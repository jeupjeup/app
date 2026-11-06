#!/usr/bin/env bash
# T25b: 후보 모델을 하나씩 받고(또는 변환하고) 측정한 뒤 필요 없는 파일을 지운다.
# 디스크 여유가 40GB뿐이라 순서를 "작은 것 먼저, 측정 후 삭제"로 둔다.
#
# 필요한 환경 변수:
#   T25B_MODELS_DIR  모델 캐시 루트 (예: /Users/minjun/orca/workspaces/dc2/models). 저장소 밖이다.
#   T25B_SPIKE_PY    스파이크 venv 파이썬 (llama-cpp-python 0.3.36 Metal, torch, transformers, mlx-lm)
#   T25B_CONVERT     llama-cpp-python 0.3.36 sdist의 vendor/llama.cpp/convert_hf_to_gguf.py
# 사용: scripts/spikes/run_all.sh <step> [<step> ...]
#   steps: qwen25-3b exaone kanana2b qwen3 mlx qwen7b kanana8b
# 각 단계 전에 남은 디스크를 기록하고, 참고 후보(exaone, qwen25-3b)는 15GB 미만이면 건너뛴다.
# 받기 단계도 이 파일에 있다 (T25b 검수 L2): 공식 GGUF는 YAML sha256과 비교하고(--expect), 직접 변환할 모델은
# 고정 revision의 safetensors가 없을 때만 받는다. revision·sha256은 config/analyzer_profiles.yaml과 같다.
set -euo pipefail

M="${T25B_MODELS_DIR:?}"
P="${T25B_SPIKE_PY:?}"
CONVERT="${T25B_CONVERT:?}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
LOG="$M/logs"
mkdir -p "$LOG" "$M/gguf" "$M/hf" "$M/mlx"

free_gb() { df -g "$M" | awk 'NR==2 {print $4}'; }
note() { echo "[run_all $(date '+%H:%M:%S')] $* (free=$(free_gb)GB)" | tee -a "$LOG/run_all.log"; }
fetch() { "$P" -I scripts/spikes/fetch_model.py "$@" 2>&1 | grep '^{"' | tee -a "$LOG/fetch.jsonl"; }
measure() { "$P" -I scripts/spikes/run_llama.py --model-id "$1" --model-path "$2" > "$LOG/run_$1.log" 2>&1; }
hf_files() {
  curl -s "https://huggingface.co/api/models/$1/revision/$2" | python3 -c \
    "import json,sys;print(' '.join(s['rfilename'] for s in json.load(sys.stdin)['siblings'] if not s['rfilename'].startswith('.') and not s['rfilename'].endswith(('.png','.jpg','.gif'))))"
}
convert() {  # convert <hf-dir|repo> <out.gguf> "<intermediate> [--remote]"
  # shellcheck disable=SC2086
  "$P" -I scripts/spikes/convert_quantize.py --hf-dir "$1" --out "$2" --convert-script "$CONVERT" \
    --intermediate $3 > "$LOG/convert_$(basename "$2").log" 2>&1
  grep '^{"' "$LOG/convert_$(basename "$2").log" | tee -a "$LOG/convert.jsonl"
}

fetch_hf_dir() {  # fetch_hf_dir <repo> <revision> <dest>: 고정 revision 저장소 파일 전체 (이미 있으면 건너뜀)
  if [ -f "$3/config.json" ]; then note "safetensors present: $3"; return; fi
  note "fetch $1@$2"
  # shellcheck disable=SC2046
  fetch --repo "$1" --revision "$2" --dest "$3" $(hf_files "$1" "$2")
}

