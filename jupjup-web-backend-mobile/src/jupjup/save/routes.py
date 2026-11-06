"""Public save API routes. SQL and orchestration live in save services."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Query, Response
from fastapi.encoders import jsonable_encoder

from jupjup.api.dto import ErrorEnvelope
from jupjup.api.errors import ApiError, Utf8JSONResponse
from jupjup.auth import PrincipalDependency
from jupjup.container import AppContainer, analyzer_profile_name
from jupjup.domain.errors import ContentValidationError
from jupjup.ingest.service import IngestService
from jupjup.save.dto import (
    AliasDetail,
    ContentDetail,
    ContentPage,
    ContentPatch,
    CreateContent,
    JobDetail,
    ReanalyzeRequest,
    ReviewRequest,
    ReviewResponse,
    SubmitResponse,
)
from jupjup.save.jobs import job_detail, review
from jupjup.save.patch import apply_user_patch
from jupjup.save.query import ContentListQuery, ContentQueryService
from jupjup.save.service import ContentCommandService


def save_router(
    ingest: IngestService, container: AppContainer, service: ContentCommandService | None = None
) -> APIRouter:
    router = APIRouter(responses={code: {"model": ErrorEnvelope} for code in (400, 404, 409, 422, 500, 503)})
    service = service or ContentCommandService(ingest, analyzer_profile_name(container.settings))

    def submitted(status: int, payload: dict[str, Any], replayed: bool) -> Response:
        headers = {"Location": f"/v1/contents/{payload['content_id']}"}
        if payload["job_id"]:
            headers["Content-Location"] = f"/v1/jobs/{payload['job_id']}"
        if replayed:
            headers["Idempotency-Replayed"] = "true"
        return Utf8JSONResponse(payload, status_code=status, headers=headers)

    @router.post(
        "/v1/contents", status_code=202, response_model=SubmitResponse, responses={200: {"model": SubmitResponse}}
    )
    def create(
        body: CreateContent, principal: PrincipalDependency, idempotency_key: Annotated[str | None, Header()] = None
    ) -> Response:
        return submitted(*service.submit(principal.user_id, body, idempotency_key))

    @router.post("/v1/contents/{content_id}:reanalyze", status_code=202, response_model=SubmitResponse)
    def reanalyze(
        content_id: str,
        body: ReanalyzeRequest,
        principal: PrincipalDependency,
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> Response:
        return submitted(*service.submit(principal.user_id, body, idempotency_key, content_id))

    queries = ContentQueryService(ingest.repo, container.settings.cursor_secret)

    @router.get("/v1/contents/{content_id}", response_model=ContentDetail | AliasDetail)
    def detail(content_id: str, principal: PrincipalDependency) -> Response:
        payload = queries.get(principal.user_id, content_id)
        return Utf8JSONResponse(
            jsonable_encoder(payload), headers={"ETag": f'"content:{content_id}:{payload["revision"]}"'}
        )

    @router.get("/v1/contents", response_model=ContentPage)
    def listing(principal: PrincipalDependency, query: Annotated[ContentListQuery, Query()]) -> Response:
        return Utf8JSONResponse(jsonable_encoder(queries.list(principal.user_id, query)))

    @router.patch("/v1/contents/{content_id}", response_model=ContentDetail | AliasDetail)
    def patch(
        content_id: str,
        body: ContentPatch,
        principal: PrincipalDependency,
        if_match: Annotated[str | None, Header()] = None,
    ) -> Response:
        try:
            apply_user_patch(ingest.repo, principal.user_id, content_id, body, if_match)
        except ContentValidationError as exc:
            raise ApiError(422, "INVALID_PATCH", "세부 태그 형식이 올바르지 않습니다") from exc
        container.indexer.index_content(principal.user_id, content_id)
        container.indexer.refresh_if_stale(principal.user_id)
        return detail(content_id, principal)

    @router.delete("/v1/contents/{content_id}", status_code=204)
    def delete_content(content_id: str, principal: PrincipalDependency) -> Response:
        container.indexer.remove_content(principal.user_id, content_id)
        return Response(status_code=204)

    @router.post(
        "/v1/contents/{content_id}:review", response_model=ReviewResponse, responses={202: {"model": ReviewResponse}}
    )
    def decide(content_id: str, body: ReviewRequest, principal: PrincipalDependency) -> Response:
        status, payload = review(ingest, principal.user_id, content_id, body)
        return Utf8JSONResponse(payload, status_code=status)

    @router.get("/v1/jobs/{job_id}", response_model=JobDetail)
    def job(
        job_id: str, principal: PrincipalDependency, trace: Literal["none", "summary", "full"] = "summary"
    ) -> Response:
        return Utf8JSONResponse(
            jsonable_encoder(job_detail(ingest, principal.user_id, job_id, trace)),
            headers={"Cache-Control": "private, no-store"},
        )

    from jupjup.collections.routes import collections_router

    router.include_router(collections_router(ingest.repo.engine))
    return router
