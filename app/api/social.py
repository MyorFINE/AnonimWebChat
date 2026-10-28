"""A'zolar, shaxsiy suhbatlar va profil endpointlari."""
from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api.deps import bearer_token, client_ip, current_user
from app.config import settings
from app.errors import ChatError
from app.realtime.events import deliver, publish_rotate_hint, publish_user_removed
from app.repositories import users as users_repo
from app.realtime.manager import manager
from app.security import hash_token
from app.services import accounts, activity, auth, badges, chat, directory, reports, views

router = APIRouter(prefix="/api", tags=["social"])


class ProfileIn(BaseModel):
    nickname: str | None = Field(None, max_length=64)
    bio: str | None = Field(None, max_length=500)
    color: str | None = Field(None, max_length=16)       # "#rrggbb" yoki "" (standart) — faqat ega/adminlar
    badge: str | None = Field(None, max_length=16)       # emoji nishon ("" = galochka, "none" = yashirish) — faqat ega/adminlar
    badge_anim: str | None = Field(None, max_length=16)  # nishon animatsiyasi


class PasswordIn(BaseModel):
    old: str = Field(max_length=128)
    new: str = Field(max_length=128)
    key_blob: str | None = Field(None, max_length=4096)     # E2EE: yangi parol bilan qayta o'ralgan maxfiy kalitlar
    kdf_iter: int | None = None


class AccountDeleteIn(BaseModel):
    password: str = Field(max_length=128)


@router.post("/account/delete")
async def delete_account(data: AccountDeleteIn, request: Request, user=Depends(current_user)):
    ip = client_ip(request)
    accounts.delete_self(user, data.password)
    activity.record("leave", ip=ip, user=user)
    await publish_user_removed(user["id"])
    await publish_rotate_hint("leave")
    return {"ok": True}


@router.get("/members")
def members(user=Depends(current_user)):
    return {"members": directory.members(user), "online_ids": manager.online_ids()}


@router.get("/dialogs")
def dialogs(user=Depends(current_user)):
    return {"dialogs": chat.dialogs(user)}


@router.get("/dm/{partner_id}")
def dm_history(partner_id: int, user=Depends(current_user)):
    return {"history": chat.dm_history(user, partner_id)}


class ReportIn(BaseModel):
    message_id: int
    reason: str = Field("", max_length=200)
    evidence: str = Field("", max_length=1200)              # E2EE: shikoyatchi O'ZI ochib bergan xabar matni (ixtiyoriy)


@router.post("/report")
async def report_message(data: ReportIn, request: Request, user=Depends(current_user)):
    """Umumiy chatdagi xabarga shikoyat. Adminlarga real vaqtda xabar beriladi."""
    rid = reports.create(user, data.message_id, data.reason, data.evidence)
    activity.record("report", ip=client_ip(request), user=user, detail=f"#{data.message_id}")
    await manager.send_many(users_repo.staff_ids(), {"type": "report_new", "id": rid})
    return {"ok": True}


@router.patch("/profile")
async def update_profile(data: ProfileIn, request: Request, user=Depends(current_user)):
    has_badge = data.badge is not None or data.badge_anim is not None
    if data.nickname is None and data.bio is None and data.color is None and not has_badge:
        raise ChatError("O'zgartirish uchun ma'lumot yo'q")
    if data.nickname is not None or data.bio is not None or data.color is not None:
        view = auth.update_profile(user, data.nickname, data.bio, data.color)
    if has_badge:
        badges.set_for(user, user["id"], data.badge, data.badge_anim)
    view = views.user_view(user["id"])
    await manager.broadcast({"type": "user_update", "user": view})
    ip = client_ip(request)
    if has_badge:
        activity.record("badge", ip=ip, user=user, detail=(view["badge"] or "standart"))
    if data.color is not None:
        activity.record("color", ip=ip, user=user, detail=view["color"] or "standart")
    if data.nickname is not None or data.bio is not None:
        activity.record("profile", ip=ip, user=user, detail=f"nickname={view['nickname']}")
    return {"me": view}


@router.post("/messages/media")
@router.post("/messages/image")                      # eski nom (mosligi uchun)
async def send_media(request: Request, file: UploadFile = File(...), caption: str = Form(""),
                     to: int | None = Form(None), reply_to: int | None = Form(None),
                     user=Depends(current_user)):
    """Istalgan turdagi fayl (50 MB gacha) + ixtiyoriy izoh. `to` — lichka, `reply_to` — javob berilayotgan xabar id."""
    raw = await file.read(settings.max_media_bytes + 1)
    message = await run_in_threadpool(chat.post_media, user, raw, file.filename or "", file.content_type or "",
                                      caption, to, reply_to)
    await deliver({"recipient_id": message["to"], "user_id": user["id"]}, message)
    # Fayl nomi va mazmuni logga YOZILMAYDI; faqat umumiy chatdagi izoh (lichkada hech narsa).
    activity.record("file" if message["file"] else "image", ip=client_ip(request), user=user,
                    detail=None if to is not None else (caption.strip()[:80] or None))
    return {"ok": True, "id": message["id"]}


# `def`: scrypt CPU'ni band qiladi, thread pool'da bajariladi
@router.post("/password")
def change_password(data: PasswordIn, request: Request, user=Depends(current_user),
                    authorization: str | None = Header(None)):
    auth.change_password(user, data.old, data.new, hash_token(bearer_token(authorization)), data.key_blob, data.kdf_iter)
    activity.record("password", ip=client_ip(request), user=user)
    return {"ok": True}
