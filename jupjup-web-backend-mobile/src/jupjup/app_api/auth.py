"""Salted credentials, opaque sessions, and durable account password locks."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Connection, text

from jupjup.app_api import validation as v
from jupjup.app_api.errors import ContractError


def instant(now: datetime) -> str:
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str, salt: str) -> str:
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=64).hex()


def credentials(password: str) -> dict[str, str]:
    salt = secrets.token_hex(16)
    return {"password_salt": salt, "password_hash": hash_password(password, salt)}


def user_dto(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "nickname": user["nickname"],
        "notificationsEnabled": bool(user["notifications_enabled"]),
    }


def session(conn: Connection, user: dict[str, Any], now: datetime) -> dict[str, Any]:
    token = secrets.token_hex(32)
    expires = instant(now + timedelta(days=30))
    conn.execute(
        text("INSERT INTO api_sessions VALUES (:token,:user,:expires)"),
        dict(token=digest(token), user=user["id"], expires=expires),
    )
    return {"token": token, "expiresAt": expires, "user": user_dto(user)}


def authenticate(conn: Connection, authorization: str, now: datetime) -> tuple[dict[str, Any], str]:
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or len(parts[1]) != 64:
        raise ContractError(401, "UNAUTHORIZED")
    token_hash = digest(parts[1])
    row = (
        conn.execute(
            text(
                "SELECT u.* FROM api_users u JOIN api_sessions s ON s.user_id=u.id "
                "WHERE s.token_hash=:token AND s.expires_at>:now"
            ),
            dict(token=token_hash, now=instant(now)),
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ContractError(401, "UNAUTHORIZED")
    return dict(row), token_hash


def register(conn: Connection, body: dict[str, Any], now: datetime) -> dict[str, Any]:
    address = v.email(body)
    password = v.password(body, "password")
    nickname = v.string(body, "nickname", 25)
    if body.get("requiredConsent") is not True or type(body.get("notificationsEnabled", False)) is not bool:
        v.invalid()
    if conn.execute(text("SELECT 1 FROM api_users WHERE email=:email"), dict(email=address)).first():
        raise ContractError(409, "EMAIL_EXISTS")
    user = dict(
        id=str(uuid4()),
        email=address,
        nickname=nickname,
        notifications_enabled=int(body.get("notificationsEnabled", False)),
        consent_at=instant(now),
        **credentials(password),
    )
    conn.execute(
        text(
            "INSERT INTO api_users (id,email,nickname,notifications_enabled,consent_at,password_hash,password_salt) "
            "VALUES (:id,:email,:nickname,:notifications_enabled,:consent_at,:password_hash,:password_salt)"
        ),
        user,
    )
    return session(conn, user, now)


def login(conn: Connection, body: dict[str, Any], now: datetime) -> dict[str, Any]:
    address = v.email(body)
    password = v.string(body, "password", 128, trim=False)
    row = conn.execute(text("SELECT * FROM api_users WHERE email=:email"), dict(email=address)).mappings().first()
    # Perform the same expensive work for an unknown email.
    salt = row["password_salt"] if row else "00" * 16
    actual = hash_password(password, salt)
    expected = row["password_hash"] if row else "00" * 64
    if not hmac.compare_digest(actual, expected) or row is None:
        raise ContractError(401, "INVALID_CREDENTIALS")
    return session(conn, dict(row), now)


def verify_password(conn: Connection, user: dict[str, Any], body: dict[str, Any], now: datetime) -> None:
    password = v.string(body, "currentPassword", 128, trim=False)
    locked = user["password_locked_until"]
    if locked and locked > instant(now):
        raise ContractError(429, "PASSWORD_LOCKED")
    failures = 0 if locked else user["password_failures"]
    if not hmac.compare_digest(hash_password(password, user["password_salt"]), user["password_hash"]):
        failures += 1
        until = instant(now + timedelta(hours=24)) if failures >= 5 else None
        conn.execute(
            text("UPDATE api_users SET password_failures=:n,password_locked_until=:until WHERE id=:id"),
            dict(n=failures, until=until, id=user["id"]),
        )
        # An authentication failure is a durable security event, even though the request fails.
        conn.commit()
        raise ContractError(429 if until else 401, "PASSWORD_LOCKED" if until else "INVALID_CREDENTIALS")
    conn.execute(
        text("UPDATE api_users SET password_failures=0,password_locked_until=NULL WHERE id=:id"), dict(id=user["id"])
    )
