"""Autentifikatsiya endpointlari."""
from fastapi import APIRouter, Depends, Header, Request

from app.api.deps import bearer_token, client_ip, current_user
from app.config import settings
from app.errors import ChatError
from app.repositories import users
from app.schemas import KdfIn, LoginIn, RegisterIn
from app.security import limiter
from app.services import activity, auth, views
from app.services import e2ee as e2ee_svc


def _session(token: str, me: dict) -> dict:
    u = users.get(me["id"])
    return {"token": token, "me": me, "e2ee": e2ee_svc.own_info(u), "upgrade": int(u["auth_v"] or 0) == 0}

router = APIRouter(prefix="/api", tags=["auth"])


# `def` (async emas): scrypt CPU'ni band qiladi, shuning uchun thread pool'da bajariladi.
@router.post("/register")
def register(data: RegisterIn, request: Request):
    ip = client_ip(request)
    limiter.check(f"reg:{ip}", settings.register_attempts, settings.register_window,
                  "Juda ko'p urinish, keyinroq qayta urinib ko'ring")
    token, me = auth.register(data.username, data.nickname, data.password, data.e2ee)
    activity.record("register", ip=ip, user=users.get(me["id"]))
    return _session(token, me)


@router.post("/login")
def login(data: LoginIn, request: Request):
    ip = client_ip(request)
    key = f"login:{ip}:{data.username.strip().lower()}"
    try:
        limiter.check(key, settings.login_attempts, settings.login_window,
                      "Juda ko'p noto'g'ri urinish. Bir necha daqiqadan so'ng qayta urining")
        token, me = auth.login(data.username, data.password)
    except ChatError as e:
        known = users.get_by_username(data.username)
        activity.record("login_failed", ip=ip, user=known, username=data.username.strip()[:30], detail=e.message)
        raise
    activity.record("login", ip=ip, user=users.get(me["id"]))
    return _session(token, me)


@router.post("/kdf")
def kdf(data: KdfIn, request: Request):
    """Kirishdan oldin: brauzer parolni qaysi usulda (E2EE kirish kaliti yoki eski) va necha iteratsiyada qayta ishlashini bilishi kerak."""
    limiter.check(f"kdf:{client_ip(request)}", 60, 60, "Juda tez-tez so'raldi")
    return e2ee_svc.kdf_params(data.username)


@router.get("/username/{name}")
def username_check(name: str, request: Request):
    """Ro'yxatdan o'tishda username bandligini (katta-kichik harfsiz) ko'rsatish uchun."""
    limiter.check(f"uname:{client_ip(request)}", 60, 60, "Juda tez-tez so'raldi")
    ok, reason = auth.username_status(name)
    return {"available": ok, "reason": reason}


@router.post("/logout")
def logout(request: Request, authorization: str | None = Header(None)):
    token = bearer_token(authorization)
    user = auth.authenticate(token)
    if user:
        activity.record("logout", ip=client_ip(request), user=user)
    auth.logout(token)
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    return {"me": views.user_view(user["id"]), "e2ee": e2ee_svc.own_info(user), "upgrade": int(user["auth_v"] or 0) == 0}
