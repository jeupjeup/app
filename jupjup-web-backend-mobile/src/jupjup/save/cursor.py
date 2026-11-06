"""Authenticated opaque keyset cursors bound to user and query."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from jupjup.api.errors import ApiError
from jupjup.storage.save_repositories import canonical_json


def encode_cursor(payload: dict[str, Any], secret: str) -> str:
    raw = canonical_json(payload).encode()
    signature = hmac.digest(secret.encode(), raw, "sha256")
    return base64.urlsafe_b64encode(signature + raw).decode().rstrip("=")


def decode_cursor(token: str, scope: str, secret: str) -> tuple[str, str]:
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        signature, payload = raw[:32], raw[32:]
        if not hmac.compare_digest(signature, hmac.digest(secret.encode(), payload, "sha256")):
            raise ValueError("signature")
        data = json.loads(payload)
        if data["version"] != 1 or data["scope"] != scope:
            raise ValueError("scope")
        return str(data["sort_value"]), str(data["id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ApiError(422, "INVALID_CURSOR", "커서가 올바르지 않습니다") from exc


def cursor_scope(user_id: str, filters: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json([user_id, filters]).encode()).hexdigest()
