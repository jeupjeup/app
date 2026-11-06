"""CLI (설계서 5.8.8절). typer 기반.

    jupjup seed load data/golden/seeds.jsonl [--db PATH] [--replace-user] [--strict] [--analyze [--no-inline]]
    jupjup ingest submit --user u_alice --text "..." | --fixture html/x.html --platform news [--inline] [--json]
    jupjup ingest status <job_id> --user u_alice [--json]
    jupjup worker run [--concurrency 2] [--once | --max-jobs N]
    jupjup index rebuild [--user u_alice] [--db PATH]
    jupjup search "지난달 인스타에서 본 성수동 카페" --user u_alice [--now 2026-10-15T12:00+09:00] [--explain]
    jupjup api serve [--db var/jupjup.db --host 127.0.0.1 --port 8000]
    jupjup demo serve --db var/demo.db --port 8780
    jupjup embedding record --force
    jupjup eval validate
    jupjup eval validate-ingest [--golden-dir data/golden/ingest] [--legacy]      # v2 템플릿 검사·test 봉인
    jupjup eval run --mode mock --split test [--baseline ...] [--out reports/] [--update-baseline]
    jupjup eval ab --mode recorded --split dev --arms A0,A1 [--confirm-with test-ab.json] [--latency bench.json]
    jupjup rerank record [--force] [--device auto|mps|cpu]
    jupjup bench rerank --devices mps,cpu --max-lengths 256,384 --windows 12,20,32 --repeat 3
    jupjup bench search --device mps --repeat 3 [--out reports/bench_search_mps.json]
    jupjup models pull qwen2.5-3b-instruct-q4km [--cache-dir D]     # 네트워크를 쓰는 유일한 분석 모델 명령
    jupjup models doctor [--json] [--no-sha]
    jupjup eval ingest --mode recorded --profile local-qwen3-4b --split dev [--linkage mock|recorded]
    jupjup eval ingest --mode mock --golden v2 --split dev                     # mock 기본 골든은 v1
    jupjup eval ingest --mode live --profile P --split dev --confirm-run      # 녹화함 (골든 합성 원문만)
    jupjup analyze freeze --profile P                                        # frozen_config_sha256
    jupjup analyze record --profile P --split dev|test|all [--target ingest|seeds] [--append] \
        [--confirm-run] [--frozen-config SHA]
    jupjup analyze record-linkage --profile P --frozen-config SHA [--force]   # embed extra
    jupjup bench analyze --profile P --split dev --confirm-run [--out reports/bench_analyze.json]
    jupjup eval compare-profiles --candidate a.json --incumbent b.json --direction downgrade|upgrade \
        [--bench-candidate x.json --bench-incumbent y.json] [--n-boot 1000] [--seed 20261102] [--out d.json]

종료 코드: 0 성공/합격, 1 기준 미달·회귀·일부 실패, 2 설정·데이터 오류.
`api serve`는 검색 API이고, `demo serve`는 dev 전용 로컬 시연 앱이다.
"""

from __future__ import annotations

import ipaddress
import json
import sys
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NoReturn

import typer
from pydantic import ValidationError

from jupjup.config import REPO_ROOT, Settings
from jupjup.domain.errors import GoldenSetError, InvalidFilterError, JupjupError
from jupjup.text.lexicon import Lexicon

if TYPE_CHECKING:
    from jupjup.container import AppContainer
    from jupjup.eval.ingest_harness import IngestEvalConfig
    from jupjup.ingest.jobs import JobRecord
    from jupjup.search.types import SearchResult

app = typer.Typer(add_completion=False, no_args_is_help=True, help="줍줍저장소 검색 코어 CLI")
seed_app = typer.Typer(no_args_is_help=True, help="시드 적재")
index_app = typer.Typer(no_args_is_help=True, help="인덱스 관리")
eval_app = typer.Typer(no_args_is_help=True, help="평가 하네스")
demo_app = typer.Typer(no_args_is_help=True, help="dev 전용 로컬 웹 데모")
api_app = typer.Typer(no_args_is_help=True, help="검색 HTTP API")
embedding_app = typer.Typer(no_args_is_help=True, help="실제 임베딩 녹화")
rerank_app = typer.Typer(no_args_is_help=True, help="크로스 인코더 리랭커 녹화")
bench_app = typer.Typer(no_args_is_help=True, help="live 지연 벤치마크 (rerank extra 필요)")
ingest_app = typer.Typer(no_args_is_help=True, help="dev 인제스트 (저장 시점 분석 잡)")
worker_app = typer.Typer(no_args_is_help=True, help="인제스트 워커")
models_app = typer.Typer(no_args_is_help=True, help="로컬 분석 모델 (analyze-local extra)")
analyze_app = typer.Typer(no_args_is_help=True, help="로컬 분석기 녹화·동결 해시 (평가 전용)")
app.add_typer(seed_app, name="seed")
app.add_typer(index_app, name="index")
app.add_typer(eval_app, name="eval")
app.add_typer(demo_app, name="demo")
app.add_typer(api_app, name="api")
app.add_typer(embedding_app, name="embedding")
app.add_typer(rerank_app, name="rerank")
app.add_typer(bench_app, name="bench")
app.add_typer(ingest_app, name="ingest")
app.add_typer(worker_app, name="worker")
app.add_typer(models_app, name="models")
app.add_typer(analyze_app, name="analyze")
GOLDEN_DIR = REPO_ROOT / "data" / "golden"

DbOpt = Annotated[Path | None, typer.Option("--db", help="SQLite 경로 (기본: var/jupjup.db 또는 JUPJUP_DB_PATH)")]


def _container(db: Path | None) -> AppContainer:
    from jupjup.container import build_container

    settings = Settings() if db is None else Settings(db_path=db)
    return build_container(settings)


def _echo(msg: str = "") -> None:
    typer.echo(msg)


