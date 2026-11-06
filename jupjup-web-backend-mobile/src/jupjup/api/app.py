"""FastAPI application factory for the public search API."""

from __future__ import annotations

import logging
import re
import threading
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from jupjup.api.dto import (
    BulkFailure,
    BulkUpsertBody,
    BulkUpsertResponse,
    CorrectionResponse,
    ErrorEnvelope,
    FacetResponse,
    HealthResponse,
    IngestBody,
    IngestJobResponse,
    IngestSubmitResponse,
    ParseBody,
    ParseResponse,
    ResultItemResponse,
    SearchBody,
    SearchResponse,
    TimeRangeResponse,
    UnderstandingResponse,
)
from jupjup.api.errors import ApiError, Utf8JSONResponse, install_error_handlers
from jupjup.app_api.http import create_api
from jupjup.auth import CompositeAuthenticator, PrincipalDependency
from jupjup.config import Settings
from jupjup.container import AppContainer, analyzer_health, build_container, build_ingest_service
from jupjup.domain.errors import (
    ContentValidationError,
    IndexNotReadyError,
    InvalidFilterError,
    JupjupError,
    NotFoundError,
)
from jupjup.domain.models import ContentBundle, SeedRecord
from jupjup.ingest.analyzer import UnavailableAnalyzer
from jupjup.ingest.service import IngestService
from jupjup.query.understanding import ParsedQuery
from jupjup.search.filters import SearchFilters
from jupjup.search.service import SearchRequest
from jupjup.search.types import SearchResult

logger = logging.getLogger(__name__)

JOB_ID_RE = re.compile(r"^job_[0-9a-f]{32}$")

SEARCH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
    500: {"model": ErrorEnvelope},
    503: {"model": ErrorEnvelope},
}


def _understanding(parsed: ParsedQuery, overridden: list[str]) -> UnderstandingResponse:
    time_range = None
    if parsed.time_range is not None:
        time_range = TimeRangeResponse(
            expression=parsed.time_range.expression,
            start=parsed.time_range.start,
            end=parsed.time_range.end,
            field=parsed.time_range.field,
            fuzzy=parsed.time_range.fuzzy,
        )
    return UnderstandingResponse(
        intent=parsed.intent,
        keywords=parsed.keywords,
        semantic_query=parsed.semantic_query,
        purpose_terms=parsed.purpose_terms,
        time_range=time_range,
        platforms=[FacetResponse(value=hit.value, strength=hit.strength) for hit in parsed.platforms],
        content_types=[FacetResponse(value=hit.value, strength=hit.strength) for hit in parsed.content_types],
        corrections=[
            CorrectionResponse(from_=item.from_, to=item.to, kind=item.kind, confidence=item.confidence)
            for item in parsed.corrections
        ],
        overridden_by_request=overridden,
    )


def _search_response(result: SearchResult) -> SearchResponse:
    return SearchResponse(
        query_id=result.query_id,
        query=result.query,
        understanding=_understanding(result.understanding, result.overridden_by_request),
        results=[
            ResultItemResponse(
                content_id=item.content_id,
                rank=item.rank,
                score=item.score,
                title=item.title,
                platform=item.platform,
                content_type=item.content_type,
                summary=item.summary,
                representative_tags=item.representative_tags,
                saved_at=item.saved_at,
                source_url=item.source_url,
                original_available=item.original_available,
                relaxed=item.relaxed,
                match_reasons=item.match_reasons,
                debug=(
                    {key: item.debug[key] for key in ("ranks", "rrf", "features")} if item.debug is not None else None
                ),
            )
            for item in result.results
        ],
        applied_relaxations=result.applied_relaxations,
        empty_state=result.empty_state,
        degraded=result.degraded,
        timing_ms=result.timing_ms,
    )


def _search_filters(body: SearchBody) -> SearchFilters | None:
    if body.filters is None:
        return None
    try:
        return SearchFilters.model_validate(body.filters.model_dump())
    except ValidationError as exc:
        raise InvalidFilterError("필터 값이 올바르지 않아요.", {"field": "filters"}) from exc


def _json_model(
    model: SearchResponse
    | ParseResponse
    | BulkUpsertResponse
    | HealthResponse
    | IngestSubmitResponse
    | IngestJobResponse,
    *,
    status_code: int = 200,
) -> Utf8JSONResponse:
    return Utf8JSONResponse(content=jsonable_encoder(model, by_alias=True), status_code=status_code)


