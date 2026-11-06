"""T25b: 두 번째 문법 패스(grammar_b)가 느려지는 원인을 가른다.

가설 A: 같은 LlamaGrammar 객체를 여러 호출에 재사용하면 호출마다 느려진다 (설계 5.3절 "문법 캐시"에 영향).
가설 B: 장시간 부하에 따른 열·전력 제한 (조건과 무관하게 모두 느려진다).
같은 입력으로 [재사용 문법, 매번 새 문법, 문법 없음]을 라운드마다 번갈아 돌려 조건별 tok/s 추이를 본다.

스파이크 venv에서 실행한다. 네트워크를 쓰지 않는다.
    $SPIKE_PY -I scripts/spikes/probe_grammar_reuse.py --model-id <id> --model-path <gguf> \\
        [--rounds 6] [--item syn-06-news]
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

os.environ["HF_HUB_OFFLINE"] = "1"

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-id", required=True)
    ap.add_argument("--model-path", required=True, type=Path)
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--item", default="syn-06-news")
    args = ap.parse_args()

    from llama_cpp import Llama, LlamaGrammar

    inputs = json.loads((HERE / "results" / "inputs.json").read_text(encoding="utf-8"))
    item = next(i for i in inputs["items"] if i["id"] == args.item)
    schema_text = json.dumps(inputs["decoding_schema"], ensure_ascii=False)
    llm = Llama(model_path=str(args.model_path), n_ctx=16384, n_batch=512, n_ubatch=512, n_threads=4,
                n_gpu_layers=-1, seed=20261102, verbose=False)
    reused = LlamaGrammar.from_json_schema(schema_text, verbose=False)
    messages = [{"role": "system", "content": item["system"]}, {"role": "user", "content": item["user"]}]

    def call(grammar: Any) -> dict[str, Any]:
        llm.reset()
        t = time.perf_counter()
        resp = llm.create_chat_completion(messages=messages, grammar=grammar, temperature=0.0, top_k=1, top_p=1.0,
                                          min_p=0.0, repeat_penalty=1.0, seed=20261102, max_tokens=1536)
        latency = time.perf_counter() - t
        tokens = resp["usage"]["completion_tokens"]
        return {"latency_s": round(latency, 2), "tokens": tokens, "tok_per_s": round(tokens / latency, 1),
                "content_sha": hash(resp["choices"][0]["message"]["content"])}

    rows = []
    for r in range(args.rounds):
        for cond in ("reused", "fresh", "none"):
            grammar = {"reused": reused, "fresh": None, "none": None}[cond]
            if cond == "fresh":
                grammar = LlamaGrammar.from_json_schema(schema_text, verbose=False)
            row = {"round": r, "cond": cond, **call(grammar)}
            rows.append(row)
            print(json.dumps(row), flush=True)
    out = HERE / "results" / f"probe_grammar_reuse.{args.model_id}.json"
    for row in rows:
        row.pop("content_sha")
    out.write_text(json.dumps({"model_id": args.model_id, "item": args.item, "rows": rows}, indent=1) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
