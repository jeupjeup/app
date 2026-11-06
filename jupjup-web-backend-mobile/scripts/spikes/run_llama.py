"""T25b: llama-cpp-python(Metal)로 한 모델의 dev 10건을 측정한다.

프로젝트 venv가 아니라 스파이크 전용 venv에서 실행한다 (기본 설치에 llama_cpp를 넣지 않기 위해):
    $SPIKE_PY -I scripts/spikes/run_llama.py --model-id <id> --model-path <gguf> [--n-ctx 16384]

모델 파일은 로컬 경로로만 연다. 이 스크립트는 네트워크를 쓰지 않는다 (HF_HUB_OFFLINE=1을 강제한다).

측정 순서 (설계 3.5절 디코딩 값 고정):
  grammar_a  문법 제약(ds-1 근사 스키마)으로 10건
  none       문법 없이 같은 프롬프트로 10건 (첫 시도 JSON 준수율 비교용)
  grammar_b  grammar_a와 같은 입력을 다시 10건 (결정성: 출력 차이 건수)
  long       긴 입력 1건, 문법 제약 (지연 상한 확인용)
호출마다 llm.reset()으로 KV 접두사 재사용을 끈다 (요청을 서로 독립으로 만든다).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import threading
import time
from pathlib import Path
from typing import Any

os.environ["HF_HUB_OFFLINE"] = "1"

import psutil

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "results" / "inputs.json"

DECODING = {
    "temperature": 0.0,
    "top_k": 1,
    "top_p": 1.0,
    "min_p": 0.0,
    "repeat_penalty": 1.0,
    "seed": 20261102,
    "n_batch": 512,
    "n_ubatch": 512,
    "n_threads": 4,
    "n_gpu_layers": -1,
    "max_tokens": 1536,
}


class RssSampler:
    def __init__(self) -> None:
        self.proc = psutil.Process()
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, self.proc.memory_info().rss)
            time.sleep(0.05)

    def __enter__(self) -> RssSampler:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()


def patched_grammar_text(schema: dict[str, Any]) -> str:
    """llama-cpp-python 0.3.36의 SchemaConverter는 `char ::= [^"\\\\]`로 원시 제어 문자를 허용한다.
    upstream llama.cpp(json-schema-to-grammar)처럼 `[^"\\\\\\x7F\\x00-\\x1F]`로 바꾼다."""
    from llama_cpp import llama_grammar

    conv = llama_grammar.SchemaConverter(prop_order={}, allow_fetch=False, dotall=False, raw_pattern=False)
    conv.visit(schema, "")
    text = conv.format_grammar()
    old = 'char ::= [^"\\\\] |'
    if old not in text:
        raise SystemExit("unexpected grammar char rule; patch not applied")
    return text.replace(old, 'char ::= [^"\\\\\\x7F\\x00-\\x1F] |')


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-id", required=True)
    ap.add_argument("--model-path", required=True, type=Path)
    ap.add_argument("--n-ctx", type=int, default=16384)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--patch-control-chars", action="store_true",
                    help="문법의 char 규칙에서 제어 문자(\\x00-\\x1F, \\x7F)를 뺀다 (0.3.36 SchemaConverter 결함 우회)")
    ap.add_argument("--passes", default="grammar_a,none,grammar_b,long")
    args = ap.parse_args()
    out = args.out or HERE / "results" / f"{args.model_id}.llama.json"

    import llama_cpp
    from llama_cpp import Llama, LlamaGrammar

    inputs = json.loads(INPUTS.read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = inputs["items"]
    schema_text = json.dumps(inputs["decoding_schema"], ensure_ascii=False)

    with RssSampler() as rss:
        t0 = time.perf_counter()
        llm = Llama(
            model_path=str(args.model_path),
            n_ctx=args.n_ctx,
            n_batch=DECODING["n_batch"],
            n_ubatch=DECODING["n_ubatch"],
            n_threads=DECODING["n_threads"],
            n_gpu_layers=DECODING["n_gpu_layers"],
            seed=DECODING["seed"],
            verbose=False,
        )
        load_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        if args.patch_control_chars:
            grammar = LlamaGrammar.from_string(patched_grammar_text(inputs["decoding_schema"]), verbose=False)
        else:
            grammar = LlamaGrammar.from_json_schema(schema_text, verbose=False)
        grammar_compile_s = time.perf_counter() - t0

        def call(item: dict[str, Any], use_grammar: bool) -> dict[str, Any]:
            llm.reset()
            messages = [{"role": "system", "content": item["system"]}, {"role": "user", "content": item["user"]}]
            t = time.perf_counter()
            resp = llm.create_chat_completion(
                messages=messages,
                grammar=grammar if use_grammar else None,
                temperature=DECODING["temperature"],
                top_k=DECODING["top_k"],
                top_p=DECODING["top_p"],
                min_p=DECODING["min_p"],
                repeat_penalty=DECODING["repeat_penalty"],
                seed=DECODING["seed"],
                max_tokens=DECODING["max_tokens"],
            )
            latency = time.perf_counter() - t
            choice = resp["choices"][0]
            usage = resp.get("usage", {})
            return {
                "id": item["id"],
                "latency_s": round(latency, 3),
                "finish_reason": choice.get("finish_reason"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "content": choice["message"]["content"],
            }

        passes: dict[str, list[dict[str, Any]]] = {}
        wanted = args.passes.split(",")
        for name, use_grammar in (("grammar_a", True), ("none", False), ("grammar_b", True)):
            if name not in wanted:
                continue
            passes[name] = []
            for item in items:
                result = call(item, use_grammar)
                passes[name].append(result)
                print(f"[{args.model_id}] {name} {item['id']} {result['latency_s']}s "
                      f"{result['completion_tokens']}tok {result['finish_reason']}", flush=True)
        if "long" in wanted:
            passes["long"] = [call(inputs["long_probe"], True)]
            print(f"[{args.model_id}] long {passes['long'][0]['latency_s']}s", flush=True)
        source_tokens = [len(llm.tokenize(i["source_document"].encode("utf-8"), add_bos=False)) for i in items]

    def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        lat = [r["latency_s"] for r in rows]
        dec = [r["completion_tokens"] / r["latency_s"] for r in rows if r["completion_tokens"]]
        return {
            "n": len(rows),
            "latency_p50_s": round(_pct(lat, 0.5), 2),
            "latency_p95_s": round(_pct(lat, 0.95), 2),
            "latency_max_s": round(max(lat), 2),
            "mean_prompt_tokens": round(sum(r["prompt_tokens"] for r in rows) / len(rows), 1),
            "mean_completion_tokens": round(sum(r["completion_tokens"] for r in rows) / len(rows), 1),
            "mean_end_to_end_tok_per_s": round(sum(dec) / len(dec), 1) if dec else None,
            "finish_length": sum(1 for r in rows if r["finish_reason"] == "length"),
        }

    shards = sorted(args.model_path.parent.glob("*.gguf"))
    payload = {
        "model_id": args.model_id,
        "model_files": [p.name for p in shards],
        "runtime": {
            "llama_cpp_python": llama_cpp.__version__,
            "gpu_offload": bool(llama_cpp.llama_supports_gpu_offload()),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "decoding": DECODING,
        "n_ctx": args.n_ctx,
        "decoding_schema_sha256": inputs["decoding_schema_sha256"],
        "grammar_patch_control_chars": args.patch_control_chars,
        "load_s": round(load_s, 2),
        "grammar_compile_s": round(grammar_compile_s, 3),
        "peak_rss_sampled_mb": round(rss.peak / 2**20),
        "ru_maxrss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20),
        "mean_source_tokens": round(sum(source_tokens) / len(source_tokens), 1),
        "summaries": {name: summary(rows) for name, rows in passes.items()},
        "passes": passes,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
