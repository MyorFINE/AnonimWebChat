"""Admin paneli: harakatlar logi, IP jamlanmalari, IP bloklash. Faqat ega va adminlar."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import admin_user, client_ip
from app.config import settings
from app.constants import WS_IP_BLOCKED
from app.errors import ChatError
from app.realtime.events import publish_deleted
from app.realtime.manager import manager
from app import crypto, e2ee as envelope_fmt
from app.repositories import activity as repo
from app.repositories import e2ee as e2ee_repo
from app.services import e2ee as e2ee_svc
from app.repositories import logs as logs_repo
from app.repositories import messages as messages_repo
from app.repositories import reports as reports_repo
from app.repositories import users as users_repo
from app.roles import Role, role_of
from app.services import activity, badges, chat, ipblock, mediamgr, modsettings, reports, views
import time

router = APIRouter(prefix="/api/admin", tags=["admin"])


class BlockIn(BaseModel):
    ip: str = Field(max_length=64)
    reason: str = Field("", max_length=200)


class UnblockIn(BaseModel):
    ip: str = Field(max_length=64)


@router.get("/ips")
def ips(q: str = "", user=Depends(admin_user)):
    """IP'lar bo'yicha: har bir IP'dan qaysi profillar (username) necha marta kirgan va nima qilgan."""
    by_ip: dict[str, dict] = {}
    for r in repo.ip_profiles(q.strip()[:60]):
        e = by_ip.setdefault(r["ip"], {
            "ip": r["ip"], "logins": 0, "sessions": 0, "msgs": 0, "failed": 0,
            "first_seen": r["first_seen"], "last_seen": r["last_seen"], "profiles": [],
            "blocked": ipblock.is_blocked(r["ip"]),
        })
        e["logins"] += r["logins"] or 0
        e["sessions"] += r["sessions"] or 0
        e["msgs"] += r["msgs"] or 0
        e["failed"] += r["failed"] or 0
        e["first_seen"] = min(e["first_seen"], r["first_seen"])
        e["last_seen"] = max(e["last_seen"], r["last_seen"])
        e["profiles"].append({
            "user_id": r["user_id"], "username": r["username"] or "?", "nickname": r["nickname"],
            "known": r["user_id"] is not None, "logins": r["logins"] or 0, "sessions": r["sessions"] or 0,
            "msgs": r["msgs"] or 0, "failed": r["failed"] or 0, "last_seen": r["last_seen"],
        })
    rows = sorted(by_ip.values(), key=lambda e: e["last_seen"], reverse=True)
    return {"ips": rows[:300]}


@router.get("/activity")
def activity_log(ip: str = "", user: str = "", action: str = "", before: int = 0, limit: int = 100,
                 admin=Depends(admin_user)):
    rows = repo.query(ip=ip.strip()[:60], user=user.strip()[:30], action=action.strip()[:20],
                      before=max(0, before), limit=max(1, min(limit, 200)))
    return {
        "items": [{"id": r["id"], "ts": r["created_at"], "ip": r["ip"] or "", "username": r["username"] or "",
                   "action": r["action"], "label": activity.ACTIONS.get(r["action"], r["action"]),
                   "detail": e2ee_svc.public_detail(r["action"], r["detail"])} for r in rows],
        "actions": [{"key": k, "label": v} for k, v in activity.ACTIONS.items()],
    }


@router.get("/blocks")
def blocks(admin=Depends(admin_user)):
    return {"blocks": ipblock.listing()}


@router.post("/blocks")
async def block(data: BlockIn, request: Request, admin=Depends(admin_user)):
    ip = ipblock.block(admin, data.ip, data.reason, client_ip(request))
    kicked = await manager.kick_ip(ip, WS_IP_BLOCKED)
    return {"ok": True, "ip": ip, "kicked": kicked}


@router.post("/unblock")
def unblock(data: UnblockIn, request: Request, admin=Depends(admin_user)):
    ip = ipblock.unblock(admin, data.ip, client_ip(request))
    return {"ok": True, "ip": ip}


