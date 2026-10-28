"""Bazada saqlanadigan ma'lumotlarni shifrlash (at-rest): AES-256-GCM.

Xabar matni, tahrir/o'chirish loglari va harakatlar tafsiloti bazada FAQAT shifrlangan ko'rinishda yotadi
(`enc1:<base64>`). Shifrni ochish faqat server xotirasida, `open_()` orqali bajariladi.

Kalit manbai (ustuvorlik bo'yicha):
  1. TERMCHAT_MASTER_KEY muhit o'zgaruvchisi (tavsiya: hosting "secrets" bo'limida, bazadan alohida)
  2. data/master.key fayli (birinchi ishga tushirishda avtomatik yaratiladi, ruxsat 0600)
Kalit yo'qolsa, shifrlangan ma'lumotlarni qayta tiklab bo'lmaydi — zaxiralang.
"""
from __future__ import annotations

import base64
import logging
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings

log = logging.getLogger("termchat.crypto")

PREFIX = "enc1:"
BROKEN = "[shifrni ochib bo'lmadi]"


def _master_secret() -> bytes:
    raw = (settings.master_key or "").strip()
    if raw:
        if len(raw) < 16:
            raise RuntimeError("TERMCHAT_MASTER_KEY kamida 16 belgi bo'lishi kerak")
        return raw.encode()
    path = settings.master_key_path
    if path.is_file():
        return path.read_text(encoding="utf-8").strip().encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(48)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value)
    log.warning("Yangi shifrlash kaliti yaratildi: %s — uni zaxiralang (yoki TERMCHAT_MASTER_KEY bering)", path)
    return value.encode()


def _derive(secret: bytes, label: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"anonim-chat-by-hevorix", info=label).derive(secret)


_aead = AESGCM(_derive(_master_secret(), b"at-rest/v1"))


def is_sealed(value: str | None) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def seal(text: str | None, ctx: str) -> str | None:
    """Matnni shifrlaydi. `ctx` — shifrlangan qiymatni boshqa ustun/jadvalga ko'chirib bo'lmasligi uchun (AAD)."""
    if text is None:
        return None
    nonce = secrets.token_bytes(12)
    ct = _aead.encrypt(nonce, text.encode("utf-8"), ctx.encode())
    return PREFIX + base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def open_(value: str | None, ctx: str) -> str | None:
    """Shifrni ochadi. Eski (shifrlanmagan) qiymatlar o'zgarishsiz qaytariladi."""
    if value is None or not is_sealed(value):
        return value
    try:
        blob = base64.urlsafe_b64decode(value[len(PREFIX):].encode("ascii"))
        return _aead.decrypt(blob[:12], blob[12:], ctx.encode()).decode("utf-8")
    except (InvalidTag, ValueError, UnicodeDecodeError):
        log.error("Shifrni ochib bo'lmadi (ctx=%s)", ctx)
        return BROKEN


MEDIA_MAGIC = b"ACM1"


def seal_bytes(data: bytes, ctx: str) -> bytes:
    """Faylni shifrlaydi. Har bir fayl uchun alohida tasodifiy 256-bit kalit olinadi; u master kalit bilan
    o'ralib (wrap) fayl boshiga yoziladi. Format: ACM1 | wnonce(12) | wrapped_key(48) | nonce(12) | ciphertext."""
    fkey, wnonce, nonce = secrets.token_bytes(32), secrets.token_bytes(12), secrets.token_bytes(12)
    wrapped = _aead.encrypt(wnonce, fkey, b"media-key/" + ctx.encode())
    return MEDIA_MAGIC + wnonce + wrapped + nonce + AESGCM(fkey).encrypt(nonce, data, ctx.encode())


def open_bytes(blob: bytes, ctx: str) -> bytes | None:
    """Fayl shifrini ochadi. Buzilgan/begona fayl bo'lsa None."""
    try:
        if blob[:4] != MEDIA_MAGIC or len(blob) < 4 + 12 + 48 + 12 + 16:
            return None
        wnonce, wrapped, nonce, ct = blob[4:16], blob[16:64], blob[64:76], blob[76:]
        fkey = _aead.decrypt(wnonce, wrapped, b"media-key/" + ctx.encode())
        return AESGCM(fkey).decrypt(nonce, ct, ctx.encode())
    except (InvalidTag, ValueError):
        log.error("Fayl shifrini ochib bo'lmadi (ctx=%s)", ctx)
        return None


def admin_view(raw: str | None, ctx: str = "msg", n: int = 160) -> str:
    """ADMIN uchun ko'rinish: faqat shifrlangan shakl. E2EE konvert o'zgarishsiz; eski (server ochadigan) matn — bazadagi
    server-kalit shifrining boshi. Adminga hech qachon ochiq matn berilmaydi."""
    if not raw:
        return ""
    if raw.startswith("e2e1:"):
        return raw
    if is_sealed(raw):
        inner = open_(raw, ctx)
        if isinstance(inner, str) and inner.startswith("e2e1:"):
            return inner
    return preview(raw, n)


def preview(value: str | None, n: int = 72) -> str:
    """Admin ko'rinishi uchun: bazada yotgan shifrlangan matnning boshi."""
    if not value:
        return ""
    return value if len(value) <= n else value[:n] + "…"


def migrate_legacy(db) -> int:
    """Eski bazadagi shifrlanmagan matnlarni bir marta shifrlaydi. O'zgargan qatorlar sonini qaytaradi."""
    n = 0
    with db._lock:
        c = db._conn
        for table, cols, ctxs in (("messages", ("content",), ("msg",)),
                                  ("logs", ("old_content", "new_content"), ("log-old", "log-new")),
                                  ("activity", ("detail",), ("act",))):
            sel = ", ".join(cols)
            where = " OR ".join(f"({col} IS NOT NULL AND {col} NOT LIKE '{PREFIX}%' AND {col} NOT LIKE 'e2e1:%')" for col in cols)
            rows = c.execute(f"SELECT id, {sel} FROM {table} WHERE {where}").fetchall()
            for r in rows:
                sets, args = [], []
                for i, col in enumerate(cols):
                    v = r[i + 1]
                    if v is not None and not is_sealed(v) and not v.startswith("e2e1:"):
                        sets.append(f"{col}=?")
                        args.append(seal(v, ctxs[i]))
                if sets:
                    c.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", (*args, r[0]))
                    n += 1
        c.commit()
    if n:
        log.info("Eski ma'lumotlardan %d ta qator shifrlandi", n)
    return n
