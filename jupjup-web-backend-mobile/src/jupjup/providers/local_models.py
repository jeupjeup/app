"""로컬 분석 모델 파일 받기와 점검 (``jupjup models pull|doctor``, 설계 3.4절, 6.8절).

**네트워크를 쓰는 곳은 이 모듈의 ``pull_model`` 하나뿐이다** (AC-L8). 서비스·워커 경로는 이 함수를 부르지 않는다.
받은 파일은 명세 sha256과 비교해 다르면 지우고 실패한다 (T25b 검수 L3).
"""

from __future__ import annotations

import importlib
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jupjup.domain.errors import AnalyzerUnavailableError
from jupjup.ingest.profiles import AnalyzerProfiles, LocalModelSpec, recording_model_id
from jupjup.providers.json_grammar import DecodingPolicyMismatchError, policies_for_version
from jupjup.providers.llm_local import file_sha256, llama_runtime_info, verified_sha256

# (repo, filename, revision, staging_dir) → 받은 파일 경로
Downloader = Callable[[str, str, str, Path], Path]

_STAGING = ".partial"


def _hf_downloader() -> Downloader:
    try:
        hub = importlib.import_module("huggingface_hub")
    except ImportError as exc:
        raise AnalyzerUnavailableError(
            "huggingface_hub이 없습니다. `uv sync --extra embed`(또는 local-models)로 설치한 뒤 다시 받으세요",
            {"retryable": False, "reason": "extra_missing"},
        ) from exc

    def download(repo: str, filename: str, revision: str, staging: Path) -> Path:
        return Path(hub.hf_hub_download(repo_id=repo, filename=filename, revision=revision, local_dir=staging))

    return download


