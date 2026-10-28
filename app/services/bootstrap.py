"""Ishga tushganda: platforma egasi @Hevorix mavjudligini ta'minlaydi."""
import logging
import secrets
import time

from app.config import settings
from app.constants import OWNER_USERNAME
from app.repositories import users
from app.roles import Role
from app.security import hash_password, verify_password

log = logging.getLogger("termchat.bootstrap")


def ensure_owner() -> None:
    """@Hevorix doim mavjud va ega bo'ladi.

    - Parol TERMCHAT_ADMIN_PASSWORD dan olinadi (o'zgartirsangiz, keyingi ishga tushirishda yangilanadi).
    - U berilmagan va foydalanuvchi hali yo'q bo'lsa, tasodifiy parol yaratilib, logga BIR MARTA yoziladi.
    """
    env_pw = settings.admin_password
    if env_pw and len(env_pw) < 6:
        log.error("TERMCHAT_ADMIN_PASSWORD kamida 6 belgi bo'lishi kerak — e'tiborga olinmadi")
        env_pw = ""

    user = users.get_by_username(OWNER_USERNAME)
    if user is None:
        generated = not env_pw
        password = env_pw or secrets.token_urlsafe(9)
        users.create(OWNER_USERNAME, OWNER_USERNAME, hash_password(password), Role.OWNER.db_name, time.time())
        if generated:
            log.warning("=" * 60)
            log.warning("Ega yaratildi: username=%s  parol=%s", OWNER_USERNAME, password)
            log.warning("Kirgach parolni profil sozlamalarida almashtiring (yoki TERMCHAT_ADMIN_PASSWORD bering).")
            log.warning("=" * 60)
        else:
            log.info("Ega yaratildi: %s", OWNER_USERNAME)
        return

    if user["role"] != Role.OWNER.db_name:
        users.set_role(user["id"], Role.OWNER.db_name)
        log.info("%s egalik huquqiga qaytarildi", OWNER_USERNAME)
    if env_pw and int(user["auth_v"] or 0) == 1:
        pass                      # E2EE akkaunt: parol hash'i brauzer hosil qilgan kalitdan; env paroli bilan solishtirib bo'lmaydi
    elif env_pw and not verify_password(env_pw, user["password_hash"]):
        users.set_password(user["id"], hash_password(env_pw))
        log.info("%s paroli TERMCHAT_ADMIN_PASSWORD bo'yicha yangilandi", OWNER_USERNAME)