def _bulk_upsert(container: AppContainer, user_id: str, body: BulkUpsertBody) -> BulkUpsertResponse:
    valid: list[tuple[int, SeedRecord, ContentBundle]] = []
    failed: list[BulkFailure] = []
    ids = [item.get("id") for item in body.items if isinstance(item.get("id"), str)]
    duplicate_ids = {content_id for content_id in ids if ids.count(content_id) > 1}
    for index, item in enumerate(body.items):
        item_id = item.get("id") if isinstance(item.get("id"), str) else None
        if item_id in duplicate_ids:
            failed.append(
                BulkFailure(
                    index=index,
                    id=item_id,
                    code="DUPLICATE_CONTENT",
                    message="한 요청 안에서 content id는 중복될 수 없어요.",
                )
            )
            continue
        try:
            record = SeedRecord.model_validate(item)
            if record.user_id != user_id:
                raise ContentValidationError("user_id가 X-User-Id와 달라요.", {"id": record.id})
            valid.append((index, record, record.to_bundle()))
        except (ValidationError, ContentValidationError) as exc:
            message = exc.message if isinstance(exc, ContentValidationError) else "콘텐츠 형식이 올바르지 않아요."
            failed.append(BulkFailure(index=index, id=item_id, code="INVALID_CONTENT", message=message))

    if body.strict and failed:
        return BulkUpsertResponse(upserted=0, failed=failed, embedding_pending=0)

    upserted = 0
    embedding_pending = 0
    if body.strict:
        prepared_items = []
        for index, record, bundle in valid:
            try:
                prepared_items.append((index, record, container.indexer.prepare_bundle(bundle)))
            except JupjupError as exc:
                failed.append(BulkFailure(index=index, id=record.id, code=exc.code, message=exc.message))
        if failed:
            failed.sort(key=lambda item: item.index)
            return BulkUpsertResponse(upserted=0, failed=failed, embedding_pending=0)
        try:
            indexed_items = container.indexer.commit_prepared([staged for _, _, staged in prepared_items])
            for indexed in indexed_items:
                embedding_pending += int(indexed.embedding_pending)
                upserted += 1
        except JupjupError as exc:
            return BulkUpsertResponse(
                upserted=0,
                failed=[
                    BulkFailure(index=index, id=record.id, code=exc.code, message=exc.message)
                    for index, record, _ in prepared_items
                ],
                embedding_pending=0,
            )
        return BulkUpsertResponse(upserted=upserted, failed=failed, embedding_pending=embedding_pending)

    for index, record, bundle in valid:
        try:
            prepared_item = container.indexer.prepare_bundle(bundle)
            container.repo.upsert(bundle)
            indexed = container.indexer.apply_prepared(prepared_item)
        except JupjupError as exc:
            failed.append(BulkFailure(index=index, id=record.id, code=exc.code, message=exc.message))
            continue
        embedding_pending += int(indexed.embedding_pending)
        upserted += 1
    failed.sort(key=lambda item: item.index)
    return BulkUpsertResponse(upserted=upserted, failed=failed, embedding_pending=embedding_pending)


def _submit_only_ingest_service(container: AppContainer) -> IngestService:
    """API 프로세스는 잡을 넣고 조회만 한다 (분석은 워커 몫). 분석기 설정 문제로 검색 API까지 내려가지 않게,
    조립이 실패하면 경고 1회 뒤 ``UnavailableAnalyzer``를 자리 표시자로 쓴다 (T25e 검수 L2). mock 대체는 없다."""
    try:
        return build_ingest_service(container)
    except (JupjupError, ValueError) as exc:
        warnings.warn(
            f"분석기 조립에 실패해 API는 잡 등록·조회만 합니다 ({type(exc).__name__}). "
            "`uv run jupjup models doctor`로 확인하세요",
            RuntimeWarning,
            stacklevel=2,
        )
        profile = container.settings.analyzer.profile or "unknown"
        return build_ingest_service(container, analyzer=UnavailableAnalyzer(profile, "config_error"))