def pull_model(spec: LocalModelSpec, cache_dir: Path, *, downloader: Downloader | None = None) -> list[Path]:
    """명세의 모든 파일을 고정 revision에서 받고 sha256을 검증한다. 이미 맞는 파일은 건너뛴다."""
    if spec.source != "hf_gguf":
        raise AnalyzerUnavailableError(
            f"{spec.model_id}는 공식 safetensors를 직접 변환한 GGUF라 저장소에서 받을 수 없습니다. "
            f"변환본을 {spec.model_path(cache_dir)}에 두세요 (sha256 {spec.sha256})",
            {"retryable": False, "reason": "model_missing", "model_id": spec.model_id, "source": spec.source},
        )
    target_dir = spec.model_dir(cache_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    staging = target_dir / _STAGING
    paths: list[Path] = []
    download: Downloader | None = downloader
    try:
        for item in spec.files:
            final = target_dir / item.filename
            if final.is_file():
                if file_sha256(final) == item.sha256:
                    paths.append(final)
                    continue
                final.unlink()
            if download is None:
                download = _hf_downloader()
            staging.mkdir(parents=True, exist_ok=True)
            try:
                received = download(spec.repo, item.filename, spec.revision, staging)
            except AnalyzerUnavailableError:
                raise
            except Exception as exc:
                raise AnalyzerUnavailableError(
                    "모델 파일을 받지 못했습니다",
                    {
                        "retryable": True,
                        "reason": "download_failed",
                        "model_id": spec.model_id,
                        "filename": item.filename,
                        "error": type(exc).__name__,
                    },
                ) from exc
            actual = file_sha256(received)
            if actual != item.sha256:
                received.unlink(missing_ok=True)
                raise AnalyzerUnavailableError(
                    "받은 모델 파일의 sha256이 명세와 달라 지웠습니다",
                    {
                        "retryable": False,
                        "reason": "sha_mismatch",
                        "model_id": spec.model_id,
                        "filename": item.filename,
                        "expected": item.sha256,
                        "actual": actual,
                    },
                )
            os.replace(received, final)
            paths.append(final)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return paths


def doctor_report(
    profiles_path: Path, cache_dir: Path, *, active_engine: str, active_profile: str | None, verify_sha: bool = True
) -> dict[str, Any]:
    """extra, 모델 파일, sha256, Metal 여부, 프로필 참조 무결성을 한 번에 점검한다. 네트워크를 쓰지 않는다."""
    report: dict[str, Any] = {
        "runtime": llama_runtime_info(),
        "cache_dir": str(cache_dir),
        "profiles_path": str(profiles_path),
        "active": {"engine": active_engine, "profile": active_profile},
        "warnings": [],
    }
    warnings: list[str] = report["warnings"]
    runtime = report["runtime"]
    if runtime["machine"] != "arm64":
        warnings.append(f"Python이 arm64가 아닙니다 ({runtime['machine']}). Apple Silicon에서는 10배 가까이 느립니다")
    if runtime.get("installed") and runtime.get("gpu_offload") is False:
        warnings.append("llama-cpp-python이 GPU 오프로드(Metal)를 지원하지 않는 빌드입니다")
    try:
        profiles = AnalyzerProfiles.load(profiles_path)
    except ValueError as exc:
        report["profiles_ok"] = False
        report["profiles_error"] = str(exc)
        report["usable"] = active_engine == "mock"
        return report
    report["profiles_ok"] = True
    report["default_profile"] = profiles.default_profile
    models: list[dict[str, Any]] = []
    for spec in profiles.models.values():
        row: dict[str, Any] = {
            "model_id": spec.model_id,
            "source": spec.source,
            "license": spec.license,
            "license_commercial_ok": spec.license_commercial_ok,
            "files": [],
        }
        present = True
        sha_ok: bool | None = True
        for item in spec.files:
            path = spec.model_dir(cache_dir) / item.filename
            exists = path.is_file()
            ok: bool | None = None
            if exists and verify_sha:
                ok = verified_sha256(path) == item.sha256
            row["files"].append({"filename": item.filename, "present": exists, "sha256_ok": ok})
            present = present and exists
            if not exists or ok is False:
                sha_ok = False
            elif ok is None and sha_ok:
                sha_ok = None
        row["present"] = present
        row["sha256_ok"] = sha_ok if present else False
        models.append(row)
    report["models"] = models
    profile_rows: list[dict[str, Any]] = []
    for profile in profiles.profiles.values():
        row = {"name": profile.name, "engine": profile.engine, "model": profile.model, "policy_ok": True}
        if profile.engine == "local":
            try:
                policies_for_version(profile.decoding.decoding_schema_version)
            except DecodingPolicyMismatchError as exc:
                row["policy_ok"] = False
                row["policy_error"] = str(exc)
            spec = profiles.model_for(profile)
            row["recording_model_id"] = recording_model_id(spec, profile.decoding)
            if not spec.license_commercial_ok:
                warnings.append(f"프로필 {profile.name}의 모델 {spec.model_id}는 상업 이용 불가 라이선스입니다")
        profile_rows.append(row)
    report["profiles"] = profile_rows
    report["usable"] = _active_usable(report, profiles, active_engine, active_profile)
    return report


def _active_usable(
    report: dict[str, Any], profiles: AnalyzerProfiles, active_engine: str, active_profile: str | None
) -> bool:
    if active_engine == "mock":
        return True
    try:
        profile = profiles.profile(active_profile)
    except ValueError:
        return False
    if profile.engine != "local":
        # 분석기 조립(container._local_profile)과 같은 규칙: engine=local이면 프로필도 local이어야 한다 (T25e 검수 L3).
        report["warnings"].append(
            f"analyzer.engine=local인데 프로필 {profile.name}의 engine은 {profile.engine}입니다. "
            "JUPJUP_ANALYZER__PROFILE로 local 프로필을 지정하세요"
        )
        return False
    if not report["runtime"].get("installed"):
        return False
    rows = {row["name"]: row for row in report["profiles"]}
    models = {row["model_id"]: row for row in report["models"]}
    needed = {profiles.model_for(profile).model_id, profiles.model_for(profile, chunk=True).model_id}
    return (
        bool(rows[profile.name]["policy_ok"])
        and all(models[m]["sha256_ok"] is not False for m in needed)
        and all(models[m]["present"] for m in needed)
    )
