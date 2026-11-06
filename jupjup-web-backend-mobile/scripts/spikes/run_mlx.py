"""T25b: MLX-LM 4bit 자유 생성(문법 없음) 지연을 llama.cpp `none` 조건과 비교한다 (설계 3.2절).

스파이크 venv에서 실행한다. 모델은 미리 받은 로컬 디렉터리에서만 연다 (HF_HUB_OFFLINE=1):
    $SPIKE_PY -I scripts/spikes/run_mlx.py --model-id <id> --model-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
from pathlib import Path
from typing import Any

os.environ["HF_HUB_OFFLINE"] = "1"

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "results" / "inputs.json"
MAX_TOKENS = 1536


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-id", required=True)
    ap.add_argument("--model-dir", required=True, type=Path)
    args = ap.parse_args()

    import mlx.core as mx
    import mlx_lm
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    inputs = json.loads(INPUTS.read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    model, tokenizer = load(str(args.model_dir))
    load_s = time.perf_counter() - t0
    sampler = make_sampler(temp=0.0)
    rows: list[dict[str, Any]] = []
    for item in inputs["items"]:
        messages = [{"role": "system", "content": item["system"]}, {"role": "user", "content": item["user"]}]
        prompt = tokenizer.apply_chat_template(messages, add_generation_prompt=True)
        t = time.perf_counter()
        text = generate(model, tokenizer, prompt=prompt, max_tokens=MAX_TOKENS, sampler=sampler, verbose=False)
        latency = time.perf_counter() - t
        completion_tokens = len(tokenizer.encode(text))
        rows.append({"id": item["id"], "latency_s": round(latency, 3), "prompt_tokens": len(prompt),
                     "completion_tokens": completion_tokens, "content": text})
        print(f"[mlx {args.model_id}] {item['id']} {latency:.1f}s {completion_tokens}tok", flush=True)
    lat = [r["latency_s"] for r in rows]
    payload = {
        "model_id": args.model_id,
        "runtime": {"mlx_lm": mlx_lm.__version__, "machine": platform.machine()},
        "load_s": round(load_s, 2),
        "peak_metal_memory_mb": round(mx.get_peak_memory() / 2**20),
        "latency_p50_s": round(_pct(lat, 0.5), 2),
        "latency_p95_s": round(_pct(lat, 0.95), 2),
        "mean_completion_tokens": round(sum(r["completion_tokens"] for r in rows) / len(rows), 1),
        "mean_tok_per_s": round(sum(r["completion_tokens"] / r["latency_s"] for r in rows) / len(rows), 1),
        "rows": rows,
    }
    out = HERE / "results" / f"{args.model_id}.mlx.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
