"""T25b: Hugging Face 공식 저장소에서 고정 revision의 파일을 받아 sha256을 기록한다.

스파이크 venv에서 실행한다. 이 스크립트만 네트워크를 쓴다 (측정 스크립트는 오프라인).
    $SPIKE_PY -I scripts/spikes/fetch_model.py --repo <repo> --revision <commit> --dest <dir> FILE [FILE ...]

출력: dest 아래 파일, 표준 출력에 파일별 sha256과 크기(JSON 한 줄).
`--expect FILE=SHA256`을 주면 받은 파일과 비교해, 다르면 파일을 지우고 종료 코드 2로 끝낸다 (T25b 검수 L3).
제품 경로의 받기는 `jupjup models pull`(명세 sha256 필수 검증)이다. 이 스크립트는 스파이크 재현용이다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 24), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    from huggingface_hub import hf_hub_download

    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--dest", required=True, type=Path)
    ap.add_argument("--expect", action="append", default=[], metavar="FILE=SHA256",
                    help="받은 파일의 기대 sha256. 다르면 파일을 지우고 종료 2")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()
    expected = dict(item.split("=", 1) for item in args.expect)
    unknown = sorted(set(expected) - set(args.files))
    if unknown:
        raise SystemExit(f"--expect에 받지 않는 파일이 있습니다: {unknown}")
    args.dest.mkdir(parents=True, exist_ok=True)
    for name in args.files:
        path = Path(hf_hub_download(args.repo, name, revision=args.revision, local_dir=args.dest))
        digest = sha256_file(path)
        print(json.dumps({"repo": args.repo, "revision": args.revision, "file": name,
                          "bytes": path.stat().st_size, "sha256": digest}), flush=True)
        if name in expected and digest != expected[name]:
            path.unlink()
            print(f"sha256 mismatch for {name}: expected {expected[name]}, got {digest} (deleted)", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