# ------------------------------------------------------------------------ api
@api_app.command("serve")
def api_serve(
    db: DbOpt = None,
    with_worker: Annotated[
        bool, typer.Option("--with-worker/--no-worker", help="API와 인제스트 워커 함께 실행")
    ] = True,
    host: Annotated[str, typer.Option("--host", help="바인드 주소")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8000,
    allow_external_bind: Annotated[
        bool,
        typer.Option("--allow-external-bind", help="app_session 인증으로 LAN 바인딩 허용"),
    ] = False,
    mode: Annotated[str | None, typer.Option("--mode", help="임베딩 모드: mock|recorded|live")] = None,
) -> None:
    import uvicorn

    from jupjup.api import create_app

    if mode is not None and mode not in {"mock", "recorded", "live"}:
        _echo("--mode는 mock|recorded|live")
        raise typer.Exit(2)
    updates: dict[str, object] = {"embedded_worker": with_worker}
    if db is not None:
        updates["db_path"] = db
    if mode is not None:
        updates["mode"] = mode
    settings = Settings.model_validate(updates)
    if not _is_loopback_host(host):
        if not allow_external_bind or settings.auth_backend != "app_session":
            _echo("외부 바인딩에는 --allow-external-bind와 JUPJUP_AUTH_BACKEND=app_session이 필요합니다.")
            raise typer.Exit(2)
        settings = settings.model_copy(update={"admin_api_enabled": False})
        _echo(f"LAN 앱 주소: http://<LAN-IP>:{port}/api (방화벽과 Wi-Fi 설정 확인)")
    application = create_app(settings)
    _echo(f"줍줍저장소 API: http://{host}:{port}")
    uvicorn.run(application, host=host, port=port)


# ---------------------------------------------------------------------- seed
@seed_app.command("load")
def seed_load(
    path: Annotated[
        Path,
        typer.Argument(help="seeds.jsonl 경로 (생략하면 data/golden/seeds.jsonl)"),
    ] = GOLDEN_DIR / "seeds.jsonl",
    db: DbOpt = None,
    replace_user: Annotated[
        bool, typer.Option("--replace-user", help="파일에 나온 사용자의 기존 저장물을 먼저 지운다")
    ] = False,
    strict: Annotated[bool, typer.Option("--strict", help="한 줄이라도 틀리면 아무것도 넣지 않는다")] = False,
    analyze: Annotated[
        bool, typer.Option("--analyze", help="스냅샷만 넣고 요약·태그는 인제스트 파이프라인으로 만든다")
    ] = False,
    inline: Annotated[
        bool, typer.Option("--inline/--no-inline", help="--analyze 잡을 바로 실행할지 (아니면 worker run에 맡김)")
    ] = True,
) -> None:
    from jupjup.storage.seed import load_seed_file

    if not path.exists():
        _echo(f"파일이 없습니다: {path}")
        raise typer.Exit(2)
    c = _container(db)
    if analyze:
        _seed_load_analyze(c, path, replace_user=replace_user, strict=strict, inline=inline)
        return
    rep = load_seed_file(path, c.repo, c.indexer, replace_user=replace_user, strict=strict)
    _echo(f"DB: {c.settings.db_path}")
    _echo(f"줄 {rep.total_lines} / 적재 {rep.loaded} / 인덱싱 {rep.indexed} / 임베딩 대기 {rep.embedding_pending}")
    _echo("사용자별: " + ", ".join(f"{u} {n}" for u, n in sorted(rep.users.items())))
    if rep.rolled_back:
        _echo("strict 모드: 오류가 있어 아무것도 적재하지 않았습니다")
    for e in rep.errors[:50]:
        _echo(f"  {e.line}행 [{e.code}] {e.id or '-'}: {e.message}")
    raise typer.Exit(1 if rep.errors else 0)


def _seed_load_analyze(c: AppContainer, path: Path, *, replace_user: bool, strict: bool, inline: bool) -> None:
    from jupjup.container import build_ingest_service
    from jupjup.ingest.seeding import load_seed_file_for_analysis

    service = build_ingest_service(c, worker_id="seed-analyze")
    rep = load_seed_file_for_analysis(path, service, c.indexer, replace_user=replace_user, strict=strict, inline=inline)
    _echo(f"DB: {c.settings.db_path}")
    statuses = ", ".join(f"{k} {v}" for k, v in sorted(rep.statuses.items())) or "-"
    _echo(f"줄 {rep.total_lines} / 적재 {rep.loaded} / 잡 {rep.queued} / 상태: {statuses}")
    _echo("사용자별: " + (", ".join(f"{u} {n}" for u, n in sorted(rep.users.items())) or "-"))
    if rep.rolled_back:
        _echo("오류가 있어 아무것도 적재하지 않았습니다")
    for e in rep.errors[:50]:
        _echo(f"  {e.line}행 [{e.code}] {e.id or '-'}: {e.message}")
    raise typer.Exit(0 if rep.all_succeeded else 1)


# --------------------------------------------------------------------- ingest
UserOpt = Annotated[str, typer.Option("--user", help="사용자 id (u_로 시작)")]


def _require_user(user: str) -> None:
    from jupjup.domain.models import USER_ID_RE

    if not USER_ID_RE.fullmatch(user):
        _echo(f"사용자 id 형식이 올바르지 않습니다: {user}")
        raise typer.Exit(2)


def _require_dev() -> None:
    environment = Settings().env
    if environment != "dev":
        _echo(f"인제스트 명령은 JUPJUP_ENV=dev에서만 쓸 수 있습니다 (현재 {environment})")
        raise typer.Exit(2)


def _job_payload(job: JobRecord) -> dict[str, Any]:
    from jupjup.api.dto import IngestJobResponse

    return IngestJobResponse.from_job(job).model_dump(mode="json")


@ingest_app.command("submit")
def ingest_submit(
    user: UserOpt,
    text: Annotated[str | None, typer.Option("--text", help="본문 직접 입력")] = None,
    fixture: Annotated[
        str | None, typer.Option("--fixture", help="fixture 루트 기준 상대 경로 (html, vtt, srt, json)")
    ] = None,
    ocr_text: Annotated[str | None, typer.Option("--ocr-text", help="이미지 OCR 텍스트 (kind=image)")] = None,
    url: Annotated[str | None, typer.Option("--url", help="--fixture와 함께 기록할 원본 URL")] = None,
    platform: Annotated[str | None, typer.Option("--platform", help="플랫폼 힌트 (news, youtube, ...)")] = None,
    title: Annotated[str | None, typer.Option("--title")] = None,
    note: Annotated[str | None, typer.Option("--note", help="사용자 메모")] = None,
    saved_at: Annotated[str | None, typer.Option("--saved-at", help="ISO 8601, 타임존 포함")] = None,
    inline: Annotated[bool, typer.Option("--inline", help="워커 없이 바로 실행")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    db: DbOpt = None,
) -> None:
    from jupjup.api.dto import IngestBody
    from jupjup.container import build_ingest_service

    _require_user(user)
    chosen = [name for name, value in (("--text", text), ("--fixture", fixture), ("--ocr-text", ocr_text)) if value]
    if len(chosen) != 1:
        _echo("--text, --fixture, --ocr-text 중 하나만 주세요")
        raise typer.Exit(2)
    source: dict[str, object] = (
        {"kind": "text", "text": text}
        if text
        else {"kind": "url", "fixture": fixture, "url": url}
        if fixture
        else {"kind": "image", "ocr_text": ocr_text}
    )
    if url and not fixture:
        _echo("--url은 --fixture와 함께만 쓸 수 있습니다")
        raise typer.Exit(2)
    try:
        body = IngestBody.model_validate(
            {
                "source": {k: v for k, v in source.items() if v is not None},
                "platform_hint": platform,
                "title": title,
                "user_note": note,
                "saved_at": _parse_datetime_option(saved_at, "--saved-at"),
            }
        )
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", ()))
        _echo(f"입력 오류: {loc}: {first['msg']}")
        raise typer.Exit(2) from exc
    except InvalidFilterError as exc:  # --saved-at 형식 오류
        _echo(f"입력 오류: {exc.message}")
        raise typer.Exit(2) from exc
    _require_dev()
    c = _container(db)
    service = build_ingest_service(c, worker_id="cli-inline")
    try:
        submitted = service.submit(user, body.to_request(service.worker.clock()))
        job = service.run_inline(submitted.job_id) if inline else service.status(user, submitted.job_id)
    except JupjupError as exc:
        _echo(f"인제스트 실패 [{exc.code}]: {exc.message}")
        raise typer.Exit(2) from exc
    payload = _job_payload(job)
    if as_json:
        _echo(json.dumps(payload, ensure_ascii=False))
    else:
        _echo(f"content_id {payload['content_id']} / job_id {payload['job_id']} / 상태 {payload['status']}")
        if payload["last_error"]:
            _echo(f"  오류: {payload['last_error']}")
    raise typer.Exit(1 if job.status in ("failed", "needs_review") else 0)


@ingest_app.command("status")
def ingest_status(
    job_id: Annotated[str, typer.Argument(help="job_...")],
    user: UserOpt,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    db: DbOpt = None,
) -> None:
    from jupjup.container import build_ingest_service
    from jupjup.domain.errors import NotFoundError

    _require_user(user)
    _require_dev()
    c = _container(db)
    service = build_ingest_service(c)
    try:
        job = service.status(user, job_id)
    except NotFoundError as exc:
        _echo(f"잡을 찾을 수 없습니다: {job_id}")
        raise typer.Exit(1) from exc
    payload = _job_payload(job)
    if as_json:
        _echo(json.dumps(payload, ensure_ascii=False))
        return
    _echo(
        f"{payload['job_id']} / content {payload['content_id']} / {payload['status']} @ {payload['stage']}"
        f" / 시도 {payload['attempts']}"
    )
    if payload["last_error"]:
        _echo(f"  오류: {payload['last_error']}")


@worker_app.command("run")
def worker_run(
    concurrency: Annotated[int | None, typer.Option("--concurrency", min=1, max=16)] = None,
    once: Annotated[bool, typer.Option("--once", help="대기 중인 잡을 모두 처리하면 끝낸다")] = False,
    max_jobs: Annotated[int | None, typer.Option("--max-jobs", min=1, help="이만큼 처리하면 끝낸다")] = None,
    db: DbOpt = None,
) -> None:
    """dev 인제스트 워커. 기본은 Ctrl+C까지 계속 돈다."""
    import signal
    import threading

    from jupjup.container import build_content_analyzer, build_ingest_service, warm_up_content_analyzer
    from jupjup.domain.errors import AnalyzerUnavailableError

    _require_dev()
    c = _container(db)
    try:
        # 로컬 분석기면 시작 때 모델 로드·sha256 검증·문법 컴파일을 미리 한다 (설계 6.3·6.8절).
        analyzer, chunk_settings = build_content_analyzer(c.settings, c.lexicon, c.morph_tokenizer)
        analyzer = warm_up_content_analyzer(analyzer, c.settings)
    except AnalyzerUnavailableError as exc:
        model_id = exc.details.get("model_id") or "<model_id>"
        reason = exc.details.get("reason", "unknown")
        _echo(
            f"로컬 분석기를 쓸 수 없습니다 ({reason}, analyzer.required=true): "
            f"uv sync --extra analyze-local && uv run jupjup models pull {model_id}"
        )
        raise typer.Exit(2) from exc
    except (JupjupError, ValueError) as exc:
        _echo(f"분석기 조립 실패: {exc}")
        raise typer.Exit(2) from exc
    service = build_ingest_service(c, concurrency=concurrency, analyzer=analyzer, chunk_settings=chunk_settings)
    worker = service.worker
    _echo(f"인제스트 워커 {worker.worker_id} 시작 (동시성 {worker.concurrency}, DB {c.settings.db_path})")
    if once or max_jobs is not None:
        processed = 0
        while max_jobs is None or processed < max_jobs:
            if not worker.run_once():
                break
            processed += 1
        _echo(f"처리한 잡 {processed}")
        return
    stop = threading.Event()

    def _stop(*_: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    worker.run_forever(stop)
    _echo("워커를 멈췄습니다")


# ---------------------------------------------------------------------- index
@index_app.command("rebuild")
def index_rebuild(
    user: Annotated[str | None, typer.Option("--user", help="이 사용자만 재구축")] = None,
    db: DbOpt = None,
) -> None:
    c = _container(db)
    stats = c.indexer.reindex_all(user)
    _echo(
        f"사용자 {stats.users} / 문서 {stats.documents} / 새 임베딩 {stats.embedded} / 재사용 {stats.reused}"
        f" / 임베딩 대기 {stats.embedding_pending}"
    )


# ----------------------------------------------------------------------- demo
@demo_app.command("serve")
def demo_serve(
    db: Annotated[Path, typer.Option("--db", help="데모 SQLite 경로")] = REPO_ROOT / "var" / "demo.db",
    host: Annotated[str, typer.Option("--host", help="바인드 주소")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8780,
    allow_external_bind: Annotated[
        bool,
        typer.Option("--allow-external-bind", help="위험: 인증 없는 dev 데모를 외부 주소에 바인딩"),
    ] = False,
    mode: Annotated[str, typer.Option("--mode", help="임베딩 모드: mock|recorded|live")] = "mock",
) -> None:
    import uvicorn

    from jupjup.demo import create_demo_app

    if not _is_loopback_host(host) and not allow_external_bind:
        _echo("외부 바인딩은 기본으로 거부됩니다. 위험을 인지했다면 --allow-external-bind를 명시하세요.")
        raise typer.Exit(2)
    if mode not in {"mock", "recorded", "live"}:
        _echo("--mode는 mock|recorded|live")
        raise typer.Exit(2)
    settings = Settings(db_path=db, mode=mode)
    if settings.env not in {"dev", "test"}:
        _echo("데모는 dev/test 환경에서만 사용할 수 있습니다")
        raise typer.Exit(2)
    try:
        demo = create_demo_app(settings)
    except ValueError as exc:
        _echo(str(exc))
        raise typer.Exit(2) from exc
    if not _is_loopback_host(host):
        _echo("경고: 인증 없는 dev 데모를 외부 주소에 바인딩합니다.")
    if demo.state.container.repo.count() == 0:
        _echo(f"주의: {db}에 저장물이 없습니다. 먼저 `jupjup seed load --db {db}`를 실행하세요.")
    _echo(f"줍줍저장소 데모: http://{host}:{port}")
    uvicorn.run(demo, host=host, port=port)


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# --------------------------------------------------------------- embedding
@embedding_app.command("record")
def embedding_record(
    seeds: Annotated[Path, typer.Option("--seeds")] = GOLDEN_DIR / "seeds.jsonl",
    queries: Annotated[Path, typer.Option("--queries")] = GOLDEN_DIR / "queries.jsonl",
    lexicon_cases: Annotated[Path, typer.Option("--lexicon-cases")] = GOLDEN_DIR / "lexicon_cases.jsonl",
    challenge: Annotated[Path, typer.Option("--challenge")] = GOLDEN_DIR / "challenge_queries.jsonl",
    probes: Annotated[Path, typer.Option("--probes")] = GOLDEN_DIR / "recorded_probes.jsonl",
    output: Annotated[Path, typer.Option("--output")] = REPO_ROOT / "data" / "recordings" / "embeddings.bge-m3.jsonl",
    cache_dir: Annotated[Path, typer.Option("--cache-dir")] = REPO_ROOT / "var" / "models",
    device: Annotated[str, typer.Option("--device", help="auto|cpu|mps")] = "auto",
    batch_size: Annotated[int, typer.Option("--batch-size", min=1)] = 16,
    force: Annotated[bool, typer.Option("--force", help="기존 녹화본을 성공 시 교체")] = False,
) -> None:
    """모든 시드 문서/청크와 골든·challenge 질의의 실제 검색 텍스트를 녹화한다."""
    from jupjup.container import build_container
    from jupjup.eval.schema import load_and_validate
    from jupjup.search.service import SearchRequest
    from jupjup.storage.db import create_db_engine
    from jupjup.storage.seed import load_seed_file

    if device not in {"auto", "cpu", "mps"}:
        _echo("--device는 auto|cpu|mps")
        raise typer.Exit(2)
    if output.exists() and not force:
        _echo(f"녹화본이 이미 있습니다: {output} (--force로 교체)")
        raise typer.Exit(2)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with suppress(FileNotFoundError):
        temporary.unlink()
    try:
        gs = load_and_validate(seeds, queries, lexicon_cases, challenge)
        probe_rows: list[tuple[str, str, datetime]] = []
        for line_number, line in enumerate(probes.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            try:
                probe_rows.append((str(row["user_id"]), str(row["query"]), datetime.fromisoformat(row["now"])))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"probe {line_number}행이 올바르지 않습니다") from exc
        settings = Settings(
            env="test",
            mode="live",
            db_path=Path(":memory:"),
            embedding_recording_path=temporary,
            bge_cache_dir=cache_dir,
            bge_device=device,
            bge_batch_size=batch_size,
        )
        c = build_container(settings, engine=create_db_engine(None))
        loaded = load_seed_file(seeds, c.repo, c.indexer, strict=True)
        if loaded.errors or loaded.rolled_back or loaded.embedding_pending:
            details = [error.message for error in loaded.errors[:5]]
            raise JupjupError(
                "시드 임베딩 녹화에 실패했습니다",
                {"errors": details, "embedding_pending": loaded.embedding_pending},
            )
        query_texts: list[str] = []
        seen: set[str] = set()
        for query in gs.queries:
            parsed = c.search.parse_only(query.query, query.now, query.user_id)
            if parsed.semantic_query and parsed.semantic_query not in seen:
                seen.add(parsed.semantic_query)
                query_texts.append(parsed.semantic_query)
        for user_id, probe_query, now in probe_rows:
            parsed = c.search.parse_only(probe_query, now, user_id)
            if parsed.semantic_query and parsed.semantic_query not in seen:
                seen.add(parsed.semantic_query)
                query_texts.append(parsed.semantic_query)
        c.embedder.embed(query_texts, "query")
        # 완화 정책은 원 해석에서 플랫폼/유형 등을 제거한 파생 semantic_query로 재검색할 수 있다.
        # 전체 검색을 한 번 순회해 recorded 재생이 소비할 모든 파생 키도 함께 녹화한다.
        for query in gs.queries:
            c.search.search(
                SearchRequest(
                    user_id=query.user_id,
                    query=query.query,
                    filters=query.request_filters,
                    limit=10,
                    now=query.now,
                )
            )
        for user_id, probe_query, now in probe_rows:
            c.search.search(SearchRequest(user_id=user_id, query=probe_query, limit=10, now=now))
        temporary.replace(output)
    except (GoldenSetError, JupjupError, ValueError) as exc:
        with suppress(FileNotFoundError):
            temporary.unlink()
        _echo(f"녹화 실패: {exc}")
        raise typer.Exit(2) from exc
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line]
    query_rows = sum(row.get("kind") == "query" for row in rows)
    _echo(
        f"bge-m3 녹화 완료: {output} ({output.stat().st_size / (1024 * 1024):.2f} MiB, "
        f"전체 {len(rows)}벡터, 질의 {query_rows}벡터)"
    )


# ---------------------------------------------------------------------- search
def _parse_datetime_option(s: str | None, option: str) -> datetime | None:
    if s is None:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise InvalidFilterError(
            f"{option}은 ISO 8601 시각이어야 합니다 (2026-10-15T12:00+09:00 형식).",
            {"field": option.removeprefix("--")},
        ) from exc
    if dt.tzinfo is None:
        raise InvalidFilterError(
            f"{option}에는 시간대가 있어야 합니다 (예: 2026-10-15T12:00+09:00).",
            {"field": option.removeprefix("--")},
        )
    return dt


@app.command("search")
def search_cmd(
    query: Annotated[str, typer.Argument(help="자연어 질의")],
    user: Annotated[str, typer.Option("--user", help="사용자 id (예: u_alice)")],
    now: Annotated[str | None, typer.Option("--now", help="기준 시각 ISO 8601. 없으면 현재 시각")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=50)] = 10,
    explain: Annotated[bool, typer.Option("--explain", help="검색기별 순위와 점수 표시")] = False,
    platform: Annotated[list[str] | None, typer.Option("--platform", help="요청 필터: 플랫폼 (여러 번 가능)")] = None,
    ctype: Annotated[list[str] | None, typer.Option("--type", help="요청 필터: 콘텐츠 유형 (여러 번 가능)")] = None,
    saved_from: Annotated[str | None, typer.Option("--from", help="요청 필터: 저장 시각 하한 (포함)")] = None,
    saved_to: Annotated[str | None, typer.Option("--to", help="요청 필터: 저장 시각 상한 (제외)")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="SearchResult를 JSON으로 출력")] = False,
    db: DbOpt = None,
) -> None:
    from jupjup.search.filters import SearchFilters
    from jupjup.search.service import SearchRequest

    c = _container(db)
    if c.repo.count(user) == 0:
        _echo(f"{user}의 저장물이 DB({c.settings.db_path})에 없습니다. 먼저 `jupjup seed load`를 실행하세요.")
    else:
        c.indexer.reindex_all(user)  # SQLite(정본)에서 메모리 인덱스를 만든다. 저장된 벡터를 재사용한다
    try:
        filters = None
        if platform or ctype or saved_from or saved_to:
            try:
                filters = SearchFilters.model_validate(
                    {
                        "platforms": platform or None,
                        "content_types": ctype or None,
                        "saved_from": _parse_datetime_option(saved_from, "--from"),
                        "saved_to": _parse_datetime_option(saved_to, "--to"),
                    }
                )
            except ValidationError as exc:
                raise InvalidFilterError("필터 값이 올바르지 않아요.", {"field": "filters"}) from exc
        res = c.search.search(
            SearchRequest(
                user_id=user,
                query=query,
                filters=filters,
                limit=limit,
                now=_parse_datetime_option(now, "--now"),
                explain=explain,
            )
        )
    except JupjupError as exc:
        _echo(f"[{exc.code}] {exc.message}")
        raise typer.Exit(2) from exc
    if as_json:
        _echo(res.model_dump_json(indent=2))
        return
    _print_result(res, c, explain, now)


def _print_result(res: SearchResult, c: AppContainer, explain: bool, now: str | None) -> None:
    p = res.understanding
    lx = c.lexicon
    _echo(f"질의: {res.query}")
    _echo(f"기준 시각: {now or '(현재 시각)'}")
    _echo("")
    _echo("[질의 해석]")
    _echo(f"  의도      : {p.intent}")
    if p.time_range:
        tr, tw = p.time_range, p.time_window
        _echo(
            f"  기간      : '{tr.expression}' → {tr.start:%Y-%m-%d} ~ {tr.end:%Y-%m-%d} (끝 제외)"
            f"{' [근사]' if tr.fuzzy else ''}"
        )
        if tw:
            _echo(f"  필터 창   : {tw.start:%Y-%m-%d} ~ {tw.end:%Y-%m-%d} (granularity={tr.granularity})")
    else:
        _echo("  기간      : 없음")
    plats = ", ".join(f"{lx.platform_label(h.value)}({h.strength})" for h in p.platforms) or "없음"
    types = ", ".join(f"{lx.content_type_label(h.value)}({h.strength})" for h in p.content_types) or "없음"
    _echo(f"  플랫폼    : {plats}")
    _echo(f"  유형      : {types}")
    _echo(f"  키워드    : {', '.join(p.keywords) or '없음'}")
    if p.purpose_terms:
        _echo(f"  목적      : {', '.join(p.purpose_terms)}")
    if p.corrections:
        _echo("  교정      : " + ", ".join(f"{x.from_}→{x.to}({x.kind})" for x in p.corrections))
    _echo(f"  의미 질의 : {p.semantic_query or '(없음)'}")
    if p.warnings:
        _echo(f"  경고      : {', '.join(p.warnings)}")
    if res.overridden_by_request:
        _echo(f"  요청 필터가 대체: {', '.join(res.overridden_by_request)}")
    _echo("")
    flag = " [degraded: " + ",".join(res.degraded_reasons) + "]" if res.degraded else ""
    _echo(f"[결과 {len(res.results)}건, {res.timing_ms.get('total', 0):.1f}ms]{flag}")
    if not res.results and res.empty_state:
        _echo(f"  {res.empty_state.message}")
        for s in res.empty_state.suggestions:
            _echo(f"   - {s.label}")
    for r in res.results:
        deleted = " (원본 삭제됨)" if not r.original_available else ""
        _echo(
            f"{r.rank:>3}. [{lx.platform_label(r.platform)}/{lx.content_type_label(r.content_type)}] {r.title}{deleted}"
        )
        _echo(f"     {r.content_id} | 저장 {r.saved_at:%Y-%m-%d} | score {r.score:.4f}")
        if r.summary:
            _echo(f"     {r.summary}")
        if r.representative_tags:
            _echo(f"     태그: {', '.join(r.representative_tags)}")
        reasons = []
        for m in r.match_reasons:
            reasons.append(f"{m.type}:{','.join(m.terms) if m.terms else (m.detail or '')}")
        if reasons:
            _echo(f"     근거: {'; '.join(reasons)}")
        if explain and r.debug:
            _echo(f"     ranks={r.debug['ranks']} rrf={r.debug['rrf']}")


# ---------------------------------------------------------------------- eval
_G = GOLDEN_DIR


@eval_app.command("validate")
def eval_validate(
    seeds: Annotated[Path, typer.Option("--seeds")] = _G / "seeds.jsonl",
    queries: Annotated[Path, typer.Option("--queries")] = _G / "queries.jsonl",
    lexicon: Annotated[Path, typer.Option("--lexicon")] = _G / "lexicon_cases.jsonl",
    challenge: Annotated[Path, typer.Option("--challenge")] = _G / "challenge_queries.jsonl",
    review_metadata: Annotated[Path, typer.Option("--review-metadata")] = _G / "review_metadata.json",
    ingest_sources: Annotated[Path, typer.Option("--ingest-sources")] = _G / "ingest" / "sources.jsonl",
    ingest_annotations: Annotated[Path, typer.Option("--ingest-annotations")] = _G / "ingest" / "annotations.jsonl",
) -> None:
    from collections import Counter

    from jupjup.eval.harness import load_review_metadata
    from jupjup.eval.ingest_harness import load_ingest_golden, validate_ingest_golden
    from jupjup.eval.schema import load_golden, validate_golden

    gs, errors = load_golden(seeds, queries, lexicon, challenge)
    errors += validate_golden(gs)
    ingest_golden, ingest_errors = load_ingest_golden(ingest_sources, ingest_annotations)
    ingest_errors += validate_ingest_golden(
        ingest_golden,
        fixtures_root=ingest_sources.parent / "fixtures",
    )
    errors += [f"ingest: {error}" for error in ingest_errors]
    statuses = Counter(q.review_status for q in gs.queries)
    try:
        metadata = load_review_metadata(review_metadata)
    except (OSError, ValueError) as exc:
        errors.append(f"review_metadata 검증 실패: {exc}")
        metadata = None
    if metadata is not None and metadata.reviewed_query_count_total != statuses["human_reviewed"]:
        errors.append(
            "review_metadata.reviewed_query_count_total이 human_reviewed 질의 수와 다릅니다: "
            f"{metadata.reviewed_query_count_total} != {statuses['human_reviewed']}"
        )
    if metadata is not None:
        for split in ("dev", "test"):
            actual = sum(q.review_status == "human_reviewed" and q.split == split for q in gs.queries)
            recorded = metadata.reviewed_query_count_by_split.get(split)
            if recorded != actual:
                errors.append(
                    f"review_metadata.reviewed_query_count_by_split.{split}가 실제 수와 다릅니다: "
                    f"{recorded} != {actual}"
                )
    if errors:
        _echo(f"골든셋 검증 실패 ({len(errors)}건)")
        for e in errors[:100]:
            _echo(f"  - {e}")
        raise typer.Exit(1)
    cats = Counter(c for q in gs.queries for c in q.categories)
    splits = Counter(q.split for q in gs.queries)
    _echo(
        f"골든셋 검증 통과 (review_status 분리): seeds {len(gs.seeds)}, queries {len(gs.queries)} "
        f"(dev {splits['dev']}, test {splits['test']}), lexicon_cases {len(gs.lexicon_cases)}"
    )
    _echo("카테고리: " + ", ".join(f"{k} {v}" for k, v in sorted(cats.items())))
    _echo("review_status: " + ", ".join(f"{k} {v}" for k, v in sorted(statuses.items())))
    ingest_splits = Counter(annotation.split for annotation in ingest_golden.annotations)
    ingest_groups = Counter(source.platform_group for source in ingest_golden.sources)
    _echo(
        f"인제스트 골든셋: sources {len(ingest_golden.sources)}, annotations {len(ingest_golden.annotations)} "
        f"(dev {ingest_splits['dev']}, test {ingest_splits['test']})"
    )
    _echo("인제스트 플랫폼군: " + ", ".join(f"{key} {value}" for key, value in sorted(ingest_groups.items())))
    if metadata is not None:
        _echo(
            "review_metadata: "
            f"reviewed {metadata.reviewed_query_count_total}, reviewers {metadata.reviewer_count}, "
            f"weighted_kappa {metadata.weighted_kappa_overall}"
        )


@eval_app.command("validate-ingest")
def eval_validate_ingest(
    golden_dir: Annotated[Path, typer.Option("--golden-dir", help="골든 디렉터리 (기본 v2: data/golden/ingest)")] = _G
    / "ingest",
    legacy: Annotated[
        bool, typer.Option("--legacy", help="v1 템플릿 골든: 구조 검사만 한다 (템플릿 검사·test 봉인 생략)")
    ] = False,
) -> None:
    """인제스트 골든 구조 검사 + 템플릿 검사(설계 8.1절 a~d) + test 봉인(test.sha256) 확인. 실패하면 종료 1."""
    from collections import Counter

    from jupjup.eval.ingest_golden_checks import (
        MAX_NGRAM_OVERLAP,
        check_ingest_templates,
        check_test_seal,
        difficult_case_counts,
    )
    from jupjup.eval.ingest_harness import load_ingest_golden, validate_ingest_golden

    golden, errors = load_ingest_golden(golden_dir / "sources.jsonl", golden_dir / "annotations.jsonl")
    errors += validate_ingest_golden(golden, fixtures_root=golden_dir / "fixtures")
    warnings: list[str] = []
    template = None
    if not legacy and not errors:
        template = check_ingest_templates(golden, golden_dir / "fixtures")
        errors += template.errors
        warnings += template.warnings
        errors += check_test_seal(golden, golden_dir, required=True)
    splits = Counter(annotation.split for annotation in golden.annotations)
    groups = Counter(source.platform_group for source in golden.sources)
    statuses = Counter(annotation.review_status for annotation in golden.annotations)
    _echo(
        f"인제스트 골든 {golden_dir.name}: sources {len(golden.sources)}, annotations {len(golden.annotations)} "
        f"(dev {splits['dev']}, test {splits['test']})"
    )
    _echo("플랫폼군: " + ", ".join(f"{key} {value}" for key, value in sorted(groups.items())))
    _echo("어려운 사례: " + ", ".join(f"{key} {value}" for key, value in sorted(difficult_case_counts(golden).items())))
    _echo("review_status: " + ", ".join(f"{key} {value}" for key, value in sorted(statuses.items())))
    if legacy:
        _echo("--legacy: 템플릿 검사와 test 봉인 확인을 생략했습니다 (v1 mock 배선 회귀용)")
    elif template is not None:
        overlaps = ", ".join(f"{group} {value[0]:.3f}" for group, value in sorted(template.max_overlap.items()))
        _echo(f"플랫폼군별 최대 8-gram 중복률 (상한 {MAX_NGRAM_OVERLAP}): {overlaps}")
    for warning in warnings[:30]:
        _echo(f"  경고: {warning}")
    if errors:
        _echo(f"인제스트 골든 검증 실패 ({len(errors)}건)")
        for error in errors[:100]:
            _echo(f"  - {error}")
        raise typer.Exit(1)
    _echo("인제스트 골든 검증 통과" + ("" if legacy else " (템플릿 검사·test 봉인 포함)"))


@eval_app.command("run")
def eval_run(
    mode: Annotated[str, typer.Option("--mode")] = "mock",
    split: Annotated[str, typer.Option("--split")] = "test",
    baseline: Annotated[Path | None, typer.Option("--baseline")] = None,
    out: Annotated[Path, typer.Option("--out")] = REPO_ROOT / "reports",
    update_baseline_flag: Annotated[bool, typer.Option("--update-baseline")] = False,
    overrides: Annotated[str | None, typer.Option("--overrides", help="SearchSettings 덮어쓰기 JSON")] = None,
) -> None:
    from jupjup.eval.harness import EvalConfig, EvalHarness, update_baseline
    from jupjup.eval.report import write_report

    if mode not in ("mock", "recorded", "live") or split not in ("dev", "test", "all"):
        _echo("--mode는 mock|recorded|live, --split은 dev|test|all")
        raise typer.Exit(2)
    try:
        cfg = EvalConfig.model_validate(
            {
                "mode": mode,
                "split": split,
                "baseline_path": baseline,
                "search_overrides": json.loads(overrides) if overrides else {},
            }
        )
        report = EvalHarness(cfg).run()
    except GoldenSetError as exc:
        _echo(f"골든셋 오류: {exc.message}")
        for e in exc.details.get("errors", [])[:50]:
            _echo(f"  - {e}")
        raise typer.Exit(2) from exc
    except (JupjupError, ValueError) as exc:
        _echo(f"설정 오류: {exc}")
        raise typer.Exit(2) from exc
    jp, mp = write_report(report, out)
    g = report.gate
    _echo(
        f"평가 mode={mode} split={split} — {'PASS' if g.passed else 'FAIL'}  "
        "(기술 게이트: ai_draft_unreviewed; 제품 PASS 근거 분리)"
    )
    _echo(f"{'지표':<26}{'값':>10}  기준")
    for c in g.checks + g.regression:
        v = "-" if c.value is None else f"{c.value:.4f}"
        _echo(f"{c.name:<26}{v:>10}  {c.op} {c.threshold:g}  {'OK' if c.passed else 'FAIL'}")
    _echo(f"p95 지연: {report.perf.get('latency_p95_ms', 0):.1f}ms (비결정적)")
    _echo(f"리포트: {jp}\n        {mp}")
    if update_baseline_flag:
        target = baseline or (REPO_ROOT / "data" / "baselines" / f"{mode}.json")
        ok, msg = update_baseline(target, report, note="골든셋 v1 초안(사용자 검수 전) 기준")
        _echo(msg)
        if not ok:
            raise typer.Exit(1)
    raise typer.Exit(0 if g.passed else 1)


ConfirmRunOpt = Annotated[
    bool,
    typer.Option(
        "--confirm-run",
        "--confirm-cost",
        help="live 로컬 모델 실행 확인 (예상 시간·비용 0 USD를 본 뒤). --confirm-cost는 같은 뜻의 별칭",
    ),
]
FrozenOpt = Annotated[
    str | None,
    typer.Option("--frozen-config", help="설정 동결 해시 (test·all split 필수, `jupjup analyze freeze`로 확인)"),
]
AnalyzerProfilesOpt = Annotated[Path | None, typer.Option("--profiles", help="analyzer_profiles.yaml 경로")]
LlmRecordingsOpt = Annotated[
    Path | None, typer.Option("--recordings-dir", help="분석기 녹화 디렉터리 (기본 data/recordings/llm)")
]


def _ingest_config(profiles_path: Path | None, recordings_dir: Path | None, **values: Any) -> IngestEvalConfig:
    """경로 옵션은 주어졌을 때만 기본값을 덮는다."""
    from jupjup.eval.ingest_harness import IngestEvalConfig

    if profiles_path is not None:
        values["profiles_path"] = profiles_path
    if recordings_dir is not None:
        values["recordings_dir"] = recordings_dir
    return IngestEvalConfig(**values)


def _print_misses(report: Any) -> None:
    misses = report.misses or []
    _echo(f"녹화 미스 {len(misses)}건 (원문 없이 해시만 표시):")
    for miss in misses[:50]:
        _echo(
            f"  - {miss.source_id}: {miss.kind} schema={miss.schema_name or '-'} max_tokens={miss.max_tokens or '-'} "
            f"request_hash={(miss.request_hash or '-')[:16]}"
        )
    if len(misses) > 50:
        _echo(f"  … 외 {len(misses) - 50}건 (리포트 misses 참고)")


@eval_app.command("ingest")
def eval_ingest(
    mode: Annotated[str, typer.Option("--mode")] = "mock",
    profile: Annotated[str, typer.Option("--profile")] = "mock",
    split: Annotated[str, typer.Option("--split")] = "test",
    judge: Annotated[str | None, typer.Option("--judge")] = None,
    baseline: Annotated[Path | None, typer.Option("--baseline")] = None,
    out: Annotated[Path, typer.Option("--out")] = REPO_ROOT / "reports",
    confirm_run: ConfirmRunOpt = False,
    frozen_config: FrozenOpt = None,
    linkage: Annotated[
        str, typer.Option("--linkage", help="검색 연결 지표: none|mock(HashingEmbedder)|recorded(bge-m3 녹화)")
    ] = "none",
    linkage_split: Annotated[
        str, typer.Option("--linkage-split", help="검색 연결 질의 분할: dev|test|all")
    ] = "all",
    profiles_path: AnalyzerProfilesOpt = None,
    recordings_dir: LlmRecordingsOpt = None,
    golden: Annotated[
        str | None,
        typer.Option("--golden", help="v1(템플릿, mock 배선 회귀) | v2(자연문). 생략: mock은 v1, recorded/live는 v2"),
    ] = None,
    judge_calibration: Annotated[
        Path | None,
        typer.Option("--judge-calibration", help="판정기 보정 파일 (기본 <골든>/judge_calibration.<judge>.json)"),
    ] = None,
) -> None:
    """인제스트 분석 품질/배선 평가. mock은 고정 응답, recorded는 분석 녹화 재생, live는 로컬 모델(녹화함).

    종료 코드: 0 합격, 1 기준 미달, 2 설정·데이터 오류 또는 녹화 미스.
    """
    from jupjup.eval.ingest_harness import (
        INGEST_GOLDEN_DIRS,
        INGEST_MOCK_BASELINES,
        IngestEvalHarness,
        default_golden_version,
    )
    from jupjup.eval.ingest_report import write_ingest_report

    if mode not in ("mock", "recorded", "live") or split not in ("dev", "test", "all"):
        _echo("--mode는 mock|recorded|live, --split은 dev|test|all")
        raise typer.Exit(2)
    if linkage not in ("none", "mock", "recorded"):
        _echo("--linkage는 none|mock|recorded")
        raise typer.Exit(2)
    if linkage_split not in ("dev", "test", "all"):
        _echo("--linkage-split은 dev|test|all")
        raise typer.Exit(2)
    version = golden or default_golden_version(mode)
    if version not in INGEST_GOLDEN_DIRS:
        _echo("--golden은 v1|v2")
        raise typer.Exit(2)
    golden_dir = INGEST_GOLDEN_DIRS[version]
    try:
        config = _ingest_config(
            profiles_path,
            recordings_dir,
            mode=mode,
            profile=profile,
            split=split,
            sources_path=golden_dir / "sources.jsonl",
            annotations_path=golden_dir / "annotations.jsonl",
            judge_profile=judge,
            baseline_path=(
                baseline if baseline is not None else (INGEST_MOCK_BASELINES[version] if mode == "mock" else None)
            ),
            confirm_cost=confirm_run,
            frozen_config=frozen_config,
            # 녹화는 평가·녹화 명령에서만 켠다. live 평가 출력은 골든(합성 원문)이라 녹화한다 (설계 6.9절).
            record=mode == "live",
            linkage=linkage,
            linkage_split=linkage_split,
            judge_calibration_path=judge_calibration,
        )
        harness = IngestEvalHarness(config)
        if mode == "live" and not confirm_run:
            estimate = harness.estimate_run()
            _echo(f"live 분석기 평가 {estimate.items}건. {estimate.describe()}")
            judge_estimate = harness.estimate_judge_run()
            if judge_estimate is not None:
                _echo(f"live 판정기 최소 {judge_estimate.items}회. {judge_estimate.describe()}")
            _echo("실제 호출은 하지 않았습니다. 실행하려면 --confirm-run을 주세요.")
            raise typer.Exit(2)
        report = harness.run()
        json_path, markdown_path = write_ingest_report(report, out)
    except typer.Exit:
        raise
    except ValidationError as exc:
        first = exc.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first["loc"])
        _echo(f"인제스트 평가 오류: {location}: {first['msg']}")
        raise typer.Exit(2) from exc
    except (JupjupError, OSError, ValueError) as exc:
        _echo(f"인제스트 평가 오류: {str(exc).splitlines()[0]}")
        raise typer.Exit(2) from exc
    _echo(f"인제스트 평가 mode={mode} split={split} — {'PASS' if report.gate.passed else 'FAIL'}")
    _echo(f"골든 {version} ({golden_dir.relative_to(REPO_ROOT).as_posix()})")
    if report.runtime is not None:
        _echo(
            f"프로필 {report.runtime.profile}, recording_model_id {report.runtime.recording_model_id}, "
            f"frozen_config_sha256 {report.runtime.frozen_config_sha256[:16]}…"
        )
    for check in [*report.gate.checks, *report.gate.regression]:
        value = "해당 없음" if check.value is None else f"{check.value:.4f}"
        _echo(f"{check.name:<34}{value:>10}  {check.op} {check.threshold:g}  {'OK' if check.passed else 'FAIL'}")
    _echo(f"리포트: {json_path}\n        {markdown_path}")
    if report.misses:
        _print_misses(report)
        raise typer.Exit(2)
    raise typer.Exit(0 if report.gate.passed else 1)


