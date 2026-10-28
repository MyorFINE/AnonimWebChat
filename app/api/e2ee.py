"""E2EE endpointlari: kalitlar, guruh kaliti avlodlari, shifrlangan fayllar va "server nimani ko'radi" inspektori.

Bu yerda hech qachon ochiq matn, guruh kaliti yoki maxfiy kalit ishlatilmaydi — server faqat shifrlangan ma'lumotni saqlaydi/uzatadi.
"""
import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import current_user
from app.config import settings
from app.errors import ChatError
from app.realtime.manager import manager
from app.repositories import e2ee as repo
from app.security import limiter
from app.services import e2ee as svc
from app.services import media, views

router = APIRouter(prefix="/api/e2ee", tags=["e2ee"])


class SetupIn(BaseModel):
    old: str = Field(max_length=128)                 # eski parol (bir martalik tekshiruv uchun; shundan keyin server uni bilmaydi)
    auth: str = Field(max_length=128)                # yangi kirish kaliti (hex)
    keys: dict


class WrapItem(BaseModel):
    user_id: int
    wrapped: str = Field(max_length=200)


class InitIn(BaseModel):
    check: str = Field(max_length=400)
    wraps: list[WrapItem] = Field(max_length=svc.MAX_WRAPS)


class RotateIn(InitIn):
    from_epoch: int
    reason: str = Field("rotate", max_length=20)


class WrapIn(BaseModel):
    epoch: int
    wraps: list[WrapItem] = Field(max_length=200)


def _wraps(items) -> list[dict]:
    return [{"user_id": w.user_id, "wrapped": w.wrapped} for w in items]


# `def` (async emas): scrypt CPU'ni band qiladi
@router.post("/setup")
def setup(data: SetupIn, user=Depends(current_user)):
    """Eski akkauntni E2EE'ga o'tkazish (bir marta): kalitlar brauzerda yaratilgan, parol hash'i endi brauzer kalitidan."""
    limiter.check(f"e2e-setup:{user['id']}", 5, 300, "Juda ko'p urinish")
    svc.upgrade_legacy(user, data.old, data.auth, data.keys)
    return {"ok": True}


@router.get("/keys")
def keys(ids: str = "", user=Depends(current_user)):
    """Foydalanuvchilarning OMMAVIY kalitlari (id'lar vergul bilan)."""
    want = [int(x) for x in ids.split(",")[:300] if x.strip().isdigit()]
    return {"keys": svc.public_keys(want)}


@router.get("/room")
def room(user=Depends(current_user)):
    return svc.room_state(user)


@router.post("/room/init")
async def room_init(data: InitIn, user=Depends(current_user)):
    ep = svc.room_init(user, data.check, _wraps(data.wraps))
    await manager.broadcast({"type": "e2ee_room", "epoch": ep})
    return {"ok": True, "epoch": ep}


@router.post("/room/rotate")
async def room_rotate(data: RotateIn, user=Depends(current_user)):
    ep = svc.room_rotate(user, data.from_epoch, data.check, _wraps(data.wraps), data.reason)
    await manager.broadcast({"type": "e2ee_room", "epoch": ep})
    return {"ok": True, "epoch": ep}


@router.post("/room/wrap")
async def room_wrap(data: WrapIn, user=Depends(current_user)):
    added = svc.room_wrap(user, data.epoch, _wraps(data.wraps))
    if added:
        await manager.send_many(added, {"type": "e2ee_wrap", "epoch": data.epoch})
    return {"ok": True, "added": len(added)}


@router.get("/room/missing")
def room_missing(user=Depends(current_user)):
    return {"missing": svc.room_missing()}


@router.delete("/room/wrap/{epoch}")
def drop_wrap(epoch: int, user=Depends(current_user)):
    """Noto'g'ri (tekshiruvdan o'tmagan) o'ralgan kalitni o'chirish: boshqa a'zo qayta o'rab beradi."""
    limiter.check(f"e2e-drop:{user['id']}", 10, 60, "Juda tez-tez so'raldi")
    svc.drop_own_wrap(user, epoch)
    return {"ok": True}


@router.get("/server-view")
def server_view(to: int | None = None, limit: int = 8, user=Depends(current_user)):
    """Inspektor: joriy suhbat bo'yicha serverda AYNAN nima yotgani (shifrlangan, o'zgartirilmagan) va admin nimani ko'rishi."""
    limiter.check(f"e2e-view:{user['id']}", 30, 60, "Juda tez-tez so'raldi")
    return svc.server_view(user, to, limit)


_uploads = 0


@router.post("/blob")
async def upload_blob(request: Request, user=Depends(current_user)):
    """Shifrlangan fayl baytlarini (iv | AES-GCM) qabul qiladi. Server na nomini, na turini, na mazmunini biladi."""
    global _uploads
    left = views.mute_left(user)
    if left > 0:
        raise ChatError("Siz mute holatidasiz")
    if not user["ecdh_pub"]:
        raise ChatError("Avval E2EE kalitlaringiz yaratilishi kerak", 409)
    limiter.check(f"e2e-blob:{user['id']}", 20, 60, "Juda ko'p fayl yuklandi, biroz kuting")
    raw = await request.body()
    name = media.store_opaque(raw)
    repo.add_blob(name, user["id"], len(raw))
    _uploads += 1
    if _uploads % 20 == 0:                                   # biriktirilmagan eski yuklamalarni tozalash
        for r in repo.stale_blobs(time.time() - 3600):
            media.remove(r["name"])
            repo.drop_blob(r["name"])
    return {"blob": name, "size": len(raw)}
