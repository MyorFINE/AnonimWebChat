"""Umumiy chat moderatsiyasi: sekin rejim, qulflash, taqiqlangan so'zlar va avtomatik antispam.

Sozlamalar bazada saqlanadi. Qoidalar faqat UMUMIY chatga tegishli va adminlarga/egaga qo'llanmaydi;
shaxsiy yozishmalar (lichka) hech qachon filtrlanmaydi va tekshirilmaydi.
"""
from __future__ import annotations

import re
import time
from math import ceil

from app.errors import ChatError
from app.repositories import chat_settings, logs, users
from app.roles import is_admin
from app.security import limiter

MAX_SLOWMODE = 3600
MAX_WORDS = 200
SPAM_MUTE_SECONDS = 300
_last_post: dict[int, float] = {}
_APOS = str.maketrans({"’": "'", "ʻ": "'", "ʼ": "'", "‘": "'", "`": "'", "´": "'"})
_ZW = re.compile("[\u200b-\u200f\u2060\ufeff]")


def get() -> dict:
    return {
        "slowmode": int(chat_settings.get("slowmode", 0) or 0),
        "locked": bool(chat_settings.get("locked", False)),
        "words": list(chat_settings.get("words", []) or []),
    }


def public() -> dict:
    """Hamma foydalanuvchiga ko'rinadigan qism (so'zlar ro'yxati yashirin)."""
    s = get()
    return {"slowmode": s["slowmode"], "locked": s["locked"]}


def _norm(text: str) -> str:
    return _ZW.sub("", (text or "").translate(_APOS)).lower()


def set_slowmode(actor, seconds) -> int:
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 0 <= seconds <= MAX_SLOWMODE:
        raise ChatError(f"Sekin rejim 0 dan {MAX_SLOWMODE} soniyagacha bo'lishi kerak")
    chat_settings.put("slowmode", seconds)
    logs.add("slowmode", user_id=actor["id"], actor_id=actor["id"], new=f"{seconds} soniya" if seconds else "o'chirildi")
    return seconds


def set_locked(actor, locked: bool) -> bool:
    chat_settings.put("locked", bool(locked))
    logs.add("lock" if locked else "unlock", user_id=actor["id"], actor_id=actor["id"])
    return bool(locked)


def clean_words(words) -> list[str]:
    """Ro'yxatni tozalaydi: kichik harf, 2–32 belgi, takrorlarsiz. Oxiridagi `*` — prefiks bo'yicha moslik."""
    if not isinstance(words, list):
        raise ChatError("So'zlar ro'yxati noto'g'ri")
    out: list[str] = []
    for w in words:
        if not isinstance(w, str):
            continue
        w = " ".join(_norm(w).split())
        if len(w.rstrip("*")) < 2 or len(w) > 32 or w.startswith("*") or w in out:
            continue
        out.append(w)
    if len(out) > MAX_WORDS:
        raise ChatError(f"Taqiqlangan so'zlar {MAX_WORDS} tadan oshmasligi kerak")
    return out


def set_words(actor, words) -> list[str]:
    cleaned = clean_words(words)
    chat_settings.put("words", cleaned)
    logs.add("words", user_id=actor["id"], actor_id=actor["id"], new=f"{len(cleaned)} ta so'z")
    return cleaned


def _pattern(word: str) -> re.Pattern:
    prefix = word.endswith("*")
    core = re.escape(word.rstrip("*"))
    return re.compile(r"(?<!\w)" + core + (r"\w*" if prefix else r"(?!\w)"))


def find_banned(text: str, words: list[str] | None = None) -> str | None:
    t = _norm(text)
    for w in (get()["words"] if words is None else words):
        if _pattern(w).search(t):
            return w
    return None


def check_words(user, text: str) -> None:
    if is_admin(user) or not text:
        return
    if find_banned(text):
        raise ChatError("Xabaringizda taqiqlangan so'z bor")


def check_group(user, text: str) -> None:
    """Umumiy chatga yozishdan oldin: qulf, taqiqlangan so'zlar, sekin rejim (adminlar uchun qo'llanmaydi)."""
    if is_admin(user):
        return
    s = get()
    if s["locked"]:
        raise ChatError("Umumiy chat hozir faqat adminlar uchun ochiq (qulflangan)", 403)
    check_words(user, text)
    if s["slowmode"]:
        left = s["slowmode"] - (time.monotonic() - _last_post.get(user["id"], -1e9))
        if left > 0:
            raise ChatError(f"Sekin rejim: yana {ceil(left)} soniya kuting", 429)


def note_post(user) -> None:
    _last_post[user["id"]] = time.monotonic()


def spam_strike(user) -> str | None:
    """Tezlik limitiga qayta-qayta urilgan oddiy foydalanuvchini avtomatik mute qiladi (1 daqiqada 3 martadan keyin)."""
    if is_admin(user) or limiter.allow(f"spam:{user['id']}", 3, 60):
        return None
    users.set_mute(user["id"], time.time() + SPAM_MUTE_SECONDS, "spam (avtomatik)")
    logs.add("mute", user_id=user["id"], actor_id=None, new=f"{SPAM_MUTE_SECONDS // 60} daqiqa: spam (avtomatik)")
    return f"Spam uchun {SPAM_MUTE_SECONDS // 60} daqiqaga avtomatik mute qilindingiz"