@eval_app.command("compare-profiles")
def eval_compare_profiles(
    candidate: Annotated[Path, typer.Option("--candidate", help="후보 프로필 eval ingest 리포트 JSON")],
    incumbent: Annotated[Path, typer.Option("--incumbent", help="현행 프로필 eval ingest 리포트 JSON")],
    direction: Annotated[str, typer.Option("--direction", help="downgrade(더 작은 모델) | upgrade(더 큰 모델)")],
    bench_candidate: Annotated[
        Path | None, typer.Option("--bench-candidate", help="후보 bench analyze JSON (지연·메모리 판단)")
    ] = None,
    bench_incumbent: Annotated[Path | None, typer.Option("--bench-incumbent", help="현행 bench analyze JSON")] = None,
    n_boot: Annotated[int, typer.Option("--n-boot", min=1)] = 1000,
    seed: Annotated[int, typer.Option("--seed")] = 20261102,
    out: Annotated[Path | None, typer.Option("--out", help="SwapDecision JSON 경로 (같은 이름 .md도 쓴다)")] = None,
) -> None:
    """두 인제스트 리포트로 프로필 교체 판정 (설계 8.6절). 모델을 부르지 않는다.

    종료 코드: 0 교체 후보, 1 교체 불가, 2 비교 거부(split·골든셋·판정기 불일치) 또는 입력 오류.
    """
    from jupjup.eval.ingest_compare import (
        BenchPair,
        compare_profiles,
        load_bench,
        load_report,
        render_swap_markdown,
    )

    if direction not in ("downgrade", "upgrade"):
        _echo("--direction은 downgrade|upgrade")
        raise typer.Exit(2)
    if (bench_candidate is None) != (bench_incumbent is None):
        _echo("--bench-candidate와 --bench-incumbent는 함께 주세요")
        raise typer.Exit(2)
    if out is not None and out.suffix != ".json":
        _echo("--out은 .json 경로여야 합니다 (같은 이름의 .md도 생성합니다)")
        raise typer.Exit(2)
    try:
        bench = None
        if bench_candidate is not None and bench_incumbent is not None:
            bench = BenchPair(candidate=load_bench(bench_candidate), incumbent=load_bench(bench_incumbent))
        decision = compare_profiles(
            load_report(candidate),
            load_report(incumbent),
            direction="downgrade" if direction == "downgrade" else "upgrade",
            bench=bench,
            n_boot=n_boot,
            seed=seed,
        )
    except ValidationError as exc:
        first = exc.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first["loc"])
        _echo(f"비교 입력 오류: {location}: {first['msg']}")
        raise typer.Exit(2) from exc
    except OSError as exc:
        _echo(f"비교 입력 오류: {str(exc).splitlines()[0]}")
        raise typer.Exit(2) from exc
    except ValueError as exc:
        _echo(f"비교 거부: {str(exc).splitlines()[0]}")
        raise typer.Exit(2) from exc
    markdown = render_swap_markdown(decision)
    _echo(markdown.rstrip("\n"))
    if out is not None:
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(decision.model_dump_json(indent=2) + "\n", encoding="utf-8")
            out.with_suffix(".md").write_text(markdown, encoding="utf-8")
        except OSError as exc:
            _echo(f"판정 출력 오류: {str(exc).splitlines()[0]}")
            raise typer.Exit(2) from exc
        _echo(f"판정: {out}\n      {out.with_suffix('.md')}")
    raise typer.Exit(0 if decision.eligible else 1)