@router.get("/messages")
def message_log(q: str = "", state: str = "", before: int = 0, limit: int = 50, admin=Depends(admin_user)):
    """Umumiy chatdagi barcha xabarlar (o'chirilgan va tahrirlanganlari ham) — FAQAT SHIFRLANGAN ko'rinishda.

    E2EE: server xabar matnini bilmaydi, shuning uchun adminga ham faqat shifrlangan konvert (`cipher`) va uning ochiq
    metama'lumoti (epoch, hajm) ko'rsatiladi. Eski (E2EE'dan oldingi) xabarlar uchun — bazadagi server shifrining boshi.
    Qidiruv faqat username bo'yicha. Lichka (shaxsiy) xabarlar bu yerga kirmaydi.
    `state`: "" (hammasi) | "deleted" | "edited".
    """
    limit = max(1, min(limit, 100))
    needle = q.strip().lower().lstrip("@")[:60]
    items, cursor, scanned = [], max(0, before), 0
    while len(items) < limit and scanned < 3000:
        page = messages_repo.group_page(cursor, 200)
        if not page:
            cursor = -1
            break
        for r in page:
            cursor = r["id"]
            scanned += 1
            if state == "deleted" and not r["deleted"]:
                continue
            if state == "edited" and not r["edited_at"]:
                continue
            u = users_repo.get(r["user_id"])
            uname = u["username"] if u else "?"
            if needle and needle not in uname.lower():
                continue
            cipher = crypto.admin_view(r["content"])
            items.append({"id": r["id"], "ts": r["created_at"], "username": uname,
                          "nickname": u["nickname"] if u else "", "cipher": cipher,
                          "meta": envelope_fmt.describe(cipher), "legacy": not r["e2e"],
                          "deleted": bool(r["deleted"]), "edited": bool(r["edited_at"]),
                          "file": bool(r["file"] or r["image"]), "file_bytes": r["file_size"] or 0})
            if len(items) >= limit:
                break
    hist: dict[int, list] = {}
    for h in logs_repo.for_messages([i["id"] for i in items]):
        actor = users_repo.get(h["actor_id"]) if h["actor_id"] else None
        hist.setdefault(h["message_id"], []).append({
            "type": h["type"], "ts": h["created_at"], "by": actor["username"] if actor else "",
            "old": h["old_content"] or "", "new": h["new_content"] or ""})
    for i in items:
        i["history"] = hist.get(i["id"], [])
    return {"items": items, "next": cursor if cursor > 0 else 0}


@router.get("/e2ee")
def e2ee_status(admin=Depends(admin_user)):
    """E2EE holati: guruh kaliti avlodi, eski (server o'qiy oladigan) xabarlar soni, kalitsiz foydalanuvchilar."""
    return {"epoch": e2ee_repo.current_epoch(), "legacy_messages": messages_repo.legacy_count(),
            "keyed_users": len(users_repo.keyed_active()), "require_e2ee": settings.require_e2ee}


@router.post("/e2ee/purge-legacy")
async def purge_legacy(request: Request, admin=Depends(admin_user)):
    """Faqat ega: server o'qiy oladigan eski xabarlarni butunlay o'chirish (qaytarib bo'lmaydi)."""
    n = chat.purge_legacy(admin)
    activity.record("clear", ip=client_ip(request), user=admin, detail=f"eski (E2EE bo'lmagan) xabarlar: {n} ta")
    await manager.broadcast({"type": "members_changed"})
    return {"ok": True, "deleted": n}


# ------------------------------------------------------------------------------------------- loglarni o'chirish
class LogDeleteIn(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=1000)
    all: bool = False                       # True: ip/user/action filtriga mos HAMMASINI (filtr bo'sh bo'lsa — butun logni)
    ip: str = Field("", max_length=60)
    user: str = Field("", max_length=30)
    action: str = Field("", max_length=20)


@router.post("/activity/delete")
def delete_activity(data: LogDeleteIn, request: Request, admin=Depends(admin_user)):
    """Harakatlar logini o'chirish (tanlanganlar yoki filtr bo'yicha hammasi). Eganing harakatlarini faqat ega o'chira oladi."""
    keep_owner = role_of(admin) != Role.OWNER
    if data.ids:
        n = repo.delete_ids(data.ids, keep_owner=keep_owner)
    elif data.all:
        n = repo.delete_matching(data.ip.strip(), data.user.strip(), data.action.strip(), keep_owner=keep_owner)
    else:
        raise ChatError("O'chiriladigan yozuvlar tanlanmagan")
    activity.record("log_clear", ip=client_ip(request), user=admin, detail=f"{n} ta yozuv")     # faqat son, mazmun yo'q
    return {"ok": True, "deleted": n}


@router.post("/messages/clean")
def clean_message_log(request: Request, admin=Depends(admin_user)):
    """Xabarlar logini tozalash: o'chirilgan umumiy chat xabarlari bazadan butunlay o'chadi, tahrir/moderatsiya tarixi tozalanadi."""
    gone = messages_repo.purge_deleted_group()
    hist = logs_repo.clear_all()
    activity.record("log_clear", ip=client_ip(request), user=admin, detail=f"xabarlar logi: {gone} ta xabar, {hist} ta tarix")
    return {"ok": True, "messages": gone, "history": hist}


