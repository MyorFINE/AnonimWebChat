"""Ro'yxatdan o'tish, kirish, sessiya, profil sozlamalari."""
import re
import sqlite3
import threading
import time

from app.constants import OWNER_USERNAME
from app.errors import ChatError
from app.repositories import sessions, users
from app.roles import Role, role_of
from app.config import settings
from app.security import hash_password, hash_token, new_token, verify_password
from app.services import e2ee as e2ee_svc
from app.services import views

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")
RESERVED = {"system", "root", "admin", "administrator", "server", "owner", OWNER_USERNAME.lower()}
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_register_lock = threading.Lock()


def clean_nickname(raw: str) -> str:
    nick = re.sub(r"[\x00-\x1f\x7f]", "", raw or "")
    nick = re.sub(r"\s+", " ", nick).strip()
    if not 1 <= len(nick) <= 24:
        raise ChatError("Nickname 1-24 belgi bo'lishi kerak")
    return nick


def _check_password(pw: str) -> None:
    if not 6 <= len(pw) <= 128:
        raise ChatError("Parol 6-128 belgi bo'lishi kerak")


def _open_session(uid: int) -> tuple[str, dict]:
    token = new_token()
    sessions.create(hash_token(token), uid, time.time())
    return token, views.user_view(uid)


def username_status(raw: str) -> tuple[bool, str]:
    """(bo'shmi, sabab). Katta-kichik harf farqsiz: Hevorix, HEVORIX, hevorix hammasi band."""
    username = (raw or "").strip().lstrip("@").lower()
    if not USERNAME_RE.match(username):
        return False, "Username: 3-20 belgi, faqat a-z, 0-9 va _"
    if username in RESERVED or users.get_by_username(username):
        return False, "Bu username band"
    return True, "Bo'sh"


def register(username: str, nickname: str, password: str, e2ee_keys: dict | None = None) -> tuple[str, dict]:
    """E2EE rejimida (standart) `password` — brauzer parolidan hosil qilgan 256-bitli kirish kaliti (hex), asl parol
    serverga umuman kelmaydi; `e2ee_keys` — ommaviy kalitlar va parol bilan o'ralgan maxfiy kalitlar."""
    username = username.strip().lstrip("@").lower()
    if not USERNAME_RE.match(username):
        raise ChatError("Username: 3-20 belgi, faqat a-z, 0-9 va _")
    if username in RESERVED or username.startswith("deleted_"):
        raise ChatError("Bu username band", 409)
    nick = clean_nickname(nickname)
    keys = None
    if e2ee_keys is not None or settings.require_e2ee:
        keys = e2ee_svc.validate_account_keys(e2ee_keys)
        e2ee_svc.check_auth(password)
    else:
        _check_password(password)
    pw_hash = hash_password(password)
    with _register_lock:
        try:
            uid = users.create(username, nick, pw_hash, Role.USER.db_name, time.time(), keys)
        except sqlite3.IntegrityError:
            raise ChatError("Bu username band", 409)
    return _open_session(uid)


def login(username: str, password: str) -> tuple[str, dict]:
    user = users.get_by_username(username)
    if not user or user["deleted"] or not verify_password(password, user["password_hash"]):
        raise ChatError("Username yoki parol noto'g'ri", 401)
    if user["banned"]:
        reason = f": {user['ban_reason']}" if user["ban_reason"] else ""
        raise ChatError(f"Siz ban qilingansiz{reason}", 403)
    return _open_session(user["id"])


def authenticate(token: str):
    """Token bo'yicha foydalanuvchi qatori yoki None."""
    return sessions.get_user(hash_token(token)) if token else None


def logout(token: str) -> None:
    if token:
        sessions.delete(hash_token(token))


def clean_bio(raw: str) -> str:
    bio = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw or "").strip()
    if len(bio) > 140:
        raise ChatError("Bio 140 belgidan oshmasligi kerak")
    return bio


def change_nickname(user, raw: str) -> dict:
    users.set_nickname(user["id"], clean_nickname(raw))
    return views.user_view(user["id"])


def clean_color(user, raw: str) -> str | None:
    """Profil rangi faqat ega/adminlar uchun. Bo'sh qator = standart rangga qaytarish."""
    if role_of(user) < Role.ADMIN:
        raise ChatError("Profil rangini faqat adminlar tanlay oladi", 403)
    raw = (raw or "").strip()
    if not raw:
        return None
    if not COLOR_RE.match(raw):
        raise ChatError("Rang #rrggbb ko'rinishida bo'lishi kerak")
    return raw.lower()


def update_profile(user, nickname: str | None = None, bio: str | None = None, color: str | None = None) -> dict:
    """Nickname, bio va/yoki rangni yangilaydi (None = o'zgartirilmaydi)."""
    new_nick = clean_nickname(nickname) if nickname is not None else None
    new_bio = clean_bio(bio) if bio is not None else None
    new_color = clean_color(user, color) if color is not None else None
    if new_nick is not None:
        users.set_nickname(user["id"], new_nick)
    if new_bio is not None:
        users.set_bio(user["id"], new_bio)
    if color is not None:
        users.set_color(user["id"], new_color)
    return views.user_view(user["id"])


def change_password(user, old: str, new: str, keep_token_hash: str, key_blob: str | None = None,
                    kdf_iter: int | None = None) -> None:
    """E2EE akkaunt: `old`/`new` — mijoz hosil qilgan kirish kalitlari; maxfiy kalitlar yangi parol bilan QAYTA O'RALADI
    (`key_blob`). Shu sababli parolni faqat brauzer (profil sozlamalari) almashtira oladi."""
    if not verify_password(old, user["password_hash"]):
        raise ChatError("Eski parol noto'g'ri")
    if int(user["auth_v"] or 0) == 1:
        if key_blob is None or kdf_iter is None:
            raise ChatError("E2EE akkauntda parolni faqat profil sozlamalaridan almashtirish mumkin (kalitlar qayta o'raladi)")
        keys = e2ee_svc.validate_account_keys({"ecdh_pub": user["ecdh_pub"], "sign_pub": user["sign_pub"],
                                                "key_blob": key_blob, "kdf_iter": kdf_iter})
        users.set_key_blob(user["id"], hash_password(e2ee_svc.check_auth(new)), keys["key_blob"], keys["kdf_iter"])
    else:
        _check_password(new)
        users.set_password(user["id"], hash_password(new))
    sessions.delete_for_user(user["id"], keep=keep_token_hash)
