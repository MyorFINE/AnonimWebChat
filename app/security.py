"""Parol, token va tezlik cheklovi."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from app.errors import ChatError

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=_N, r=_R, p=_P)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Bazada token o'zi emas, faqat hash saqlanadi."""
    return hashlib.sha256(token.encode()).hexdigest()


class RateLimiter:
    """Xotirada ishlovchi sliding-window cheklov (bitta worker uchun)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] >= window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        if len(self._hits) > 20000:      # eskirgan kalitlarni tozalash
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= 3600]:
                self._hits.pop(k, None)
        return True

    def check(self, key: str, limit: int, window: float, message: str) -> None:
        if not self.allow(key, limit, window):
            raise ChatError(message, 429)


limiter = RateLimiter()