# ------------------------------------------------------------------------------------------- media boshqaruvi
class MediaDeleteIn(BaseModel):
    ids: list[int] = Field(max_length=mediamgr.MAX_BATCH)


@router.get("/media")
def media_list(before: int = 0, limit: int = 50, kind: str = "", sender: str = "", min_mb: float = 0,
               admin=Depends(admin_user)):
    """Umumiy chatdagi fayllar: faqat tur, hajm, vaqt, yuboruvchi (nom va mazmun ochilmaydi, lichka kirmaydi)."""
    return mediamgr.listing(before, limit, kind.strip()[:10], sender, min_mb)


@router.post("/media/delete")
async def media_delete(data: MediaDeleteIn, request: Request, admin=Depends(admin_user)):
    done = mediamgr.remove(admin, data.ids)
    for row, gone in done:
        if gone:
            await publish_deleted(row)                                     # matni yo'q xabar butunlay o'chadi
        else:
            await manager.broadcast({"type": "media_removed", "id": row["id"]})
    # Logga faqat son yoziladi: qaysi fayl/kimniki ekani YOZILMAYDI.
    activity.record("media_clear", ip=client_ip(request), user=admin, detail=f"{len(done)} ta fayl")
    return {"ok": True, "deleted": len(done)}


# ------------------------------------------------------------------------------------------- moderatsiya sozlamalari
class ModSettingsIn(BaseModel):
    slowmode: int | None = Field(None, ge=0, le=modsettings.MAX_SLOWMODE)
    locked: bool | None = None
    words: list[str] | None = Field(None, max_length=modsettings.MAX_WORDS)


@router.get("/modsettings")
def mod_settings(admin=Depends(admin_user)):
    return modsettings.get()


@router.post("/modsettings")
async def set_mod_settings(data: ModSettingsIn, request: Request, admin=Depends(admin_user)):
    if data.slowmode is None and data.locked is None and data.words is None:
        raise ChatError("O'zgartirish uchun ma'lumot yo'q")
    if data.slowmode is not None:
        modsettings.set_slowmode(admin, data.slowmode)
    if data.locked is not None:
        modsettings.set_locked(admin, data.locked)
    if data.words is not None:
        modsettings.set_words(admin, data.words)
    await manager.broadcast({"type": "chat_settings", **modsettings.public()})
    activity.record("mod", ip=client_ip(request), user=admin, detail="chat sozlamalari o'zgartirildi")
    return modsettings.get()


# ------------------------------------------------------------------------------------------- shikoyatlar
class ReportCloseIn(BaseModel):
    id: int
    action: str = Field("done", max_length=10)             # dismiss | delete | done


@router.get("/reports")
def report_list(status: str = "open", before: int = 0, limit: int = 50, admin=Depends(admin_user)):
    return reports.listing(status.strip()[:10], before, limit)


@router.post("/reports/close")
async def report_close(data: ReportCloseIn, request: Request, admin=Depends(admin_user)):
    r = reports_repo.get(data.id)
    if not r:
        raise ChatError("Shikoyat topilmadi", 404)
    if r["status"] == "closed":
        raise ChatError("Bu shikoyat allaqachon ko'rib chiqilgan")
    if data.action not in reports.ACTIONS:
        raise ChatError("Noma'lum amal")
    if data.action == "delete" and messages_repo.get_active(r["message_id"]):
        msg = chat.delete(admin, r["message_id"])               # ruxsat bo'lmasa (masalan, admin xabari) xato qaytadi
        await publish_deleted(msg)
        activity.record("delete", ip=client_ip(request), user=admin, detail=f"shikoyat bo'yicha #{msg['id']}")
    if data.action == "delete":
        reports_repo.close_for_message(r["message_id"], admin["id"], "delete", time.time())
    else:
        reports_repo.close(r["id"], admin["id"], data.action, time.time())
    return {"ok": True, "open": reports_repo.open_count()}


# ------------------------------------------------------------------------------------------- nishon (emoji)
class BadgeIn(BaseModel):
    user_id: int
    badge: str = Field("", max_length=16)
    anim: str = Field("", max_length=16)


@router.post("/badge")
async def set_badge(data: BadgeIn, request: Request, admin=Depends(admin_user)):
    """Foydalanuvchiga (yoki o'zingizga) emoji nishon berish/olish. Bo'sh badge — nishonni olib tashlash/galochka."""
    t = badges.set_for(admin, data.user_id, data.badge, data.anim)
    view = views.user_view(t["id"])
    await manager.broadcast({"type": "user_update", "user": view})
    activity.record("badge", ip=client_ip(request), user=admin, detail=f"@{t['username']}: {view['badge'] or 'olib tashlandi'}")
    return {"ok": True, "user": view}
