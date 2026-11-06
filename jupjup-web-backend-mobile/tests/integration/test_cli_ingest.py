"""T23 CLI: ingest submit/status, worker run, seed load --analyze."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jupjup.cli import app
from jupjup.config import Settings
from jupjup.container import build_container
from tests.conftest import DATA

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ingest"
SEEDS = DATA / "golden" / "seeds.jsonl"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _ingest_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUPJUP_ENV", "dev")
    monkeypatch.setenv("JUPJUP_MODE", "mock")
    monkeypatch.setenv("JUPJUP_INGEST_FIXTURES_DIR", str(FIXTURES))


def _json(output: str) -> dict[str, object]:
    return json.loads(output.strip().splitlines()[-1])  # type: ignore[no-any-return]


def test_submit_inline_status_and_search(tmp_path: Path) -> None:
    db = str(tmp_path / "j.db")
    text = "은하수조약돌 관찰 기록입니다."
    args = ["--user", "u_alice", "--text", text, "--note", "메모", "--inline", "--json", "--db", db]
    r = runner.invoke(app, ["ingest", "submit", *args])
    assert r.exit_code == 0, r.output
    submitted = _json(r.output)
    assert submitted["status"] == "succeeded" and submitted["stage"] == "index"

    r = runner.invoke(app, ["ingest", "status", str(submitted["job_id"]), "--user", "u_alice", "--json", "--db", db])
    assert r.exit_code == 0, r.output
    assert _json(r.output) == submitted

    r = runner.invoke(app, ["ingest", "status", str(submitted["job_id"]), "--user", "u_bob", "--db", db])
    assert r.exit_code == 1 and "찾을 수 없습니다" in r.output

    r = runner.invoke(app, ["search", "은하수조약돌", "--user", "u_alice", "--db", db, "--json"])
    assert r.exit_code == 0, r.output
    assert [item["content_id"] for item in json.loads(r.output)["results"]] == [submitted["content_id"]]


def test_submit_queues_and_worker_run_once_processes(tmp_path: Path) -> None:
    db = str(tmp_path / "j.db")
    job_ids = []
    for args in (
        ["--fixture", "html/article.html", "--platform", "news", "--url", "https://example.com/a"],
        ["--fixture", "transcript/sample.vtt", "--platform", "youtube"],
        ["--ocr-text", "청동나침반 전시 입장권"],
    ):
        r = runner.invoke(app, ["ingest", "submit", "--user", "u_alice", *args, "--json", "--db", db])
        assert r.exit_code == 0, r.output
        queued = _json(r.output)
        assert (queued["status"], queued["stage"], queued["attempts"]) == ("queued", "fetch", 0)
        job_ids.append(str(queued["job_id"]))

    r = runner.invoke(app, ["worker", "run", "--max-jobs", "1", "--db", db])
    assert r.exit_code == 0 and "처리한 잡 1" in r.output, r.output
    r = runner.invoke(app, ["worker", "run", "--once", "--concurrency", "1", "--db", db])
    assert r.exit_code == 0 and "처리한 잡 2" in r.output, r.output
    for job_id in job_ids:
        r = runner.invoke(app, ["ingest", "status", job_id, "--user", "u_alice", "--json", "--db", db])
        assert _json(r.output)["status"] == "succeeded", r.output
    r = runner.invoke(app, ["worker", "run", "--once", "--db", db])
    assert "처리한 잡 0" in r.output


def test_failed_inline_job_exits_1(tmp_path: Path) -> None:
    args = ["--user", "u_alice", "--fixture", "html/none.html", "--inline", "--json", "--db", str(tmp_path / "j.db")]
    r = runner.invoke(app, ["ingest", "submit", *args])
    assert r.exit_code == 1, r.output
    data = _json(r.output)
    assert data["status"] == "failed" and data["last_error"]["code"] == "INGEST_UNSUPPORTED"  # type: ignore[index]


@pytest.mark.parametrize(
    "args",
    [
        ["--user", "u_alice"],
        ["--user", "u_alice", "--text", "본문", "--fixture", "html/article.html"],
        ["--user", "alice", "--text", "본문"],
        ["--user", "u_alice", "--fixture", "../etc/passwd.html"],
        ["--user", "u_alice", "--text", "본문", "--url", "https://e.com"],
        ["--user", "u_alice", "--text", "본문", "--platform", "myspace"],
        ["--user", "u_alice", "--text", "본문", "--saved-at", "2026-10-20T19:00"],
    ],
)
def test_submit_rejects_bad_input_with_exit_2(tmp_path: Path, args: list[str]) -> None:
    db = tmp_path / "j.db"
    r = runner.invoke(app, ["ingest", "submit", *args, "--db", str(db)])
    assert r.exit_code == 2, r.output


@pytest.mark.parametrize("env", ["prod", "test"])
def test_ingest_commands_are_dev_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("JUPJUP_ENV", env)
    db = str(tmp_path / "j.db")
    for args in (
        ["ingest", "submit", "--user", "u_alice", "--text", "본문"],
        ["ingest", "status", f"job_{'0' * 32}", "--user", "u_alice"],
        ["worker", "run", "--once"],
    ):
        r = runner.invoke(app, [*args, "--db", db])
        assert r.exit_code == 2 and "JUPJUP_ENV=dev" in r.output, r.output


def _seed_subset(tmp_path: Path, count: int) -> Path:
    lines = [line for line in SEEDS.read_text(encoding="utf-8").splitlines() if line.strip()][:count]
    path = tmp_path / "seeds.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_seed_load_analyze_replaces_human_analysis_but_keeps_user_values(tmp_path: Path) -> None:
    db = tmp_path / "j.db"
    seeds = _seed_subset(tmp_path, 5)
    r = runner.invoke(app, ["seed", "load", str(seeds), "--analyze", "--strict", "--db", str(db)])
    assert r.exit_code == 0, r.output
    assert "적재 5 / 잡 5 / 상태: succeeded 5" in r.output

    container = build_container(Settings(env="dev", mode="mock", data_dir=DATA, db_path=db))
    bundle = container.repo.get_bundle("u_alice", "c_alice_0001")
    assert bundle.content.status == "ready" and not bundle.content.analysis_pending
    assert bundle.summary is not None and bundle.summary.model == "mock-analyzer-v1"
    assert ("주말데이트", "user") in {(tag.name, tag.source) for tag in bundle.tags}
    assert all(tag.source in ("ai", "user") for tag in bundle.tags)
    assert bundle.snapshot is not None and "어니언" in bundle.snapshot.text
    assert bundle.detail_tags is not None and bundle.detail_tags.ai_json.get("category") == "other"

    # replace-user 재적재는 멱등이다 (잡이 다시 만들어지고 같은 결과가 나온다).
    r = runner.invoke(app, ["seed", "load", str(seeds), "--analyze", "--replace-user", "--db", str(db)])
    assert r.exit_code == 0, r.output
    assert container.repo.count("u_alice") == 5


def test_seed_load_analyze_no_inline_leaves_jobs_for_worker(tmp_path: Path) -> None:
    db = str(tmp_path / "j.db")
    seeds = _seed_subset(tmp_path, 3)
    r = runner.invoke(app, ["seed", "load", str(seeds), "--analyze", "--no-inline", "--db", db])
    assert r.exit_code == 0, r.output
    assert "상태: queued 3" in r.output
    r = runner.invoke(app, ["search", "어니언", "--user", "u_alice", "--db", db, "--json"])
    assert "c_alice_0001" in [item["content_id"] for item in json.loads(r.output)["results"]]  # 축약 인덱스
    r = runner.invoke(app, ["worker", "run", "--once", "--db", db])
    assert "처리한 잡 3" in r.output, r.output


def test_seed_load_analyze_strict_rejects_missing_snapshot(tmp_path: Path) -> None:
    record = json.loads(SEEDS.read_text(encoding="utf-8").splitlines()[0])
    record.pop("snapshot")
    path = tmp_path / "seeds.jsonl"
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    db = tmp_path / "j.db"
    r = runner.invoke(app, ["seed", "load", str(path), "--analyze", "--strict", "--db", str(db)])
    assert r.exit_code == 1
    assert "MISSING_SNAPSHOT" in r.output and "아무것도 적재하지 않았습니다" in r.output
    container = build_container(Settings(env="dev", mode="mock", data_dir=DATA, db_path=db))
    assert container.repo.count() == 0
