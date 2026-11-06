"""CLI: seed load, index rebuild, search, eval validate (종료 코드 포함)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jupjup.cli import app
from tests.conftest import DATA

runner = CliRunner()
SEEDS = str(DATA / "golden" / "seeds.jsonl")
NOW = "2026-10-15T12:00+09:00"


def test_seed_load_search_rebuild(tmp_path: Path) -> None:
    db = str(tmp_path / "j.db")
    r = runner.invoke(app, ["seed", "load", SEEDS, "--db", db, "--strict"])
    assert r.exit_code == 0, r.output
    assert "적재 200" in r.output and "u_alice 160" in r.output

    r = runner.invoke(
        app, ["search", "지난달 인스타에서 본 성수동 카페", "--user", "u_alice", "--now", NOW, "--db", db]
    )
    assert r.exit_code == 0, r.output
    assert "'지난달' → 2026-09-01 ~ 2026-10-01" in r.output
    assert "인스타그램(hard)" in r.output
    lines = r.output.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith("  1. "))
    assert "c_alice_0001" in lines[first + 1]

    r = runner.invoke(app, ["search", "성수동 카페", "--user", "u_bob", "--now", NOW, "--db", db, "--json"])
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["results"] and all(x["content_id"].startswith("c_bob_") for x in data["results"])

    r = runner.invoke(
        app,
        [
            "search",
            "인스타에서 본 성수동 카페",
            "--user",
            "u_alice",
            "--now",
            NOW,
            "--db",
            db,
            "--platform",
            "youtube",
            "--json",
        ],
    )
    data = json.loads(r.output)
    assert data["overridden_by_request"] == ["platforms"]
    assert all(x["platform"] == "youtube" for x in data["results"])

    r = runner.invoke(app, ["index", "rebuild", "--db", db])
    assert r.exit_code == 0 and "문서 200" in r.output and "새 임베딩 0" in r.output


def test_seed_load_default_path_and_rank_line_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """데모 명령은 경로 생략을 허용하고, 지연의 ``2.6ms``를 2위로 오인하지 않는다."""
    db = tmp_path / "default.db"
    monkeypatch.setenv("JUPJUP_DB_PATH", str(db))
    loaded = runner.invoke(app, ["seed", "load", "--strict"])
    assert loaded.exit_code == 0, loaded.output
    assert "적재 200" in loaded.output

    result = runner.invoke(
        app,
        ["search", "지난달 인스타에서 본 성수동 카페", "--user", "u_alice", "--now", NOW],
    )
    assert result.exit_code == 0, result.output
    rank_lines = [line for line in result.output.splitlines() if line.startswith("  ") and ". [" in line]
    assert rank_lines and rank_lines[0].startswith("  1. ")
    assert all("ms]" not in line for line in rank_lines)


def test_search_errors(tmp_path: Path) -> None:
    db = str(tmp_path / "j.db")
    runner.invoke(app, ["seed", "load", SEEDS, "--db", db])
    r = runner.invoke(app, ["search", "!!!", "--user", "u_alice", "--now", NOW, "--db", db])
    assert r.exit_code == 2 and "INVALID_QUERY" in r.output
    r = runner.invoke(app, ["search", "카페", "--user", "u_alice", "--now", "2026-10-15T12:00", "--db", db])
    assert r.exit_code == 2 and "[INVALID_FILTER]" in r.output and "--now에는 시간대" in r.output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--platform", "tiktok"], "필터 값이 올바르지"),
        (["--type", "podcast"], "필터 값이 올바르지"),
        (["--from", "not-a-time"], "--from은 ISO 8601"),
        (["--from", "2026-10-01T00:00"], "--from에는 시간대"),
        (["--to", "2026-10-31T00:00"], "--to에는 시간대"),
    ],
)
def test_search_filter_errors_are_clean(tmp_path: Path, args: list[str], message: str) -> None:
    db = str(tmp_path / "j.db")
    runner.invoke(app, ["seed", "load", SEEDS, "--db", db])
    result = runner.invoke(
        app,
        ["search", "카페", "--user", "u_alice", "--now", NOW, "--db", db, *args],
    )
    assert result.exit_code == 2
    assert "[INVALID_FILTER]" in result.output and message in result.output
    assert "Traceback" not in result.output and str(Path.cwd()) not in result.output


def test_seed_load_bad_file(tmp_path: Path) -> None:
    p = tmp_path / "bad.jsonl"
    p.write_text('{"id": "x"}\n', encoding="utf-8")
    r = runner.invoke(app, ["seed", "load", str(p), "--db", str(tmp_path / "j.db"), "--strict"])
    assert r.exit_code == 1 and "INVALID_CONTENT" in r.output and "아무것도 적재하지 않았습니다" in r.output
    r = runner.invoke(app, ["seed", "load", str(tmp_path / "none.jsonl"), "--db", str(tmp_path / "j.db")])
    assert r.exit_code == 2


def test_eval_validate() -> None:
    r = runner.invoke(app, ["eval", "validate"])
    assert r.exit_code == 0 and "검증 통과" in r.output and "review_status" in r.output
    assert "needs_human_review 24" in r.output
    assert "review_metadata: reviewed 0, reviewers 0" in r.output


def test_eval_ingest_mock_cli(tmp_path: Path) -> None:
    result = runner.invoke(app, ["eval", "ingest", "--mode", "mock", "--split", "test", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "인제스트 평가 mode=mock split=test — PASS" in result.output
    report = json.loads((tmp_path / "eval_ingest_mock_test.json").read_text(encoding="utf-8"))
    assert report["overall"]["schema_final_pass_rate"] == 1.0
    assert report["overall"]["tag_f1"] is None


def test_eval_ingest_recorded_mode_requires_local_profile(tmp_path: Path) -> None:
    # T25f: recorded/live는 local 프로필로만 돈다 (mock 프로필이면 설정 오류, 종료 2).
    result = runner.invoke(
        app,
        ["eval", "ingest", "--mode", "recorded", "--split", "dev", "--out", str(tmp_path)],
    )
    assert result.exit_code == 2
    assert "local 프로필이 필요합니다" in result.output


def test_eval_ingest_cli_reports_runtime_and_write_errors_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jupjup.domain.errors import ExtractionError
    from jupjup.eval.ingest_harness import IngestEvalConfig, IngestEvalHarness

    monkeypatch.setattr(IngestEvalHarness, "run", lambda _self: (_ for _ in ()).throw(ExtractionError("실패")))
    runtime_error = runner.invoke(app, ["eval", "ingest", "--mode", "mock", "--split", "test"])
    assert runtime_error.exit_code == 2
    assert "인제스트 평가 오류: 실패" in runtime_error.output
    assert "Traceback" not in runtime_error.output

    monkeypatch.undo()
    report = IngestEvalHarness(IngestEvalConfig(split="test")).run()
    monkeypatch.setattr(IngestEvalHarness, "run", lambda _self: report)
    monkeypatch.setattr(
        "jupjup.eval.ingest_report.write_ingest_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("쓰기 실패")),
    )
    write_error = runner.invoke(
        app,
        ["eval", "ingest", "--mode", "mock", "--split", "test", "--out", str(tmp_path)],
    )
    assert write_error.exit_code == 2
    assert "인제스트 평가 오류: 쓰기 실패" in write_error.output
    assert "Traceback" not in write_error.output


def test_eval_run_bad_args() -> None:
    r = runner.invoke(app, ["eval", "run", "--mode", "nope"])
    assert r.exit_code == 2


def test_embedding_record_validates_device_and_existing_output(tmp_path: Path) -> None:
    bad = runner.invoke(app, ["embedding", "record", "--device", "cuda"])
    assert bad.exit_code == 2 and "auto|cpu|mps" in bad.output
    output = tmp_path / "recording.jsonl"
    output.write_text("existing\n", encoding="utf-8")
    exists = runner.invoke(app, ["embedding", "record", "--output", str(output)])
    assert exists.exit_code == 2 and "이미 있습니다" in exists.output


def test_demo_serve_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_run(application: object, *, host: str, port: int) -> None:
        called.update(application=application, host=host, port=port)

    monkeypatch.setattr("uvicorn.run", fake_run)
    db = tmp_path / "demo.db"
    r = runner.invoke(app, ["demo", "serve", "--db", str(db), "--port", "8780"])
    assert r.exit_code == 0, r.output
    assert called["host"] == "127.0.0.1" and called["port"] == 8780
    assert "http://127.0.0.1:8780" in r.output


def test_api_serve_defaults_to_loopback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_run(application: object, *, host: str, port: int) -> None:
        called.update(application=application, host=host, port=port)

    monkeypatch.setattr("uvicorn.run", fake_run)
    result = runner.invoke(app, ["api", "serve", "--db", str(tmp_path / "api.db")])
    assert result.exit_code == 0, result.output
    assert called["host"] == "127.0.0.1" and called["port"] == 8000
    assert "http://127.0.0.1:8000" in result.output


@pytest.mark.parametrize("mode", ["recorded", "live"])
def test_demo_serve_supports_embedding_modes(
    mode: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    def fake_run(application: object, *, host: str, port: int) -> None:
        called["application"] = application

    monkeypatch.setattr("uvicorn.run", fake_run)
    result = runner.invoke(
        app,
        ["demo", "serve", "--db", str(tmp_path / f"{mode}.db"), "--mode", mode],
    )
    assert result.exit_code == 0, result.output
    application = called["application"]
    assert application.state.container.settings.mode == mode  # type: ignore[attr-defined]
    if mode == "live":
        recording_path = application.state.container.settings.recording_path  # type: ignore[attr-defined]
        assert recording_path.parent.parent.name == "var"
        assert "data/recordings" not in recording_path.as_posix()


def test_demo_serve_rejects_external_bind_without_risk_flag(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["demo", "serve", "--db", str(tmp_path / "demo.db"), "--host", "0.0.0.0"],
    )
    assert result.exit_code == 2
    assert "외부 바인딩은 기본으로 거부" in result.output


def test_demo_serve_external_bind_requires_explicit_risk_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    def fake_run(application: object, *, host: str, port: int) -> None:
        called.update(application=application, host=host, port=port)

    monkeypatch.setattr("uvicorn.run", fake_run)
    result = runner.invoke(
        app,
        [
            "demo",
            "serve",
            "--db",
            str(tmp_path / "demo.db"),
            "--host",
            "0.0.0.0",
            "--allow-external-bind",
        ],
    )
    assert result.exit_code == 0
    assert called["host"] == "0.0.0.0"
    assert "경고: 인증 없는 dev 데모" in result.output


def test_demo_serve_preserves_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUPJUP_ENV", "prod")
    result = runner.invoke(app, ["demo", "serve", "--db", str(tmp_path / "demo.db")])
    assert result.exit_code == 2
    assert "dev/test 환경에서만" in result.output
