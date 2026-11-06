"""Public manual collection API."""

from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import Engine

from jupjup.api.dto import ErrorEnvelope
from jupjup.auth import PrincipalDependency
from jupjup.collections.service import (
    CollectionBody,
    CollectionPage,
    CollectionPatch,
    CollectionService,
    CollectionView,
)


def collections_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/v1/collections", responses={c: {"model": ErrorEnvelope} for c in (404, 409, 422)})
    service = CollectionService(engine)

    @router.get("", response_model=CollectionPage)
    def listing(principal: PrincipalDependency) -> dict[str, Any]:
        return service.list(principal.user_id)

    @router.post("", response_model=CollectionView, status_code=201)
    def create(body: CollectionBody, principal: PrincipalDependency) -> dict[str, Any]:
        return service.write(principal.user_id, body)

    @router.get("/{collection_id}", response_model=CollectionView)
    def detail(collection_id: str, principal: PrincipalDependency) -> dict[str, Any]:
        return service.list(principal.user_id, collection_id)

    @router.patch("/{collection_id}", response_model=CollectionView)
    def patch(collection_id: str, body: CollectionPatch, principal: PrincipalDependency) -> dict[str, Any]:
        return service.write(principal.user_id, body, collection_id)

    @router.delete("/{collection_id}", status_code=204)
    def delete(collection_id: str, principal: PrincipalDependency) -> Response:
        service.delete(principal.user_id, collection_id)
        return Response(status_code=204)

    @router.put("/{collection_id}/contents/{content_id}", status_code=204)
    def add(collection_id: str, content_id: str, principal: PrincipalDependency) -> Response:
        service.membership(principal.user_id, collection_id, content_id, add=True)
        return Response(status_code=204)

    @router.delete("/{collection_id}/contents/{content_id}", status_code=204)
    def remove(collection_id: str, content_id: str, principal: PrincipalDependency) -> Response:
        service.membership(principal.user_id, collection_id, content_id, add=False)
        return Response(status_code=204)

    return router
