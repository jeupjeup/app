"""Explicit trusted identities for pre-session API fixtures, never used by the app."""

from typing import Any

from fastapi import FastAPI, Request

from jupjup.api.app import create_app as real_create_app
from jupjup.auth import Principal, get_principal


def create_app(*args: Any, **kwargs: Any) -> FastAPI:
    app = real_create_app(*args, **kwargs)

    def trusted_fixture(request: Request) -> Principal:
        return app.state.authenticator.authenticate(request)  # type: ignore[no-any-return]

    app.dependency_overrides[get_principal] = trusted_fixture
    return app