for step in "$@"; do
  case "$step" in
    qwen25-3b)
      if [ "$(free_gb)" -lt 15 ]; then note "skip qwen25-3b (free < 15GB)"; continue; fi
      d="$M/gguf/qwen2.5-3b-instruct-q4km"; f=qwen2.5-3b-instruct-q4_k_m.gguf
      note "fetch qwen2.5-3b"
      fetch --repo Qwen/Qwen2.5-3B-Instruct-GGUF --revision 7dabda4d13d513e3e842b20f0d435c732f172cbe --dest "$d" \
        --expect "$f=626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d" "$f" LICENSE README.md
      measure qwen2.5-3b-instruct-q4km "$d/$f"
      rm -rf "$d"; note "qwen2.5-3b measured, deleted";;
    exaone)
      if [ "$(free_gb)" -lt 15 ]; then note "skip exaone (free < 15GB)"; continue; fi
      d="$M/gguf/exaone-3.5-2.4b-instruct-q4km"; f=EXAONE-3.5-2.4B-Instruct-Q4_K_M.gguf
      if [ ! -f "$d/$f" ]; then
        note "fetch exaone"
        fetch --repo LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct-GGUF --revision 142acae803a41c206e8d0fa978c6102c748911bb \
          --dest "$d" --expect "$f=1660a3794acc33437137faab5cb3fb2b2c4191d0a4ec991d4c31a7197cb2cdbf" "$f" LICENSE README.md
      fi
      note "measure exaone"
      measure exaone-3.5-2.4b-instruct-q4km "$d/$f"
      rm -rf "$M/gguf/exaone-3.5-2.4b-instruct-q4km"; note "exaone done, deleted";;
    kanana2b)
      fetch_hf_dir kakaocorp/kanana-1.5-2.1b-instruct-2505 7df4bc35ccd610e451809d7106e1c3cf82bfd44c \
        "$M/hf/kanana-1.5-2.1b-instruct"
      note "convert kanana 2.1b (f16 -> Q4_K_M)"
      convert "$M/hf/kanana-1.5-2.1b-instruct" "$M/gguf/kanana-1.5-2.1b-instruct-q4km/kanana-1.5-2.1b-instruct-2505-Q4_K_M.gguf" f16
      rm -rf "$M/hf/kanana-1.5-2.1b-instruct"; note "kanana 2.1b converted, safetensors deleted"
      measure kanana-1.5-2.1b-instruct-q4km "$M/gguf/kanana-1.5-2.1b-instruct-q4km/kanana-1.5-2.1b-instruct-2505-Q4_K_M.gguf"
      note "kanana 2.1b measured (kept)";;
    qwen3)
      fetch_hf_dir Qwen/Qwen3-4B-Instruct-2507 cdbee75f17c01a7cc42f958dc650907174af0554 "$M/hf/qwen3-4b-instruct-2507"
      note "convert qwen3-4b-2507 (f16 -> Q4_K_M)"
      convert "$M/hf/qwen3-4b-instruct-2507" "$M/gguf/qwen3-4b-instruct-2507-q4km/Qwen3-4B-Instruct-2507-Q4_K_M.gguf" f16
      rm -rf "$M/hf/qwen3-4b-instruct-2507"; note "qwen3 converted, safetensors deleted"
      measure qwen3-4b-instruct-2507-q4km "$M/gguf/qwen3-4b-instruct-2507-q4km/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
      note "qwen3 measured (kept)";;
    mlx)
      repo=mlx-community/Qwen3-4B-Instruct-2507-4bit
      rev=$(curl -s "https://huggingface.co/api/models/$repo" | python3 -c "import json,sys;print(json.load(sys.stdin)['sha'])")
      note "fetch mlx $repo@$rev"
      fetch --repo "$repo" --revision "$rev" --dest "$M/mlx/qwen3-4b-instruct-2507-4bit" $(hf_files "$repo" "$rev")
      "$P" -I scripts/spikes/run_mlx.py --model-id qwen3-4b-instruct-2507-mlx4bit \
        --model-dir "$M/mlx/qwen3-4b-instruct-2507-4bit" > "$LOG/run_mlx.log" 2>&1
      rm -rf "$M/mlx/qwen3-4b-instruct-2507-4bit"; note "mlx measured, deleted";;
    qwen7b)
      repo=Qwen/Qwen2.5-7B-Instruct-GGUF; rev=bb5d59e06d9551d752d08b292a50eb208b07ab1f
      note "fetch qwen2.5-7b"
      fetch --repo "$repo" --revision "$rev" --dest "$M/gguf/qwen2.5-7b-instruct-q4km" \
        qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf LICENSE README.md
      measure qwen2.5-7b-instruct-q4km "$M/gguf/qwen2.5-7b-instruct-q4km/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"
      rm -rf "$M/gguf/qwen2.5-7b-instruct-q4km"; note "qwen2.5-7b measured, deleted";;
    kanana8b)
      # 16GB safetensors를 받으면 디스크가 15GB 아래로 내려가므로 --remote(HTTP range)로 변환한다.
      # --remote는 main 브랜치만 읽으므로 변환 전후 main == 고정 revision을 확인한다.
      repo=kakaocorp/kanana-1.5-8b-instruct-2505; rev=c963a5f4f6496c749f94064a20b33028b0db9f19
      main_sha() { curl -s "https://huggingface.co/api/models/$repo/revision/main" | python3 -c "import json,sys;print(json.load(sys.stdin)['sha'])"; }
      [ "$(main_sha)" = "$rev" ] || { note "kanana8b main != pinned revision, abort"; exit 3; }
      inter=q8_0; if [ "$(free_gb)" -ge 36 ]; then inter=f16; fi
      if [ "$(free_gb)" -lt 25 ]; then note "skip kanana8b (free < 25GB)"; continue; fi
      fetch --repo "$repo" --revision "$rev" --dest "$M/hf/kanana-1.5-8b-meta" LICENSE README.md config.json
      note "convert kanana 8b remote ($inter -> Q4_K_M)"
      convert "$repo" "$M/gguf/kanana-1.5-8b-instruct-q4km/kanana-1.5-8b-instruct-2505-Q4_K_M.gguf" "$inter --remote"
      [ "$(main_sha)" = "$rev" ] || { note "kanana8b main changed during conversion, abort"; exit 3; }
      measure kanana-1.5-8b-instruct-q4km "$M/gguf/kanana-1.5-8b-instruct-q4km/kanana-1.5-8b-instruct-2505-Q4_K_M.gguf"
      rm -rf "$M/gguf/kanana-1.5-8b-instruct-q4km"; note "kanana 8b measured, deleted";;
    *) echo "unknown step $step" >&2; exit 2;;
  esac
done
note "all requested steps finished"
