"""Profil rasmlari (har bir foydalanuvchiga ko'pi bilan MAX_AVATARS ta)."""
import secrets
import time

from app.config import settings
from app.errors import ChatError
from app.repositories import avatars, users


def sniff_image(raw: bytes) -> str | None:
    """Kengaytma emas, haqiqiy fayl imzosi bo'yicha aniqlaydi."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    if raw[:4] == b"GIF8":
        return "gif"
    return None


def upload(user, raw: bytes) -> None:
    if len(avatars.list_for_user(user["id"])) >= settings.max_avatars:
        raise ChatError(f"Eng ko'pi bilan {settings.max_avatars} ta rasm. Avval /avatar del N bilan o'chiring")
    if len(raw) > settings.max_avatar_bytes:
        raise ChatError(f"Rasm {settings.max_avatar_bytes // (1024 * 1024)} MB dan oshmasligi kerak")
    if not sniff_image(raw):
        raise ChatError("Faqat PNG, JPG, WEBP yoki GIF rasmlar mumkin")
    from app.services import imgclean               # metadata (EXIF/GPS va h.k.) olib tashlanadi
    img = imgclean.clean(raw)
    name = f"{secrets.token_hex(12)}.{img.ext}"
    (settings.avatars_dir / name).write_bytes(img.data)
    aid = avatars.add(user["id"], name, time.time())
    users.set_active_avatar(user["id"], aid)


def list_for(user) -> list[tuple[int, object, bool]]:
    return [(i, a, a["id"] == user["active_avatar_id"])
            for i, a in enumerate(avatars.list_for_user(user["id"]), 1)]


def _nth(user, n: str):
    items = avatars.list_for_user(user["id"])
    if not n.isdigit() or not 1 <= int(n) <= len(items):
        raise ChatError("Bunday raqamli rasm yo'q (/avatar list)")
    return items[int(n) - 1]


def activate(user, n: str) -> None:
    users.set_active_avatar(user["id"], _nth(user, n)["id"])


def clear_active(user) -> None:
    users.set_active_avatar(user["id"], None)


def remove(user, n: str) -> None:
    a = _nth(user, n)
    if user["active_avatar_id"] == a["id"]:
        users.set_active_avatar(user["id"], None)
    avatars.delete(a["id"])
    try:
        (settings.avatars_dir / a["filename"]).unlink()
    except OSError:
        pass


# ---- id bo'yicha (veb-interfeys uchun)
def gallery(user) -> list[dict]:
    return [{"id": a["id"], "url": f"/avatars/{a['filename']}", "active": a["id"] == user["active_avatar_id"]}
            for a in avatars.list_for_user(user["id"])]


def _own(user, avatar_id: int):
    for a in avatars.list_for_user(user["id"]):
        if a["id"] == avatar_id:
            return a
    raise ChatError("Rasm topilmadi", 404)


def activate_id(user, avatar_id: int) -> None:
    users.set_active_avatar(user["id"], _own(user, avatar_id)["id"])


def remove_id(user, avatar_id: int) -> None:
    a = _own(user, avatar_id)
    if user["active_avatar_id"] == a["id"]:
        users.set_active_avatar(user["id"], None)
    avatars.delete(a["id"])
    try:
        (settings.avatars_dir / a["filename"]).unlink()
    except OSError:
        pass
