"""Akkauntni o'chirish: admin chiqarib tashlashi yoki foydalanuvchining o'zi chiqib ketishi.

Qator bazadan o'chirilmaydi: akkaunt "Deleted account" (ghost) bo'lib qoladi, shaxsiy ma'lumotlari
(username, nickname, bio, rang, profil rasmlari, parol) tozalanadi, yozgan xabarlari esa turadi.
"""
import time

from app.config import settings
from app.errors import ChatError
from app.repositories import avatars, logs, sessions, users
from app.roles import Role, role_of
from app.security import verify_password
from app.services import moderation


def _wipe(t) -> None:
    for a in avatars.list_for_user(t["id"]):
        avatars.delete(a["id"])
        try:
            (settings.avatars_dir / a["filename"]).unlink()
        except OSError:
            pass
    sessions.delete_for_user(t["id"])
    users.mark_deleted(t["id"], time.time())


def remove(actor, username: str):
    """Admin/ega foydalanuvchini chiqarib tashlaydi (qoidalar ban bilan bir xil)."""
    t = moderation._target(actor, username)
    if t["deleted"]:
        raise ChatError("Bu akkaunt allaqachon o'chirilgan")
    _wipe(t)
    logs.add("remove", user_id=t["id"], actor_id=actor["id"], new=t["username"])
    return t


def delete_self(user, password: str):
    if role_of(user) == Role.OWNER:
        raise ChatError("Platforma egasi o'z akkauntini o'chira olmaydi", 403)
    if not verify_password(password or "", user["password_hash"]):
        raise ChatError("Parol noto'g'ri", 403)
    _wipe(user)
    logs.add("leave", user_id=user["id"], actor_id=user["id"], new=user["username"])
    return user
