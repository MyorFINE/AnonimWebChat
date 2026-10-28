"""Moderatsiya: mute, ban, rollar. Barcha amallar logga yoziladi."""
import time

from app.config import settings
from app.errors import ChatError
from app.repositories import logs, messages, sessions, users
from app.roles import Role, role_of
from app.services import media

PERMANENT = 10 * 365 * 86400
WARN_LIMIT = 3                  # shuncha ogohlantirishdan keyin avtomatik mute
WARN_MUTE_MINUTES = 60
MAX_PURGE = 200                 # bir martada tozalanadigan xabarlar soni chegarasi


def _target(actor, username: str):
    t = users.get_by_username(username)
    if not t:
        raise ChatError("Bunday foydalanuvchi topilmadi")
    if t["id"] == actor["id"]:
        raise ChatError("O'zingizga qo'llay olmaysiz")
    if role_of(t) == Role.OWNER:
        raise ChatError("Egaga qo'llab bo'lmaydi")
    if role_of(t) == Role.ADMIN and role_of(actor) != Role.OWNER:
        raise ChatError("Adminga faqat ega qo'llay oladi")
    return t


def parse_mute(rest: str) -> tuple[int, str, str]:
    """'[daqiqa|perm] [sabab]' -> (soniya, yorliq, sabab)."""
    parts = rest.split(None, 1)
    head = parts[0].lower() if parts else ""
    tail = parts[1] if len(parts) > 1 else ""
    if head == "perm":
        return PERMANENT, "doimiy", tail
    if head.isdigit():
        minutes = int(head)
        if not 1 <= minutes <= 525600:
            raise ChatError("Davomiylik 1 dan 525600 daqiqagacha bo'lishi kerak")
        return minutes * 60, f"{minutes} daqiqa", tail
    m = settings.default_mute_minutes
    return m * 60, f"{m} daqiqa", rest.strip()


def mute(actor, username: str, rest: str):
    t = _target(actor, username)
    seconds, label, reason = parse_mute(rest)
    users.set_mute(t["id"], time.time() + seconds, reason)
    logs.add("mute", user_id=t["id"], actor_id=actor["id"], new=label + (f": {reason}" if reason else ""))
    return t, label, reason


def unmute(actor, username: str):
    t = _target(actor, username)
    users.set_mute(t["id"], 0, None)
    logs.add("unmute", user_id=t["id"], actor_id=actor["id"])
    return t


def ban(actor, username: str, reason: str):
    t = _target(actor, username)
    users.set_ban(t["id"], True, reason)
    sessions.delete_for_user(t["id"])
    logs.add("ban", user_id=t["id"], actor_id=actor["id"], new=reason or None)
    return t


def unban(actor, username: str):
    t = _target(actor, username)
    users.set_ban(t["id"], False, None)
    logs.add("unban", user_id=t["id"], actor_id=actor["id"])
    return t


def set_role(actor, username: str, role: Role):
    t = _target(actor, username)          # ega boshqa egaga/o'ziga qo'llay olmaydi
    users.set_role(t["id"], role.db_name)
    logs.add("role", user_id=t["id"], actor_id=actor["id"], new=role.db_name)
    return t


def warn(actor, username: str, reason: str = ""):
    """Ogohlantirish beradi. WARN_LIMIT ga yetsa, hisob nolga tushadi va foydalanuvchi avtomatik mute qilinadi.
    (nishon_qatori, hozirgi_ogohlantirishlar, avtomatik_mute_bo'ldimi) qaytaradi."""
    t = _target(actor, username)
    reason = (reason or "").strip()[:200]
    n = t["warns"] + 1
    auto = n >= WARN_LIMIT
    if auto:
        users.set_warns(t["id"], 0)
        users.set_mute(t["id"], time.time() + WARN_MUTE_MINUTES * 60, f"{WARN_LIMIT} ta ogohlantirish")
    else:
        users.set_warns(t["id"], n)
    note = f"{n}/{WARN_LIMIT}" + (f": {reason}" if reason else "") + (f" → {WARN_MUTE_MINUTES} daqiqa mute" if auto else "")
    logs.add("warn", user_id=t["id"], actor_id=actor["id"], new=note)
    return t, (0 if auto else n), auto


def unwarn(actor, username: str):
    t = _target(actor, username)
    if t["warns"] <= 0:
        raise ChatError("Bu foydalanuvchida ogohlantirish yo'q")
    users.set_warns(t["id"], t["warns"] - 1)
    logs.add("unwarn", user_id=t["id"], actor_id=actor["id"], new=f"{t['warns'] - 1}/{WARN_LIMIT}")
    return t, t["warns"] - 1


def purge_user(actor, username: str, limit: int = MAX_PURGE):
    """Foydalanuvchining umumiy chatdagi oxirgi xabarlarini (va fayllarini) o'chiradi. (nishon, o'chirilgan_qatorlar)."""
    t = _target(actor, username)
    rows = messages.group_by_user(t["id"], max(1, min(limit, MAX_PURGE)))
    for r in rows:
        messages.mark_deleted(r["id"])
        media.remove_row(r)
    logs.add("purge", user_id=t["id"], actor_id=actor["id"], new=f"{len(rows)} ta xabar")
    return t, rows
