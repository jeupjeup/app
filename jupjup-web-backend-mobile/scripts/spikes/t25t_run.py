"""T25t reproducible dev-only command runner; run under caffeinate.

No model API: subprocesses use local GGUF and offline BGE caches. Reports/logs are
local ignored artifacts. Failure statuses are retained, never interpreted as PASS.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = Path("/Users/minjun/orca/workspaces/dc2/models")
PROFILES = ["tuning-kanana-2b", "tuning-qwen3-4b", "tuning-qwen25-7b", "tuning-kanana-8b"]
OUT = REPO / "reports/t25t"
CLI = [sys.executable, "-c", "from jupjup.cli import main; main()"]
ENV = {
    **os.environ,
    "PYTHONPATH": str(REPO / "src"),
    "JUPJUP_ANALYZER_CACHE_DIR": str(CACHE),
    "JUPJUP_BGE_CACHE_DIR": str(CACHE / "bge-cache"),
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
}


def disk_guard() -> None:
    free = shutil.disk_usage(CACHE).free
    if free < 15_000_000_000:
        raise RuntimeError(f"DISK STOP: {free} bytes < 15 GB")


def run(label: str, args: list[str], allowed: tuple[int, ...] = (0,)) -> None:
    disk_guard()
    started = time.time()
    command = CLI + args
    stop_reason: str | None = None
    print(label, flush=True)
    with (OUT / f"{label}.log").open("w") as log:
        process = subprocess.Popen(command, cwd=REPO, env=ENV, stdout=log, stderr=subprocess.STDOUT)
        while process.poll() is None:
            try:
                disk_guard()
            except RuntimeError as exc:
                stop_reason = str(exc)
                process.terminate()
                process.wait()
                break
            time.sleep(5)
    row = {
        "label": label,
        "argv": command,
        "exit_code": process.returncode,
        "elapsed_s": round(time.time() - started, 3),
        "free_bytes": shutil.disk_usage(CACHE).free,
    }
    if stop_reason is not None:
        row["stop_reason"] = stop_reason
    with (OUT / "commands.jsonl").open("a") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")
    if stop_reason is not None:
        raise RuntimeError(f"{label}: {stop_reason}")
    if process.returncode not in allowed:
        raise RuntimeError(f"{label} failed ({process.returncode}); inspect its log")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["dev", "final"])
    parser.add_argument("--profiles", nargs="+", default=PROFILES)
    parser.add_argument("--label", default="dev")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for profile in args.profiles:
        disk_guard()
        if args.stage == "dev":
            run(
                f"{args.label}-{profile}",
                [
                    "analyze",
                    "record",
                    "--profile",
                    profile,
                    "--split",
                    "dev",
                    "--append",
                    "--confirm-run",
                    "--out",
                    str(OUT / f"{args.label}-{profile}"),
                ],
            )
            continue
        # Final configuration has already been measured on dev; never evaluate candidate test.
        frozen = subprocess.check_output(
            [*CLI, "analyze", "freeze", "--profile", profile, "--json"], cwd=REPO, env=ENV, text=True
        )
        (OUT / f"freeze-{profile}.json").write_text(frozen)
        digest = json.loads(frozen)["frozen_config_sha256"]
        snapshot_path = OUT / f"final-config-{profile}.json"
        if not snapshot_path.exists():
            snapshot_path = REPO / "specs/artifacts/t25t/configs" / snapshot_path.name
        snapshot = json.loads(snapshot_path.read_text())
        if digest != snapshot["frozen_config_sha256"]:
            raise RuntimeError(f"{profile}: configuration changed after dev tuning")
        # Reuse successful requests; fill any missing failures from an interrupted dev run.
        run(
            f"final-dev-{profile}",
            [
                "analyze",
                "record",
                "--profile",
                profile,
                "--split",
                "dev",
                "--append",
                "--frozen-config",
                digest,
                "--confirm-run",
                "--out",
                str(OUT / f"final-dev-{profile}"),
            ],
        )
        run(
            f"seeds-{profile}",
            [
                "analyze",
                "record",
                "--profile",
                profile,
                "--target",
                "seeds",
                "--append",
                "--frozen-config",
                digest,
                "--confirm-run",
            ],
        )
        run(
            f"linkage-{profile}",
            ["analyze", "record-linkage", "--profile", profile, "--frozen-config", digest, "--force"],
        )
        for repeat in (1, 2):
            run(
                f"recorded-{profile}-{repeat}",
                [
                    "eval",
                    "ingest",
                    "--mode",
                    "recorded",
                    "--profile",
                    profile,
                    "--split",
                    "dev",
                    "--linkage",
                    "recorded",
                    "--linkage-split",
                    "dev",
                    "--frozen-config",
                    digest,
                    "--out",
                    str(OUT / f"recorded-{profile}-{repeat}"),
                ],
                allowed=(0, 1),
            )
        run(
            f"bench-{profile}",
            [
                "bench",
                "analyze",
                "--profile",
                profile,
                "--split",
                "dev",
                "--confirm-run",
                "--frozen-config",
                digest,
                "--out",
                str(OUT / f"bench-{profile}.json"),
            ],
            allowed=(0, 1),
        )


if __name__ == "__main__":
    main()
