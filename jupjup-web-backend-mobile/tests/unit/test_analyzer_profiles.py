"""T25d: 분석기 프로필, recording_model_id, 설정, models pull|doctor. 설계 3.4, 6.2, 6.7, 6.8, 7.2절."""

from __future__ import annotations

import hashlib
import json
import re
import socket
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from jupjup.cli import app
from jupjup.config import REPO_ROOT, AnalyzerSettings, Settings
from jupjup.domain.errors import (
    AnalyzerUnavailableError,
    LLMContextOverflowError,
    LLMProviderError,
    LLMTimeoutError,
    ProviderError,
)
from jupjup.ingest.profiles import (
    AnalyzerProfiles,
    DecodingParams,
    LocalModelSpec,
    recording_file_stem,
    recording_model_id,
)
from jupjup.providers.local_models import doctor_report, pull_model
from tests.unit._fake_llama import block_llama_import

YAML_PATH = REPO_ROOT / "config" / "analyzer_profiles.yaml"


def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    return raw


def _write(tmp_path: Path, raw: dict[str, Any]) -> Path:
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


# --- 프로필 로더 -------------------------------------------------------------------------------------------


def test_committed_profiles_load() -> None:
    profiles = AnalyzerProfiles.load(YAML_PATH)
    assert profiles.default_profile == "mock"
    assert profiles.profile().engine == "mock"
    assert len(profiles.models) == 6
    assert {m.source for m in profiles.models.values()} == {"hf_gguf", "local_convert"}
    qwen7b = profiles.models["qwen2.5-7b-instruct-q4km"]
    assert [f.filename for f in qwen7b.files] == [
        "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",
        "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf",
    ]
    for name, profile in profiles.profiles.items():
        if profile.engine == "local":
            assert profiles.model_for(profile).model_id == profile.model, name
            if name.startswith("tuning-"):
                assert profile.decoding == DecodingParams(decoding_schema_version="ds-3")
            else:
                assert profile.decoding == DecodingParams()
    assert not profiles.models["exaone-3.5-2.4b-instruct-q4km"].license_commercial_ok


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r["profiles"]["local-qwen3-4b"].__setitem__("model", "nope"), "없는 모델"),
        (lambda r: r["profiles"]["local-qwen3-4b"].__setitem__("chunk_model", "nope"), "chunk_model"),
        (lambda r: r["models"]["qwen3-4b-instruct-2507-q4km"].__setitem__("model_id", "other"), "model_id가 키와"),
        (lambda r: r.__setitem__("default_profile", "nope"), "default_profile"),
        (lambda r: r["judges"]["judge-kanana-8b"].__setitem__("model", "nope"), "judges"),
        (lambda r: r["profiles"]["local-qwen3-4b"].pop("model"), "model이 필요"),
        (lambda r: r["profiles"]["mock"].__setitem__("model", "qwen3-4b-instruct-2507-q4km"), "mock 프로필"),
        (lambda r: r["models"]["qwen3-4b-instruct-2507-q4km"].__setitem__("sha256", "ABC"), "sha256"),
        (lambda r: r["models"]["qwen3-4b-instruct-2507-q4km"].__setitem__("filename", "../x.gguf"), "경로 구분자"),
        (lambda r: r["models"]["qwen3-4b-instruct-2507-q4km"].__setitem__("revision", "main"), "revision"),
        (lambda r: r["models"]["qwen3-4b-instruct-2507-q4km"].__setitem__("n_ctx", 512), "n_ctx"),
        (
            lambda r: r["profiles"]["local-qwen3-4b"].__setitem__("routes", [{"platforms": ["x"], "profile": "?"}]),
            "routes",
        ),
        (lambda r: r["profiles"]["local-qwen3-4b"].__setitem__("unknown", 1), "unknown"),
        (lambda r: r.__setitem__("version", 2), "version"),
    ],
)
def test_reference_integrity_errors(tmp_path: Path, mutate: Any, message: str) -> None:
    raw = _raw()
    mutate(raw)
    with pytest.raises(ValueError, match=message):
        AnalyzerProfiles.load(_write(tmp_path, raw))