@eval_app.command("judge-sample")
def eval_judge_sample(
    candidates: Annotated[str, typer.Option("--candidates", help="후보 분석기 프로필 (쉼표 구분)")],
    out: Annotated[Path, typer.Option("--out")] = REPO_ROOT / "data" / "golden" / "ingest" / "judge_labels.dev.jsonl",
    mode: Annotated[str, typer.Option("--mode", help="recorded(기본) | mock(배선 확인용)")] = "recorded",
    n_sentences: Annotated[int, typer.Option("--sentences", min=1)] = 100,
    n_keyfacts: Annotated[int, typer.Option("--keyfacts", min=1)] = 60,
    seed: Annotated[int, typer.Option("--seed")] = 20261102,
    force: Annotated[bool, typer.Option("--force", help="라벨이 이미 있는 파일도 덮어쓴다")] = False,
    profiles_path: AnalyzerProfilesOpt = None,
    recordings_dir: LlmRecordingsOpt = None,
) -> None:
    """판정기 보정용 빈 라벨 파일. dev 요약 문장·핵심 사실 쌍을 후보 출력에서 고르게(seed 고정) 뽑는다.

    종료 코드: 0 작성, 2 설정·데이터 오류 또는 녹화 미스.
    """
    from jupjup.eval.ingest_runtime import DEFAULT_LLM_RECORDINGS_DIR, DEFAULT_PROFILES_PATH
    from jupjup.eval.judge_calibration import MIN_KEYFACTS, MIN_SENTENCES, dump_label_rows, labels_written
    from jupjup.eval.judge_tools import JudgeToolMiss, judge_sample

    if mode not in ("mock", "recorded"):
        _echo("--mode는 recorded|mock")
        raise typer.Exit(2)
    names = [name.strip() for name in candidates.split(",") if name.strip()]
    try:
        if labels_written(out) and not force:
            _echo(f"{out}에 이미 사람 라벨이 있습니다. 덮어쓰려면 --force를 주세요")
            raise typer.Exit(2)
        rows = judge_sample(
            names,
            mode="mock" if mode == "mock" else "recorded",
            n_sentences=n_sentences,
            n_keyfacts=n_keyfacts,
            seed=seed,
            profiles_path=profiles_path or DEFAULT_PROFILES_PATH,
            recordings_dir=recordings_dir or DEFAULT_LLM_RECORDINGS_DIR,
        )
    except typer.Exit:
        raise
    except JudgeToolMiss as exc:
        _echo(f"판정기 표집 오류: {exc}")
        _print_misses(exc)
        raise typer.Exit(2) from exc
    except (JupjupError, OSError, ValueError) as exc:
        _echo(f"판정기 표집 오류: {str(exc).splitlines()[0]}")
        raise typer.Exit(2) from exc
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dump_label_rows(rows), encoding="utf-8")
    sentences = sum(row.kind == "sentence" for row in rows)
    keyfacts = len(rows) - sentences
    _echo(f"라벨 파일: {out} (문장 {sentences}개, 핵심 사실 쌍 {keyfacts}개, 후보 {', '.join(names)}, seed {seed})")
    if mode == "mock":
        _echo("주의: mock 출력은 골든 사실을 그대로 쓴 고정 응답이라 보정 라벨로 쓰지 않습니다 (배선 확인용)")
    if sentences < MIN_SENTENCES or keyfacts < MIN_KEYFACTS:
        _echo(f"주의: 보정 최소 표본(문장 {MIN_SENTENCES}, 핵심 사실 {MIN_KEYFACTS})보다 적습니다")
    _echo("각 행의 label에 문장은 supported|partially|unsupported, 핵심 사실은 covered|partial|missing을 적고")
    _echo('annotator에 "human"(사람) 또는 다른 값(준-사람 라벨)을 적은 뒤 jupjup eval judge-calibrate를 돌리세요.')
    raise typer.Exit(0)


