"""Harakatlar logi: kim (profil), qaysi IP'dan, nima qildi.

Parollar, shaxsiy xabarlar matni va ularning qabul qiluvchisi bu yerga YOZILMAYDI.
"""
import logging

from app.config import settings
from app.repositories import activity as repo

log = logging.getLogger("termchat.activity")

ACTIONS = {
    "register": "Ro'yxatdan o'tdi", "login": "Kirdi", "login_failed": "Kirish xatosi", "logout": "Chiqdi",
    "session": "Sessiya ochildi", "msg": "Umumiy chatga yozdi", "dm": "Lichkaga yozdi", "image": "Rasm yubordi", "file": "Fayl yubordi",
    "edit": "Tahrirladi", "delete": "O'chirdi", "clear": "Chatni tozaladi", "dm_clear": "Lichkani o'chirdi", "remove": "Akkauntni o'chirdi", "leave": "Akkauntini o'chirdi", "profile": "Profilni o'zgartirdi", "password": "Parolni almashtirdi",
    "avatar": "Profil rasmini o'zgartirdi", "color": "Rangni o'zgartirdi", "mod": "Moderatsiya",
    "media_clear": "Media o'chirdi", "log_clear": "Loglarni tozaladi", "badge": "Nishonni o'zgartirdi", "report": "Shikoyat qildi",
    "ip_block": "IP blokladi", "ip_unblock": "IP blokdan ochdi", "blocked": "Bloklangan IP urinishi",
}


def record(action: str, *, ip: str | None = None, user=None, username: str | None = None, detail: str | None = None) -> None:
    """Xatolik bo'lsa ham asosiy ish to'xtamasligi uchun hech qachon istisno ko'tarmaydi."""
    try:
        uid = user["id"] if user is not None else None
        name = user["username"] if user is not None else username
        repo.add(action, ip=ip, user_id=uid, username=name,
                 detail=(detail[:300] if detail else None), keep_days=settings.activity_days)
    except Exception:                           # pragma: no cover
        log.exception("Harakatni yozib bo'lmadi")