def create_app(
    settings: Settings | None = None,
    *,
    container: AppContainer | None = None,
    ingest: IngestService | None = None,
) -> FastAPI:
    """`ingest`는 테스트에서 시계를 주입할 때만 넘긴다. dev가 아니면 무시한다."""
    configuration = container.settings if container is not None else settings or Settings()
    if configuration.env == "prod" and configuration.auth_backend == "dev_header":
        raise ValueError("auth_backend=dev_header cannot be used in prod")
    active = container or build_container(configuration)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        stop = threading.Event()
        worker = None
        if configuration.embedded_worker:
            worker = threading.Thread(
                target=lambda: application.state.ingest.worker.run_forever(stop),
                name="api-ingest-worker",
                daemon=True,
            )
            worker.start()
        try:
            yield
        finally:
            stop.set()
            if worker is not None:
                worker.join(timeout=5)

    app = FastAPI(
        lifespan=lifespan,
        title="줍줍저장소 검색 API",
        version="1.0",
        default_response_class=Utf8JSONResponse,
    )
    app.state.container = active
    app.state.authenticator = CompositeAuthenticator(
        active.engine, allow_dev=configuration.env in {"dev", "test"} and configuration.auth_backend == "dev_header"
    )
    state_lock = threading.RLock()
    active.registry.ready = False
    try:
        active.indexer.reindex_all()
    except Exception:
        logger.exception("initial index rebuild failed")
    else:
        active.registry.ready = True
    install_error_handlers(app)

    def require_ready() -> None:
        if not active.registry.ready:
            raise IndexNotReadyError("검색 인덱스를 준비하고 있어요.")

    @app.post("/v1/search", response_model=SearchResponse, responses=SEARCH_ERROR_RESPONSES)
    def search(body: SearchBody, principal: PrincipalDependency) -> Response:
        user_id = principal.user_id
        require_ready()
        if body.now is not None and active.settings.env != "dev":
            raise ApiError(422, "VALIDATION_ERROR", "now는 dev 환경에서만 사용할 수 있어요.", {"field": "now"})
        try:
            request = SearchRequest(
                user_id=user_id,
                query=body.query,
                filters=_search_filters(body),
                limit=body.limit,
                now=body.now,
                explain=body.explain,
            )
        except ValidationError as exc:
            raise ApiError(422, "VALIDATION_ERROR", "요청 형식이 올바르지 않아요.") from exc
        with state_lock:
            # 별도 워커 프로세스나 CLI가 같은 DB에 쓴 결과를 반영한다(바뀌지 않았으면 요약 조회만 한다).
            active.indexer.refresh_if_stale(user_id)
            response = _search_response(active.search.search(request))
        payload: dict[str, Any] = response.model_dump(mode="json", by_alias=True)
        if not body.explain:
            for item in payload["results"]:
                item.pop("debug", None)
        return Utf8JSONResponse(content=payload)

    @app.post("/v1/query:parse", response_model=ParseResponse, responses=SEARCH_ERROR_RESPONSES)
    def parse_query(body: ParseBody, principal: PrincipalDependency) -> Response:
        user_id = principal.user_id
        require_ready()
        with state_lock:
            parsed = active.search.parse_only(body.query, active.search.clock(), user_id)
        return _json_model(ParseResponse(understanding=_understanding(parsed, [])))

    analyzer_state = analyzer_health(active.settings)  # 모델을 로드하지 않는 값싼 점검. mock 경로는 None

    @app.get("/healthz", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
    def health() -> Response:
        ready = active.registry.ready
        body = HealthResponse(
            status="ok" if ready else "starting",
            index_ready=ready,
            embedder=active.embedder.model_id,
            mode=active.settings.mode,
            analyzer=analyzer_state,
        )
        return Utf8JSONResponse(
            content=jsonable_encoder(body, by_alias=True, exclude_none=True), status_code=200 if ready else 503
        )

    if active.settings.env == "dev" and active.settings.admin_api_enabled:

        @app.post(
            "/v1/admin/contents:bulkUpsert",
            response_model=BulkUpsertResponse,
            responses={400: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}},
        )
        def bulk_upsert(body: BulkUpsertBody, principal: PrincipalDependency) -> Response:
            user_id = principal.user_id
            with state_lock:
                result = _bulk_upsert(active, user_id, body)
            return _json_model(result)

        @app.delete("/v1/admin/contents/{content_id}", status_code=204)
        def delete_content(content_id: str, principal: PrincipalDependency) -> Response:
            user_id = principal.user_id
            with state_lock:
                active.indexer.remove_content(user_id, content_id)
            return Response(status_code=204)

        ingest_service = ingest or _submit_only_ingest_service(active)
        app.state.ingest = ingest_service
        admin_errors: dict[int | str, dict[str, Any]] = {
            400: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
            500: {"model": ErrorEnvelope},
        }

        @app.post(
            "/v1/admin/ingest",
            status_code=202,
            response_model=IngestSubmitResponse,
            responses=admin_errors,
        )
        def submit_ingest(body: IngestBody, principal: PrincipalDependency) -> Response:
            user_id = principal.user_id
            result = ingest_service.submit(user_id, body.to_request(ingest_service.worker.clock()))
            response = IngestSubmitResponse(content_id=result.content_id, job_id=result.job_id, status=result.status)
            return _json_model(response, status_code=202)

        @app.get("/v1/admin/ingest/jobs/{job_id}", response_model=IngestJobResponse, responses=admin_errors)
        def ingest_job_status(job_id: str, principal: PrincipalDependency) -> Response:
            user_id = principal.user_id
            if not JOB_ID_RE.fullmatch(job_id):
                # 형식이 틀린 id도 "없는 잡"과 같은 응답을 준다 (존재 여부를 흘리지 않는다).
                raise NotFoundError("인제스트 잡을 찾을 수 없습니다", {"job_id": job_id[:64]})
            return _json_model(IngestJobResponse.from_job(ingest_service.status(user_id, job_id)))

    from jupjup.save.routes import save_router

    public_ingest = ingest or getattr(app.state, "ingest", None) or _submit_only_ingest_service(active)
    app.state.ingest = public_ingest
    from jupjup.container import analyzer_profile_name
    from jupjup.save.service import ContentCommandService

    commands = ContentCommandService(public_ingest, analyzer_profile_name(configuration))
    bridge = None
    if configuration.app_bridge_enabled:
        from jupjup.bridge.core_port import SaveCorePort
        from jupjup.bridge.service import ContentBridge

        bridge = ContentBridge(SaveCorePort(commands, active.repo))
    app.mount("/api", create_api(active.engine, bridge=bridge))
    app.include_router(save_router(public_ingest, active, commands))
    return app