def test_unreadable_profiles_raise_value_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="읽지 못했습니다"):
        AnalyzerProfiles.load(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: [1", encoding="utf-8")
    with pytest.raises(ValueError, match="읽지 못했습니다"):
        AnalyzerProfiles.load(bad)


# --- recording_model_id ------------------------------------------------------------------------------------


def _spec(sha: str = "3f9a0c1d2e4b" + "0" * 52) -> LocalModelSpec:
    return LocalModelSpec(
        model_id="qwen3-4b-instruct-2507-q4km",
        repo="Qwen/Qwen3-4B-Instruct-2507",
        revision="c" * 40,
        filename="Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        sha256=sha,
        license="apache-2.0",
        license_commercial_ok=True,
    )


def test_recording_model_id_is_deterministic() -> None:
    a = recording_model_id(_spec(), DecodingParams())
    assert a == recording_model_id(_spec(), DecodingParams())
    assert re.fullmatch(r"qwen3-4b-instruct-2507-q4km@3f9a0c1d2e4b~[0-9a-f]{8}", a)
    # 고정값: DecodingParams 기본값이 바뀌면 이 값도 바뀌어야 한다 (녹화가 다시 필요하다는 신호)
    assert DecodingParams().fingerprint() == "bbdbf37b"
    assert recording_file_stem(a) == a.replace("@", "_at_").replace("~", "_dec_")
    assert "@" not in recording_file_stem(a) and "~" not in recording_file_stem(a)


@pytest.mark.parametrize(
    "change",
    [
        {"temperature": 0.1},
        {"top_k": 2},
        {"top_p": 0.9},
        {"min_p": 0.05},
        {"repeat_penalty": 1.1},
        {"seed": 1},
        {"n_batch": 256},
        {"n_ubatch": 256},
        {"n_threads": 8},
        {"constrained": "none"},
        {"decoding_schema_version": "ds-2"},
    ],
)
def test_every_decoding_field_changes_fingerprint(change: dict[str, Any]) -> None:
    base = recording_model_id(_spec(), DecodingParams())
    assert recording_model_id(_spec(), DecodingParams(**change)) != base


def test_model_sha_changes_recording_id() -> None:
    assert recording_model_id(_spec(), DecodingParams()) != recording_model_id(_spec("a" * 64), DecodingParams())


def test_recording_file_stem_rejects_unsafe() -> None:
    with pytest.raises(ValueError):
        recording_file_stem("../escape@x")


# --- 설정과 에러 -------------------------------------------------------------------------------------------


def test_analyzer_settings_defaults_and_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = Settings()
    assert settings.analyzer == AnalyzerSettings()
    assert settings.analyzer.engine == "mock" and settings.analyzer.required is False
    assert settings.analyzer.profiles_path == YAML_PATH
    assert settings.analyzer_cache_dir == REPO_ROOT / "var" / "models"
    monkeypatch.setenv("JUPJUP_ANALYZER_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("JUPJUP_ANALYZER__ENGINE", "local")
    monkeypatch.setenv("JUPJUP_ANALYZER__PROFILE", "local-kanana-2b")
    settings = Settings()
    assert settings.analyzer_cache_dir == tmp_path
    assert (settings.analyzer.engine, settings.analyzer.profile) == ("local", "local-kanana-2b")


def test_error_codes_and_hierarchy() -> None:
    assert LLMTimeoutError.code == "LLM_TIMEOUT" and issubclass(LLMTimeoutError, LLMProviderError)
    assert LLMContextOverflowError.code == "LLM_CONTEXT_OVERFLOW" and issubclass(
        LLMContextOverflowError, LLMProviderError
    )
    assert AnalyzerUnavailableError.code == "ANALYZER_UNAVAILABLE"
    assert issubclass(AnalyzerUnavailableError, ProviderError)
    assert not issubclass(AnalyzerUnavailableError, LLMProviderError)


# --- models pull -------------------------------------------------------------------------------------------


def _hf_spec(content: bytes, **extra: Any) -> LocalModelSpec:
    return LocalModelSpec(
        model_id="tiny-q4km",
        repo="org/tiny-GGUF",
        revision="1" * 40,
        filename="tiny.gguf",
        sha256=hashlib.sha256(content).hexdigest(),
        license="apache-2.0",
        license_commercial_ok=True,
        **extra,
    )


class FakeHub:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, repo: str, filename: str, revision: str, staging: Path) -> Path:
        self.calls.append((repo, filename, revision))
        path = staging / filename
        path.write_bytes(self.files[filename])
        return path


def test_pull_verifies_and_moves_files(tmp_path: Path) -> None:
    extra = [{"filename": "tiny-2.gguf", "sha256": hashlib.sha256(b"two").hexdigest()}]
    spec = _hf_spec(b"one", extra_files=extra)
    hub = FakeHub({"tiny.gguf": b"one", "tiny-2.gguf": b"two"})
    paths = pull_model(spec, tmp_path, downloader=hub)
    assert [p.name for p in paths] == ["tiny.gguf", "tiny-2.gguf"]
    assert hub.calls == [("org/tiny-GGUF", "tiny.gguf", "1" * 40), ("org/tiny-GGUF", "tiny-2.gguf", "1" * 40)]
    assert not (spec.model_dir(tmp_path) / ".partial").exists()
    again = FakeHub({})
    assert pull_model(spec, tmp_path, downloader=again) == paths and again.calls == []  # 이미 맞으면 받지 않는다


def test_pull_deletes_file_on_sha_mismatch(tmp_path: Path) -> None:
    spec = _hf_spec(b"expected")
    with pytest.raises(AnalyzerUnavailableError) as info:
        pull_model(spec, tmp_path, downloader=FakeHub({"tiny.gguf": b"tampered"}))
    assert info.value.details["reason"] == "sha_mismatch"
    model_dir = spec.model_dir(tmp_path)
    assert not (model_dir / "tiny.gguf").exists() and not (model_dir / ".partial").exists()


def test_l4_pull_model_wraps_downloader_network_error_and_cleans_staging(tmp_path: Path) -> None:
    spec = _hf_spec(b"expected")

    def fail_download(_repo: str, _filename: str, _revision: str, staging: Path) -> Path:
        (staging / "unfinished").write_text("partial", encoding="utf-8")
        raise ConnectionError("offline")

    with pytest.raises(AnalyzerUnavailableError) as info:
        pull_model(spec, tmp_path, downloader=fail_download)

    assert info.value.details["reason"] == "download_failed"
    assert info.value.details["error"] == "ConnectionError"
    assert info.value.details["retryable"] is True
    assert not (spec.model_dir(tmp_path) / ".partial").exists()


def test_pull_replaces_corrupt_existing_file(tmp_path: Path) -> None:
    spec = _hf_spec(b"good")
    spec.model_dir(tmp_path).mkdir(parents=True)
    spec.model_path(tmp_path).write_bytes(b"corrupt")
    hub = FakeHub({"tiny.gguf": b"good"})
    pull_model(spec, tmp_path, downloader=hub)
    assert spec.model_path(tmp_path).read_bytes() == b"good" and len(hub.calls) == 1


def test_pull_refuses_local_convert_models(tmp_path: Path) -> None:
    spec = _hf_spec(b"x", source="local_convert")
    hub = FakeHub({})
    with pytest.raises(AnalyzerUnavailableError, match="직접 변환한"):
        pull_model(spec, tmp_path, downloader=hub)
    assert hub.calls == []


def test_pull_without_huggingface_hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(__import__("sys").modules, "huggingface_hub", None)
    with pytest.raises(AnalyzerUnavailableError) as info:
        pull_model(_hf_spec(b"x"), tmp_path)
    assert info.value.details["reason"] == "extra_missing"


# --- models doctor -----------------------------------------------------------------------------------------


def _deny_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    attempts: list[str] = []

    def blocked(*args: Any, **kwargs: Any) -> Any:
        attempts.append("net")
        raise OSError("blocked")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    return attempts


def test_doctor_reports_files_sha_and_licenses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = _deny_network(monkeypatch)
    block_llama_import(monkeypatch)
    raw = _raw()
    content = b"kanana"
    spec = raw["models"]["kanana-1.5-2.1b-instruct-q4km"]
    spec["sha256"] = hashlib.sha256(content).hexdigest()
    model_dir = tmp_path / "gguf" / spec["model_id"]
    model_dir.mkdir(parents=True)
    (model_dir / spec["filename"]).write_bytes(content)
    qwen = raw["models"]["qwen3-4b-instruct-2507-q4km"]
    (tmp_path / "gguf" / qwen["model_id"]).mkdir(parents=True)
    (tmp_path / "gguf" / qwen["model_id"] / qwen["filename"]).write_bytes(b"wrong")
    path = _write(tmp_path, raw)
    report = doctor_report(path, tmp_path, active_engine="local", active_profile="local-kanana-2b")
    rows = {row["model_id"]: row for row in report["models"]}
    assert rows["kanana-1.5-2.1b-instruct-q4km"]["sha256_ok"] is True
    assert rows["qwen3-4b-instruct-2507-q4km"]["sha256_ok"] is False
    assert rows["exaone-3.5-2.4b-instruct-q4km"]["present"] is False
    assert report["runtime"]["installed"] is False
    assert report["usable"] is False  # extra가 없으면 local 프로필은 못 쓴다
    assert any("상업 이용 불가" in w for w in report["warnings"])
    assert attempts == []
    json.dumps(report, ensure_ascii=False)


def test_doctor_rejects_local_engine_with_mock_profile_like_the_worker(tmp_path: Path) -> None:
    """T25e 검수 L3: engine=local + 프로필 미지정(기본 mock)은 worker run처럼 doctor도 "사용 불가"다."""
    report = doctor_report(_write(tmp_path, _raw()), tmp_path, active_engine="local", active_profile=None)
    assert report["usable"] is False
    assert any("JUPJUP_ANALYZER__PROFILE" in w for w in report["warnings"])


def test_doctor_with_broken_profiles(tmp_path: Path) -> None:
    raw = _raw()
    raw["default_profile"] = "nope"
    report = doctor_report(_write(tmp_path, raw), tmp_path, active_engine="mock", active_profile=None)
    assert report["profiles_ok"] is False and report["usable"] is True


def test_cli_models_doctor_and_pull(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUPJUP_ANALYZER_CACHE_DIR", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["models", "doctor", "--no-sha"])
    assert result.exit_code == 0, result.output
    assert "default_profile=mock" in result.output and "사용 가능" in result.output
    result = runner.invoke(app, ["models", "doctor", "--json", "--no-sha"])
    assert json.loads(result.output)["usable"] is True
    monkeypatch.setenv("JUPJUP_ANALYZER__ENGINE", "local")
    monkeypatch.setenv("JUPJUP_ANALYZER__PROFILE", "local-kanana-2b")
    assert runner.invoke(app, ["models", "doctor", "--no-sha"]).exit_code == 1
    result = runner.invoke(app, ["models", "pull", "no-such-model"])
    assert result.exit_code == 2 and "없는 모델" in result.output
    result = runner.invoke(app, ["models", "pull", "kanana-1.5-2.1b-instruct-q4km"])
    assert result.exit_code == 2 and "직접 변환한" in result.output
