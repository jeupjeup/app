"""T25b: 공식 safetensors(고정 revision)를 GGUF Q4_K_M으로 직접 변환한다 (설계 3.4절).

공식 GGUF가 없는 모델(Qwen3-4B-Instruct-2507, Kanana-1.5 2.1B/8B)에 쓴다. 스파이크 venv에서 실행한다.
    $SPIKE_PY -I scripts/spikes/convert_quantize.py --hf-dir <dir> --out <file.gguf> \
        --convert-script <llama.cpp>/convert_hf_to_gguf.py [--intermediate f16|q8_0]

1) llama-cpp-python 0.3.36 sdist에 들어 있는 llama.cpp의 convert_hf_to_gguf.py로 중간 GGUF(f16 기본)를 만든다.
2) llama_cpp.llama_model_quantize(ctypes)로 Q4_K_M을 만든다 (llama-quantize 바이너리와 같은 함수).
   중간 파일이 q8_0이면 allow_requantize를 켠다 (디스크가 모자랄 때만. 품질이 약간 떨어질 수 있어 리포트에 적는다).
3) 중간 파일을 지우고 최종 파일의 sha256과 크기를 출력한다. --remote가 아니면 네트워크를 쓰지 않는다.
   --remote는 디스크가 모자란 8B 모델에만 쓴다. 이때 run_all.sh가 변환 전후로 main == 고정 revision을 확인한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 24), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True, help="로컬 safetensors 디렉터리, 또는 --remote일 때 HF repo id")
    ap.add_argument("--remote", action="store_true",
                    help="convert_hf_to_gguf --remote: 텐서를 HTTP range로 읽어 "
                    "safetensors를 디스크에 두지 않는다 (main 브랜치)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--convert-script", required=True, type=Path)
    ap.add_argument("--intermediate", choices=["f16", "q8_0"], default="f16")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    mid = args.out.with_name(args.out.stem + f".{args.intermediate}.gguf")

    env = dict(os.environ) if args.remote else dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    cmd = [sys.executable, str(args.convert_script), str(args.hf_dir), "--outfile", str(mid),
           "--outtype", args.intermediate]
    if args.remote:
        cmd.append("--remote")
    t0 = time.perf_counter()
    subprocess.run(cmd, check=True, env=env)
    convert_s = time.perf_counter() - t0

    import llama_cpp

    params = llama_cpp.llama_model_quantize_default_params()
    params.ftype = llama_cpp.LLAMA_FTYPE_MOSTLY_Q4_K_M
    params.nthread = 8
    params.allow_requantize = args.intermediate != "f16"
    t0 = time.perf_counter()
    rc = llama_cpp.llama_model_quantize(str(mid).encode(), str(args.out).encode(), params)
    quantize_s = time.perf_counter() - t0
    if rc != 0:
        raise SystemExit(f"llama_model_quantize failed rc={rc}")
    mid.unlink()
    print(json.dumps({
        "out": args.out.name,
        "intermediate": args.intermediate,
        "remote": args.remote,
        "bytes": args.out.stat().st_size,
        "sha256": sha256_file(args.out),
        "convert_s": round(convert_s, 1),
        "quantize_s": round(quantize_s, 1),
        "llama_cpp_python": llama_cpp.__version__,
    }), flush=True)


if __name__ == "__main__":
    main()
