"""Хеширование пароля (PBKDF2) и подписанные сессионные токены (HMAC) — stdlib."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

_PBKDF_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, rounds, salt_b64, dk_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(dk, expected)
    except Exception:  # noqa: BLE001
        return False


def new_secret() -> str:
    return secrets.token_hex(32)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_session(username: str, secret: str, ttl_seconds: int = 30 * 24 * 3600) -> str:
    payload = {"u": username, "exp": int(time.time()) + ttl_seconds}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_session(token: str | None, secret: str) -> str | None:
    """Возвращает username, если токен валиден и не истёк, иначе None."""
    if not token or not secret or "." not in token:
        return None
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_unb64(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload.get("u")
    except Exception:  # noqa: BLE001
        return None
