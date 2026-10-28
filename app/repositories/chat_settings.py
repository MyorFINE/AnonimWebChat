"""Moderatsiya sozlamalari (kalit-qiymat). Xotirada keshlanadi (bitta worker)."""
import json

from app.db import db

_cache: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _cache
    if _cache is None:
        _cache = {r["key"]: r["value"] for r in db.all("SELECT key, value FROM chat_settings")}
    return _cache


def get(key: str, default=None):
    raw = _load().get(key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


def put(key: str, value) -> None:
    raw = json.dumps(value, ensure_ascii=False)
    db.run("INSERT INTO chat_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, raw))
    _load()[key] = raw
