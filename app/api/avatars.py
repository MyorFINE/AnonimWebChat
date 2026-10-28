"""Profil rasmlari."""
from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.api.deps import client_ip, current_user
from app.config import settings
from app.realtime.manager import manager
from app.services import activity, avatars, views

router = APIRouter(prefix="/api", tags=["avatars"])


async def _publish(uid: int, request: Request, user, what: str) -> None:
    await manager.broadcast({"type": "user_update", "user": views.user_view(uid)})
    activity.record("avatar", ip=client_ip(request), user=user, detail=what)


@router.get("/avatars")
def list_avatars(user=Depends(current_user)):
    return {"avatars": avatars.gallery(user), "max": settings.max_avatars}


@router.post("/avatar")
async def upload_avatar(request: Request, file: UploadFile = File(...), user=Depends(current_user)):
    raw = await file.read(settings.max_avatar_bytes + 1)
    avatars.upload(user, raw)
    await _publish(user["id"], request, user, "yangi rasm")
    return {"ok": True}


@router.post("/avatars/{avatar_id}/use")
async def use_avatar(avatar_id: int, request: Request, user=Depends(current_user)):
    avatars.activate_id(user, avatar_id)
    await _publish(user["id"], request, user, "faollashtirildi")
    return {"ok": True}


@router.post("/avatar/clear")
async def clear_avatar(request: Request, user=Depends(current_user)):
    avatars.clear_active(user)
    await _publish(user["id"], request, user, "olib tashlandi")
    return {"ok": True}


@router.delete("/avatars/{avatar_id}")
async def delete_avatar(avatar_id: int, request: Request, user=Depends(current_user)):
    avatars.remove_id(user, avatar_id)
    await _publish(user["id"], request, user, "o'chirildi")
    return {"ok": True}
