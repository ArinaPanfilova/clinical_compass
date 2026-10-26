"""Пароли и токены доступа на стандартной библиотеке.

Токен: «user_id.истекает.подпись», подпись — HMAC-SHA256 по секрету сервера.
Пароли: PBKDF2-SHA256 с солью. Для продукта: MFA врачей, отзыв токенов, ротация секрета.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

ITERATIONS = 120_000


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), ITERATIONS)
    return hmac.compare_digest(digest.hex(), digest_hex)


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:40]


def make_token(user_id: str, secret: str, ttl_s: int = 12 * 3600, now: float | None = None) -> str:
    payload = f"{user_id}.{int((now or time.time()) + ttl_s)}"
    return f"{payload}.{_sign(secret, payload)}"


def read_token(token: str, secret: str, now: float | None = None) -> str | None:
    """user_id для действующего токена с верной подписью, иначе None."""
    try:
        user_id, exp, sig = token.rsplit(".", 2)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sign(secret, f"{user_id}.{exp}")):
        return None
    if not exp.isdigit() or int(exp) < (now or time.time()):
        return None
    return user_id
