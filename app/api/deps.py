"""Umumiy FastAPI bog'liqliklari."""
from fastapi import Header, Request

from app.errors import ChatError
from app.netutil import real_ip
from app.roles import is_admin
from app.services import auth


def bearer_token(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def client_ip(request: Request) -> str:
    return real_ip(request.headers, request.client)


def current_user(authorization: str | None = Header(None)):
    user = auth.authenticate(bearer_token(authorization))
    if not user or user["banned"]:
        raise ChatError("Avtorizatsiya kerak", 401)
    return user


def admin_user(authorization: str | None = Header(None)):
    user = current_user(authorization)
    if not is_admin(user):
        raise ChatError("Bu bo'lim faqat adminlar uchun", 403)
    return user
