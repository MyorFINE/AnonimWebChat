"""Chatga yuboriladigan fayllar (rasm, video, audio, hujjat — istalgan turdagi, 50 MB gacha).

* Rasm (haqiqiy fayl imzosi bo'yicha aniqlanadi): metadata tozalanadi (EXIF/GPS...), xira nusxa tayyorlanadi.
* Boshqa har qanday fayl: o'zgartirilmasdan saqlanadi, brauzerda faqat yuklab olinadi (hech qachon sahifa sifatida ochilmaydi).
* Diskda HAMMASI faqat shifrlangan holda yotadi (AES-256-GCM, har bir fayl uchun alohida kalit, kalit master kalit bilan o'ralgan).
  Fayl nomi ham bazada shifrlangan. Fayl serverdan faqat tizimga kirgan foydalanuvchiga beriladi (lichka — faqat ikki ishtirokchiga).
"""
from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from app import crypto
from app.config import settings
from app.errors import ChatError
from app.services import imgclean
from app.services.avatars import sniff_image

log = logging.getLogger("termchat.media")

CTX = "media"
NAME_RE = re.compile(r"^[0-9a-f]{32}(?:_t)?\.(?:png|jpg|webp|gif|bin|e2e)$")
MIME_BY_EXT = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "gif": "image/gif", "bin": "application/octet-stream"}
_MIME_RE = re.compile(r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$")


@dataclass
class Stored:
    image: str | None = None         # rasm: saqlangan nom (stem.ext)
    width: int | None = None
    height: int | None = None
    file: str | None = None          # boshqa fayl: saqlangan nom (stem.bin)
    file_name: str | None = None     # foydalanuvchi bergan asl nom (tozalangan)
    file_mime: str | None = None
    size: int = 0


def limit_mb() -> int:
    return settings.max_media_bytes // (1024 * 1024)


def validate(raw: bytes) -> None:
    if not raw:
        raise ChatError("Fayl tanlanmagan")
    if len(raw) > settings.max_media_bytes:
        raise ChatError(f"Fayl {limit_mb()} MB dan oshmasligi kerak")


def sanitize_name(name: str | None) -> str:
    """Yo'l, boshqaruv belgilari va maxsus belgilar olib tashlanadi; uzunligi 100 belgigacha (kengaytma saqlanadi)."""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f<>:\"|?*\u202a-\u202e\u2066-\u2069]", "", name).strip(" .")
    if len(name) > 100:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 100 - len(ext) - 1] + "." + ext[:10]) if dot and len(ext) <= 10 and stem else name[:100]
    return name or "fayl"


def clean_mime(mime: str | None) -> str:
    m = (mime or "").split(";")[0].strip().lower()
    return m if len(m) <= 100 and _MIME_RE.match(m) else "application/octet-stream"


def thumb_name(name: str) -> str:
    return name.rsplit(".", 1)[0] + "_t.jpg"


def _path(name: str) -> Path:
    if name.endswith(".e2e"):                       # E2EE fayl: mijoz allaqachon shifrlagan, server o'zgartirmay saqlaydi
        return settings.media_dir / name
    return settings.media_dir / (name + ".enc")


def _write(name: str, data: bytes) -> None:
    path = _path(name)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(crypto.seal_bytes(data, CTX))
    tmp.replace(path)


def store(raw: bytes, filename: str | None = None, mime: str | None = None) -> Stored:
    """Faylni tekshiradi va shifrlab saqlaydi. Rasm bo'lsa rasm sifatida, aks holda oddiy fayl sifatida."""
    validate(raw)
    stem = secrets.token_hex(16)
    if sniff_image(raw):
        try:
            img = imgclean.clean(raw)
        except ChatError:                                   # buzilgan "rasm": oddiy fayl sifatida (faqat yuklab olinadi)
            img = None
        if img is not None:
            name = f"{stem}.{img.ext}"
            _write(name, img.data)
            _write(thumb_name(name), img.thumb)
            return Stored(image=name, width=img.width, height=img.height, size=len(img.data))
    name = f"{stem}.bin"
    _write(name, raw)
    return Stored(file=name, file_name=sanitize_name(filename), file_mime=clean_mime(mime), size=len(raw))


def store_opaque(raw: bytes) -> str:
    """E2EE fayl: shifrlangan baytlar (iv | AES-GCM) o'zgartirilmay saqlanadi. Server na turini, na nomini, na mazmunini biladi."""
    if not raw or len(raw) < 12 + 16:
        raise ChatError("Fayl bo'sh")
    if len(raw) > settings.max_media_bytes + 64:
        raise ChatError(f"Fayl {limit_mb()} MB dan oshmasligi kerak")
    name = secrets.token_hex(16) + ".e2e"
    path = _path(name)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)
    return name


def content_type(name: str) -> str:
    return MIME_BY_EXT.get(name.rsplit(".", 1)[-1], "application/octet-stream")


def read(name: str) -> bytes | None:
    """Shifrdan ochilgan fayl baytlari yoki None. (Migratsiya qilinmagan eski ochiq fayllar ham o'qiladi.)"""
    if not NAME_RE.match(name):
        return None
    p = _path(name)
    if name.endswith(".e2e"):
        return p.read_bytes() if p.is_file() else None
    if p.is_file():
        return crypto.open_bytes(p.read_bytes(), CTX)
    legacy = settings.uploads_dir / name
    if legacy.is_file():
        return legacy.read_bytes()
    return None


def _unlink(name: str) -> None:
    for p in (_path(name), settings.uploads_dir / name):
        try:
            p.unlink()
        except OSError:
            pass


def remove(name: str | None) -> None:
    if not name or not NAME_RE.match(name):
        return
    _unlink(name)
    if not name.endswith(".bin"):
        _unlink(thumb_name(name))


def remove_row(row) -> None:
    """Xabar qatoridagi rasm va/yoki faylni diskdan o'chiradi."""
    keys = row.keys() if hasattr(row, "keys") else row
    for k in ("image", "file"):
        if k in keys:
            remove(row[k])


def migrate_legacy() -> int:
    """Eski (shifrlanmagan) /uploads fayllarini bir marta shifrlab, ochiq nusxasini o'chiradi."""
    n = 0
    for p in settings.uploads_dir.iterdir():
        if p.is_file() and NAME_RE.match(p.name):
            try:
                _write(p.name, p.read_bytes())
                p.unlink()
                n += 1
            except OSError:
                log.exception("Eski faylni shifrlab bo'lmadi: %s", p.name)
    if n:
        log.info("Eski %d ta fayl shifrlandi", n)
    return n