@eval_app.command("judge-calibrate")
def eval_judge_calibrate(
    judge: Annotated[str, typer.Option("--judge")] = "judge-kanana-8b",
    labels: Annotated[Path, typer.Option("--labels")] = REPO_ROOT
    / "data"
    / "golden"
    / "ingest"
    / "judge_labels.dev.jsonl",
    mode: Annotated[str, typer.Option("--mode", help="recorded(기본) | live(녹화함, --confirm-run 필요)")] = "recorded",
    out: Annotated[Path | None, typer.Option("--out", help="기본 <골든>/judge_calibration.<judge>.json")] = None,
    confirm_run: ConfirmRunOpt = False,
    profiles_path: AnalyzerProfilesOpt = None,
    recordings_dir: LlmRecordingsOpt = None,
) -> None:
    """판정기 κ 보정. Cohen's κ(3분류)와 이진 κ를 내고, 이진 κ ≥ 0.7이면 통과한다 (8.3절, Q-LA10).

    종료 코드: 0 두 과제 모두 통과, 1 미달, 2 설정·데이터 오류 또는 녹화 미스.
    """
    from jupjup.eval.ingest_harness import INGEST_GOLDEN
    from jupjup.eval.ingest_runtime import DEFAULT_LLM_RECORDINGS_DIR, DEFAULT_PROFILES_PATH, default_live_llm_factory
    from jupjup.eval.judge_calibration import default_calibration_path
    from jupjup.eval.judge_tools import JudgeToolMiss, estimate_calibration_run, judge_calibrate

    if mode not in ("recorded", "live"):
        _echo("--mode는 recorded|live")
        raise typer.Exit(2)
    if mode == "live" and not confirm_run:
        try:
            estimate = estimate_calibration_run(
                labels,
                judge,
                profiles_path=profiles_path or DEFAULT_PROFILES_PATH,
                recordings_dir=recordings_dir or DEFAULT_LLM_RECORDINGS_DIR,
            )
        except (OSError, ValueError) as exc:
            _echo(f"판정기 보정 오류: {str(exc).splitlines()[0]}")
            raise typer.Exit(2) from exc
        _echo(f"live 판정기 보정 {estimate.items}회. {estimate.describe()}")
        _echo("실행하려면 --confirm-run을 주세요 (호출하지 않았습니다)")
        raise typer.Exit(2)
    try:
        factory = None
        if mode == "live":
            settings = Settings()
            factory = default_live_llm_factory(settings.analyzer_cache_dir, settings.analyzer.n_gpu_layers)
        calibration = judge_calibrate(
            labels,
            judge,
            mode="live" if mode == "live" else "recorded",
            profiles_path=profiles_path or DEFAULT_PROFILES_PATH,
            recordings_dir=recordings_dir or DEFAULT_LLM_RECORDINGS_DIR,
            live_llm_factory=factory,
            record=mode == "live",
        )
    except JudgeToolMiss as exc:
        _echo(f"판정기 보정 오류: {exc}")
        _print_misses(exc)
        raise typer.Exit(2) from exc
    except (JupjupError, OSError, ValueError) as exc:
        _echo(f"판정기 보정 오류: {str(exc).splitlines()[0]}")
        raise typer.Exit(2) from exc
    target = out or default_calibration_path(INGEST_GOLDEN, judge)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(calibration.model_dump_json(indent=2) + "\n", encoding="utf-8")
    _echo(f"판정기 {calibration.judge_profile} ({calibration.recording_model_id})")
    for stats in (calibration.faithfulness, calibration.keyfact):
        kappa3 = "정의 안 됨" if stats.kappa_3class is None else f"{stats.kappa_3class:.4f}"
        kappa2 = "정의 안 됨" if stats.kappa_binary is None else f"{stats.kappa_binary:.4f}"
        _echo(
            f"{stats.task:<13} 비교 {stats.compared}/{stats.labeled} (미표기 {stats.unlabeled}, judge_failed "
            f"{stats.judge_failed})  κ3 {kappa3}  이진 κ({stats.binary_positive} 대 나머지) {kappa2}  "
            f"{'PASS' if stats.passed else 'FAIL'}"
        )
        for reason in stats.reasons:
            _echo(f"  - {reason}")
    if not calibration.human_labels:
        _echo("주의: 사람 판정이 아닌 라벨이 있습니다 (Q-LA3 준-사람 라벨). PRD 의미의 보정으로 주장하지 않습니다")
    _echo(f"보정 파일: {target}")
    passed = calibration.faithfulness.passed and calibration.keyfact.passed
    raise typer.Exit(0 if passed else 1)


