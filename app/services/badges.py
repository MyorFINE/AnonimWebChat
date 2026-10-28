"""Profil nishoni: galochka o'rniga istalgan emoji va animatsiya (CSS orqali — tashqi resurs kerak emas).

Nishonni ega/adminlar o'zlariga qo'yadi; shuningdek oddiy foydalanuvchilarga ham bera oladi
(admin faqat oddiy foydalanuvchiga, ega — adminga ham).
"""
from __future__ import annotations

import re

from app.errors import ChatError
from app.repositories import users
from app.roles import Role, is_admin, role_of

ANIMS = ("none", "pulse", "bounce", "spin", "shake", "float", "glow", "flip", "wave", "rainbow")
HIDDEN = "none"                    # ega/admin galochkani butunlay yashirishi uchun
MAX_CODEPOINTS = 8
_EMOJI = re.compile(
    "^(?:[#*0-9]\ufe0f?\u20e3"
    "|[\u00a9\u00ae\u203c\u2049\u2122\u2139\u2190-\u21ff\u231a-\u23ff\u24c2\u25a0-\u27bf\u2934\u2935\u2b00-\u2bff\u3030\u303d\u3297\u3299"
    "\U0001f000-\U0001faff\U0001f1e6-\U0001f1ff\u200d\ufe0f\U0001f3fb-\U0001f3ff])+$")


def clean(badge, anim) -> tuple[str | None, str | None]:
    """(emoji | 'none' | None, animatsiya | None). None = standart (galochka)."""
    if badge is not None and not isinstance(badge, str) or anim is not None and not isinstance(anim, str):
        raise ChatError("Nishon noto'g'ri")
    badge = (badge or "").strip()
    anim = (anim or "").strip().lower()
    if anim and anim not in ANIMS:
        raise ChatError("Bunday animatsiya yo'q")
    if not badge:
        return None, None
    if badge == HIDDEN:
        return HIDDEN, None
    if len(badge) > MAX_CODEPOINTS or not _EMOJI.match(badge):
        raise ChatError("Nishon faqat emoji bo'lishi kerak (bittagina)")
    return badge, (None if anim in ("", "none") else anim)


def set_for(actor, target_id: int, badge, anim):
    if not is_admin(actor):
        raise ChatError("Nishonni faqat adminlar o'zgartira oladi", 403)
    t = users.get(target_id) if isinstance(target_id, int) else None
    if not t or t["deleted"]:
        raise ChatError("Foydalanuvchi topilmadi", 404)
    if t["id"] != actor["id"]:
        if role_of(t) == Role.OWNER or (role_of(t) == Role.ADMIN and role_of(actor) != Role.OWNER):
            raise ChatError("Bu foydalanuvchining nishonini o'zgartira olmaysiz", 403)
    b, a = clean(badge, anim)
    if b == HIDDEN and not is_admin(t):
        b = a = None
    users.set_badge(t["id"], b, a)
    return t