@eval_app.command("ab")
def eval_ab(
    mode: Annotated[str, typer.Option("--mode")] = "recorded",
    split: Annotated[str, typer.Option("--split")] = "dev",
    arms: Annotated[str, typer.Option("--arms", help="A0(끔), A1(리랭커 켬)")] = "A0,A1",
    out: Annotated[Path, typer.Option("--out")] = REPO_ROOT / "reports" / "ab_reranker.json",
    latency: Annotated[Path | None, typer.Option("--latency", help="bench search 결과 JSON")] = None,
    confirm_with: Annotated[
        Path | None, typer.Option("--confirm-with", help="같은 팔로 실행한 test split A/B JSON")
    ] = None,
    overrides: Annotated[str | None, typer.Option("--overrides", help="모든 팔에 공통인 SearchSettings JSON")] = None,
    iterations: Annotated[int, typer.Option("--iterations", min=1)] = 1000,
) -> None:
    """켬/끔 A/B 실행과 단계 1 채택 판정 (설계 8, 10.1절)."""
    from jupjup.eval.ab import (
        ABComparison,
        ABConfig,
        ArmConfig,
        LatencyReport,
        decide_reranker,
        reranker_test_confirmed,
        run_ab,
    )

    known = {"A0": False, "A1": True}
    names = [name.strip() for name in arms.split(",") if name.strip()]
    if mode not in ("mock", "recorded", "live") or split not in ("dev", "test") or not set(names) <= set(known):
        _echo("--mode는 mock|recorded|live, --split은 dev|test, --arms는 A0,A1 중에서 고른다")
        raise typer.Exit(2)
    common = json.loads(overrides) if overrides else {}
    try:
        config = ABConfig(
            mode=mode,
            split=split,
            arms=[ArmConfig(name=name, cross_rerank=known[name], search_overrides=common) for name in names],
            bootstrap_iterations=iterations,
            baseline_arm=names[0],
        )
        report = run_ab(config)
    except (JupjupError, ValueError) as exc:
        _echo(f"A/B 실행 실패: {exc}")
        raise typer.Exit(2) from exc
    bench = LatencyReport.model_validate_json(latency.read_text(encoding="utf-8")) if latency else None
    confirmations: dict[tuple[str, str], bool] = {}
    if confirm_with is not None:
        try:
            confirmation_data = json.loads(confirm_with.read_text(encoding="utf-8"))
            if confirmation_data.get("config", {}).get("split") != "test":
                raise ValueError("--confirm-with는 test split A/B 리포트여야 합니다")
            if confirmation_data.get("config", {}).get("mode") != mode:
                raise ValueError("--confirm-with의 mode가 현재 실행과 다릅니다")
            for raw in confirmation_data.get("comparisons", []):
                comparison = ABComparison.model_validate(raw)
                confirmations[(comparison.baseline, comparison.candidate)] = reranker_test_confirmed(comparison)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            _echo(f"test 확인 리포트 오류: {exc}")
            raise typer.Exit(2) from exc
    for comparison in report.comparisons:
        comparison.decision = decide_reranker(
            comparison,
            bench,
            test_confirmed=confirmations.get((comparison.baseline, comparison.candidate)),
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.deterministic_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for comparison in report.comparisons:
        _echo(f"{comparison.baseline} → {comparison.candidate}  rerank_status={comparison.rerank_status}")
        for delta in comparison.deltas:
            _echo(
                f"  {delta.metric:<12}{delta.delta:+.4f}  95%CI [{delta.ci_low:+.4f}, {delta.ci_high:+.4f}]  "
                f"W/L/T {delta.wins}/{delta.losses}/{delta.ties}  p={delta.sign_test_p:.3f}"
            )
        assert comparison.decision is not None
        for rule in comparison.decision.rules:
            _echo(f"  [{'OK' if rule.passed else 'FAIL'}] {rule.name}: {rule.detail}")
        _echo(f"  판정: {comparison.decision.verdict}")
    _echo(f"리포트: {out}")


# -------------------------------------------------------------------- rerank
@rerank_app.command("record")
def rerank_record(
    output: Annotated[Path, typer.Option("--output")] = REPO_ROOT
    / "data"
    / "recordings"
    / "rerank.bge-reranker-v2-m3.jsonl",
    cache_dir: Annotated[Path | None, typer.Option("--cache-dir")] = None,
    device: Annotated[str, typer.Option("--device", help="auto|cpu|mps")] = "auto",
    force: Annotated[bool, typer.Option("--force", help="기존 녹화본을 버리고 새로 만든다")] = False,
    overrides: Annotated[str | None, typer.Option("--overrides", help="SearchSettings 덮어쓰기 JSON")] = None,
) -> None:
    """골든·challenge·probe 질의의 넓은 창(R_base 상위 50 + 계획별 5)을 녹화한다. 원문은 저장하지 않는다."""
    from jupjup.eval.rerank_tools import record_rerank

    if device not in {"auto", "cpu", "mps"}:
        _echo("--device는 auto|cpu|mps")
        raise typer.Exit(2)
    try:
        stats = record_rerank(
            output=output,
            cache_dir=cache_dir or Settings().rerank_cache_dir,
            device=device,
            force=force,
            overrides=json.loads(overrides) if overrides else None,
        )
    except (GoldenSetError, JupjupError, ValueError) as exc:
        _echo(f"녹화 실패: {exc}")
        raise typer.Exit(2) from exc
    _echo(json.dumps(stats, ensure_ascii=False))


# --------------------------------------------------------------------- bench
def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@bench_app.command("rerank")
def bench_rerank_cmd(
    devices: Annotated[str, typer.Option("--devices")] = "mps,cpu",
    max_lengths: Annotated[str, typer.Option("--max-lengths")] = "256,384",
    windows: Annotated[str, typer.Option("--windows")] = "12,20,32",
    repeat: Annotated[int, typer.Option("--repeat", min=1)] = 3,
    cache_dir: Annotated[Path | None, typer.Option("--cache-dir")] = None,
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """T31: 리랭크 단계 단독 지연 (dev 질의의 실제 창 구성)."""
    from jupjup.eval.rerank_tools import bench_rerank

    result = bench_rerank(
        cache_dir=cache_dir or Settings().rerank_cache_dir,
        devices=_csv(devices),
        max_lengths=[int(item) for item in _csv(max_lengths)],
        windows=[int(item) for item in _csv(windows)],
        repeat=repeat,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    _echo(text)


@bench_app.command("search")
def bench_search_cmd(
    device: Annotated[str, typer.Option("--device", help="auto|cpu|mps")] = "auto",
    repeat: Annotated[int, typer.Option("--repeat", min=1)] = 3,
    cache_dir: Annotated[Path | None, typer.Option("--cache-dir")] = None,
    out: Annotated[Path | None, typer.Option("--out")] = None,
    overrides: Annotated[str | None, typer.Option("--overrides", help="SearchSettings 덮어쓰기 JSON")] = None,
) -> None:
    """T36: live 검색 전체 지연 A0 대 A1 (bge-m3 + bge-reranker-v2-m3)."""
    from jupjup.eval.rerank_tools import bench_search

    settings = Settings()
    report = bench_search(
        cache_dir=cache_dir or settings.rerank_cache_dir,
        embedding_cache_dir=cache_dir or settings.bge_cache_dir,
        device=device,
        repeat=repeat,
        overrides=json.loads(overrides) if overrides else None,
        scratch_dir=REPO_ROOT / "var" / "bench",
    )
    text = report.model_dump_json(indent=2)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    _echo(text)


@bench_app.command("analyze")
def bench_analyze_cmd(
    profile: Annotated[str, typer.Option("--profile")],
    split: Annotated[str, typer.Option("--split")] = "dev",
    confirm_run: ConfirmRunOpt = False,
    frozen_config: FrozenOpt = None,
    profiles_path: AnalyzerProfilesOpt = None,
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """로컬 분석기 live 지연 벤치 (single·map_reduce p50/p95, 피크 RSS, 출력 토큰/초). 녹화하지 않는다."""
    from jupjup.eval.ingest_bench import bench_from_run, peak_rss_mb
    from jupjup.eval.ingest_harness import IngestEvalHarness

    if split not in ("dev", "test", "all"):
        _echo("--split은 dev|test|all")
        raise typer.Exit(2)
    try:
        config = _ingest_config(
            profiles_path,
            None,
            mode="live",
            profile=profile,
            split=split,
            baseline_path=None,
            confirm_cost=confirm_run,
            frozen_config=frozen_config,
            record=False,
        )
        harness = IngestEvalHarness(config)
        if not confirm_run:
            estimate = harness.estimate_run()
            _echo(f"벤치 {estimate.items}건. {estimate.describe()}")
            _echo("실제 호출은 하지 않았습니다. 실행하려면 --confirm-run을 주세요.")
            raise typer.Exit(2)
        report = harness.run()
        if harness.last_capture is None:
            raise ValueError("분석기 수집 결과가 없습니다")
        bench = bench_from_run(report, harness.last_capture, rss_mb=peak_rss_mb())
    except typer.Exit:
        raise
    except (JupjupError, OSError, ValueError, ValidationError) as exc:
        _echo(f"벤치 오류: {str(exc).splitlines()[0]}")
        raise typer.Exit(2) from exc
    text = bench.model_dump_json(indent=2)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    _echo(text)
    raise typer.Exit(0 if bench.within_budget else 1)


# -------------------------------------------------------------------- analyze
ProfileArg = Annotated[str, typer.Option("--profile", help="analyzer_profiles.yaml의 local 프로필")]


def _analyze_error(exc: Exception) -> NoReturn:
    _echo(f"분석기 명령 오류: {str(exc).splitlines()[0]}")
    raise typer.Exit(2) from exc


@analyze_app.command("freeze")
def analyze_freeze(
    profile: ProfileArg,
    profiles_path: AnalyzerProfilesOpt = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """현재 프로필·프롬프트·디코딩 정책·모델 sha256의 결합 해시(frozen_config_sha256)를 출력한다 (설계 8.2절)."""
    from jupjup.eval.ingest_runtime import (
        DEFAULT_LLM_RECORDINGS_DIR,
        DEFAULT_PROFILES_PATH,
        frozen_config_components,
        prepare_local_setup,
    )

    try:
        setup = prepare_local_setup(profiles_path or DEFAULT_PROFILES_PATH, profile, DEFAULT_LLM_RECORDINGS_DIR)
        components = frozen_config_components(setup.profiles, setup.profile, setup.prompts)
    except (JupjupError, ValueError) as exc:
        _analyze_error(exc)
    if as_json:
        _echo(json.dumps({"frozen_config_sha256": setup.frozen_sha256, **components}, ensure_ascii=False, indent=2))
        return
    _echo(f"frozen_config_sha256 {setup.frozen_sha256}")
    _echo(f"recording_model_id {setup.model_id}")
    for name, digest in components["prompts"].items():
        _echo(f"  prompt {name} {digest[:16]}…")


@analyze_app.command("record")
def analyze_record(
    profile: ProfileArg,
    split: Annotated[str, typer.Option("--split", help="dev|test|all (target=ingest)")] = "dev",
    target: Annotated[str, typer.Option("--target", help="ingest(인제스트 골든) | seeds(검색 시드 200건)")] = "ingest",
    append: Annotated[bool, typer.Option("--append", help="기존 녹화 파일에 이어 붙인다 (같은 요청은 건너뜀)")] = False,
    confirm_run: ConfirmRunOpt = False,
    frozen_config: FrozenOpt = None,
    profiles_path: AnalyzerProfilesOpt = None,
    recordings_dir: LlmRecordingsOpt = None,
    out: Annotated[Path, typer.Option("--out")] = REPO_ROOT / "reports",
) -> None:
    """골든 원문(또는 시드)을 live 로컬 모델로 분석하며 RecordingLLM으로 녹화한다 (설계 7.3절).

    원문 프롬프트는 녹화하지 않는다. 같은 요청은 다시 쓰지 않는다. test·all·seeds는 --frozen-config가 필요하다.
    """
    from jupjup.eval.ingest_harness import IngestEvalHarness
    from jupjup.eval.ingest_linkage import GOLDEN as SEARCH_GOLDEN
    from jupjup.eval.ingest_linkage import run_linkage
    from jupjup.eval.ingest_report import write_ingest_report
    from jupjup.eval.ingest_runtime import build_eval_analyzer, check_frozen_config, estimate_run

    if split not in ("dev", "test", "all") or target not in ("ingest", "seeds"):
        _echo("--split은 dev|test|all, --target은 ingest|seeds")
        raise typer.Exit(2)
    try:
        config = _ingest_config(
            profiles_path,
            recordings_dir,
            mode="live",
            profile=profile,
            split=split,
            baseline_path=None,
            confirm_cost=confirm_run,
            frozen_config=frozen_config,
            record=True,
        )
        harness = IngestEvalHarness(config)
        setup = harness.local_setup()
        # 시드는 split이 없고 연결 지표는 동결 뒤 한 번만 녹화한다 (7.4절). ingest는 test·all만 동결을 요구한다.
        check_frozen_config("all" if target == "seeds" else split, frozen_config, setup.frozen_sha256)
        if target == "seeds":
            seeds_path = SEARCH_GOLDEN / "seeds.jsonl"
            count = sum(1 for line in seeds_path.read_text(encoding="utf-8").splitlines() if line.strip())
            estimate = estimate_run(setup.spec, count)
        else:
            estimate = harness.estimate_run()
        _echo(f"녹화 대상 {target} {estimate.items}건 → {', '.join(p.name for p in setup.recording_paths())}")
        _echo(estimate.describe())
        if not confirm_run:
            _echo("실제 호출은 하지 않았습니다. 실행하려면 --confirm-run을 주세요.")
            raise typer.Exit(2)
        existing = [path.name for path in setup.recording_paths() if path.exists()]
        if existing and not append:
            _echo(f"녹화 파일이 이미 있습니다: {', '.join(existing)} (이어 붙이려면 --append)")
            raise typer.Exit(2)
        if target == "seeds":
            lexicon = Lexicon.load(Settings().lexicon_dir)
            build_eval_analyzer(
                setup, mode="live", lexicon=lexicon, live_llm_factory=harness.live_factory(), record=True
            )
            assert setup.analyzer is not None
            linkage = run_linkage(setup.analyzer, setup.chunk_settings, embedder="mock")
            _echo(f"시드 분석 상태: {linkage.seed_statuses}")
            _echo(f"mock 연결 지표: {json.dumps(linkage.report_metrics(), ensure_ascii=False)}")
            return
        report = harness.run()
        json_path, markdown_path = write_ingest_report(report, out)
    except typer.Exit:
        raise
    except (JupjupError, OSError, ValueError, ValidationError) as exc:
        _analyze_error(exc)
    succeeded = sum(item.job_status == "succeeded" for item in report.items)
    _echo(
        f"녹화 완료: {succeeded}/{len(report.items)}건 성공, 게이트 {'PASS' if report.gate.passed else 'FAIL'} (참고)"
    )
    _echo(f"리포트: {json_path}\n        {markdown_path}")


@analyze_app.command("record-linkage")
def analyze_record_linkage(
    profile: ProfileArg,
    frozen_config: FrozenOpt = None,
    force: Annotated[bool, typer.Option("--force", help="기존 연결 녹화를 성공 시 교체")] = False,
    profiles_path: AnalyzerProfilesOpt = None,
    recordings_dir: LlmRecordingsOpt = None,
) -> None:
    """recorded 시드 분석 출력으로 만든 문서·청크 텍스트를 live bge-m3로 녹화한다 (embed extra, 설계 7.4절 2번)."""
    from jupjup.eval.ingest_linkage import linkage_recording_file, record_linkage
    from jupjup.eval.ingest_runtime import (
        DEFAULT_LLM_RECORDINGS_DIR,
        DEFAULT_PROFILES_PATH,
        build_eval_analyzer,
        check_frozen_config,
        prepare_local_setup,
    )

    try:
        setup = prepare_local_setup(
            profiles_path or DEFAULT_PROFILES_PATH, profile, recordings_dir or DEFAULT_LLM_RECORDINGS_DIR
        )
        check_frozen_config("all", frozen_config, setup.frozen_sha256)
        lexicon = Lexicon.load(Settings().lexicon_dir)
        build_eval_analyzer(setup, mode="recorded", lexicon=lexicon, live_llm_factory=None, record=False)
        assert setup.analyzer is not None
        stats = record_linkage(setup.analyzer, setup.chunk_settings, linkage_recording_file(profile), force=force)
    except (JupjupError, OSError, ValueError, ValidationError) as exc:
        _analyze_error(exc)
    _echo(json.dumps(stats, ensure_ascii=False))


ModelsCacheOpt = Annotated[
    Path | None, typer.Option("--cache-dir", help="모델 캐시 (기본: JUPJUP_ANALYZER_CACHE_DIR 또는 var/models)")
]
ProfilesOpt = Annotated[Path | None, typer.Option("--profiles", help="analyzer_profiles.yaml 경로")]


@models_app.command("pull")
def models_pull(
    model_id: Annotated[str, typer.Argument(help="analyzer_profiles.yaml의 models 키")],
    cache_dir: ModelsCacheOpt = None,
    profiles_path: ProfilesOpt = None,
) -> None:
    """고정 revision의 GGUF를 받고 sha256을 검증한다. 다르면 파일을 지우고 실패한다."""
    from jupjup.ingest.profiles import AnalyzerProfiles
    from jupjup.providers.local_models import pull_model

    settings = Settings()
    try:
        profiles = AnalyzerProfiles.load(profiles_path or settings.analyzer.profiles_path)
    except ValueError as exc:
        _echo(f"오류: {exc}")
        raise typer.Exit(2) from exc
    spec = profiles.models.get(model_id)
    if spec is None:
        _echo(f"오류: 없는 모델입니다: {model_id} (가능: {', '.join(sorted(profiles.models))})")
        raise typer.Exit(2)
    root = cache_dir or settings.analyzer_cache_dir
    try:
        paths = pull_model(spec, root)
    except JupjupError as exc:
        _echo(f"오류: {exc.message}")
        raise typer.Exit(2) from exc
    for path in paths:
        _echo(f"OK {path} (sha256 검증)")


@models_app.command("doctor")
def models_doctor(
    cache_dir: ModelsCacheOpt = None,
    profiles_path: ProfilesOpt = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    no_sha: Annotated[bool, typer.Option("--no-sha", help="sha256 계산을 건너뛴다 (큰 파일)")] = False,
) -> None:
    """extra, 모델 파일, sha256, Metal 여부, 프로필 참조 무결성을 점검한다. 현재 설정으로 못 쓰면 종료 1."""
    from jupjup.providers.local_models import doctor_report

    settings = Settings()
    report = doctor_report(
        profiles_path or settings.analyzer.profiles_path,
        cache_dir or settings.analyzer_cache_dir,
        active_engine=settings.analyzer.engine,
        active_profile=settings.analyzer.profile,
        verify_sha=not no_sha,
    )
    if as_json:
        _echo(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_doctor(report)
    raise typer.Exit(0 if report["usable"] else 1)


def _print_doctor(report: dict[str, Any]) -> None:
    rt = report["runtime"]
    if rt.get("installed"):
        _echo(
            f"런타임: llama-cpp-python {rt['llama_cpp_python']}, Metal={rt['gpu_offload']}, "
            f"machine={rt['machine']}, wheel={','.join(rt['wheel_tags']) or '?'}"
        )
    else:
        _echo(f"런타임: llama-cpp-python 없음 (uv sync --extra analyze-local), machine={rt['machine']}")
    _echo(f"캐시: {report['cache_dir']}")
    if not report["profiles_ok"]:
        _echo(f"프로필: 오류 {report['profiles_error']}")
    else:
        _echo(f"프로필: OK (default_profile={report['default_profile']})")
        _echo("모델:")
        for row in report["models"]:
            state = (
                "없음"
                if not row["present"]
                else {True: "OK", False: "sha256 불일치", None: "있음(sha 미검사)"}[row["sha256_ok"]]
            )
            license_note = "" if row["license_commercial_ok"] else " [상업 불가]"
            _echo(f"  {row['model_id']:<34} {state:<14} {row['license']}{license_note} ({row['source']})")
        _echo("프로필:")
        for row in report["profiles"]:
            extra = f" {row.get('recording_model_id', '')}" if row["engine"] == "local" else ""
            policy = "" if row["policy_ok"] else f" 정책 오류: {row['policy_error']}"
            _echo(f"  {row['name']:<18} {row['engine']:<5}{extra}{policy}")
    for warning in report["warnings"]:
        _echo(f"경고: {warning}")
    active = report["active"]
    verdict = "사용 가능" if report["usable"] else "사용 불가"
    _echo(f"현재 설정: engine={active['engine']} profile={active['profile']} → {verdict}")


@app.command("migrate-db")
def db_migrate(db: Annotated[Path, typer.Option("--db")] = Path("var/jupjup.db")) -> None:
    """Back up and migrate an existing SQLite database to the current version."""
    from jupjup.storage.db import create_db_engine
    from jupjup.storage.migration_v29 import migration_status

    engine = create_db_engine(db)
    _echo(str(migration_status(engine)))
    engine.dispose()


def main() -> None:
    try:
        app()
    except GoldenSetError as exc:  # pragma: no cover - 방어
        typer.echo(f"골든셋 오류: {exc.message}", err=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
