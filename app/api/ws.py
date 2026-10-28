"""Chat WebSocket: /ws?k=<kid>. Barcha kadrlar shifrlangan (app.transport.SecureWS).

Birinchi kadr (mijoz -> server): {"a": "<token>"}; keyin quyidagi xabarlar:

Mijoz -> server (JSON):
  {"type": "send",   "text": "...", "to": <user_id>?, "reply_to": <message_id>?}   to yo'q bo'lsa umumiy chatga
  {"type": "edit",   "id": 12, "text": "..."}
  {"type": "delete", "id": 12}
  {"type": "delete_many", "ids": [1, 2, 3]}          belgilangan xabarlarni birdaniga o'chirish
  {"type": "delete_dm", "with": <user_id>}           shaxsiy suhbatni ikki tomon uchun o'chirish
  {"type": "clear_chat"}                              umumiy chatni tozalash (faqat admin/ega)
  {"type": "read",   "with": <user_id>}                  shaxsiy suhbatni o'qilgan deb belgilash
  {"type": "cmd",    "text": "/mute user 10"}            moderatsiya (admin tugmalari ishlatadi)
"""
import asyncio
import json
import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.commands import Ctx, dispatch
from app.constants import WS_FORBIDDEN, WS_IP_BLOCKED, WS_REKEY, WS_UNAUTHORIZED
from app.errors import ChatError
from app.netutil import real_ip
from app.realtime.events import deliver, publish_deleted, publish_edited
from app.realtime.manager import manager
from app.security import hash_token
from app.services import activity, auth, chat, ipblock, modsettings, views
from app.transport import SecureWS, store

router = APIRouter()
log = logging.getLogger("termchat.ws")


def _parse(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _snippet(text: str, n: int = 100) -> str:
    return " ".join(text.split())[:n]


async def _handle(user, data: dict, token_hash: str, ip: str) -> None:
    kind = data.get("type") or "send"
    text = data.get("text")
    text = text.strip() if isinstance(text, str) else ""
    try:
        if kind == "send":
            to = _int(data.get("to"))
            if data.get("to") is not None and to is None:
                raise ChatError("Qabul qiluvchi noto'g'ri ko'rsatilgan")
            env = data.get("e2e")
            if isinstance(env, str):                  # E2EE: server faqat shifrlangan konvertni ko'radi
                blob = data.get("blob")
                message = chat.post_e2e(user, env, to, blob if isinstance(blob, str) else None)
                await deliver({"recipient_id": message["to"], "user_id": user["id"]}, message)
                activity.record("msg" if to is None else "dm", ip=ip, user=user)     # matn/mazmun logga YOZILMAYDI
                return
            if not text:
                return
            message = chat.post(user, text, to, _int(data.get("reply_to")))        # E2EE majburiy bo'lsa, bu yerda xato beradi
            row = {"recipient_id": message["to"], "user_id": user["id"]}
            await deliver(row, message)
            if to is None:
                activity.record("msg", ip=ip, user=user, detail=_snippet(text))
            else:                                   # shaxsiy xabar matni va qabul qiluvchisi yozilmaydi
                activity.record("dm", ip=ip, user=user)
        elif kind == "edit":
            env = data.get("e2e")
            if isinstance(env, str):
                msg, new_env = chat.edit_e2e(user, _int(data.get("id")) or 0, env)
                await publish_edited(msg, new_env, e2e=True)
                activity.record("edit", ip=ip, user=user, detail=f"#{msg['id']}" if msg["recipient_id"] is None else "lichkada")
                return
            msg, new_text = chat.edit(user, _int(data.get("id")) or 0, text)
            await publish_edited(msg, new_text)
            if msg["recipient_id"] is None:
                activity.record("edit", ip=ip, user=user,
                                detail=f"#{msg['id']}: {_snippet(msg['content'], 60)} → {_snippet(new_text, 60)}")
            else:
                activity.record("edit", ip=ip, user=user, detail="lichkada")
        elif kind == "delete":
            msg = chat.delete(user, _int(data.get("id")) or 0)
            await publish_deleted(msg)
            if msg["recipient_id"] is None:
                own = msg["user_id"] == user["id"]
                activity.record("delete", ip=ip, user=user,
                                detail=f"#{msg['id']}" + ("" if own else f" (egasi id={msg['user_id']})")
                                + ("" if msg["e2e"] else f": {_snippet(msg['content'], 80)}"))
            else:
                activity.record("delete", ip=ip, user=user, detail="lichkada")
        elif kind == "delete_many":
            raw_ids = data.get("ids")
            if not isinstance(raw_ids, list):
                return
            ids = [i for i in (_int(x) for x in raw_ids[: chat.MAX_BULK_DELETE]) if i]
            done, skipped = chat.delete_many(user, ids)
            for msg in done:
                await publish_deleted(msg)
            if done:
                activity.record("delete", ip=ip, user=user, detail=f"{len(done)} ta xabar birdaniga o'chirildi")
            if skipped:
                await manager.system(user["id"], f"{skipped} ta xabar o'chirilmadi (ruxsat yo'q)", "warn")
        elif kind == "delete_dm":
            partner = _int(data.get("with"))
            if partner is None:
                raise ChatError("Suhbat topilmadi")
            n = chat.delete_dm(user, partner)
            await manager.send_many([user["id"], partner], {"type": "dm_cleared", "a": user["id"], "b": partner})
            activity.record("dm_clear", ip=ip, user=user, detail=f"{n} ta xabar")
        elif kind == "clear_chat":
            n = chat.clear_group(user)
            await manager.broadcast({"type": "chat_cleared", "by": user["id"], "count": n})
            activity.record("clear", ip=ip, user=user, detail=f"umumiy chat tozalandi ({n} ta xabar)")
        elif kind == "read":
            partner = _int(data.get("with"))
            if partner is not None and chat.mark_read(user, partner):
                await manager.send_to(partner, {"type": "read", "by": user["id"]})
        elif kind == "cmd":
            if text.startswith("/"):
                await dispatch(Ctx.parse(user, text[:2000], token_hash, ip))
    except ChatError as e:
        await manager.system(user["id"], e.message, "error")


def _origin_ok(raw: WebSocket) -> bool:
    """Boshqa saytdan WebSocket ochishga urinishni (CSWSH) rad etadi."""
    origin = raw.headers.get("origin")
    if not origin:
        return True                                   # brauzer bo'lmagan mijoz
    host = (raw.headers.get("host") or "").split(":")[0].lower()
    return (urlsplit(origin).hostname or "").lower() == host


@router.websocket("/ws")
async def chat_socket(raw: WebSocket):
    await raw.accept()
    if not _origin_ok(raw):
        return await raw.close(WS_FORBIDDEN)
    ip = real_ip(raw.headers, raw.client)
    if ipblock.is_blocked(ip):
        return await raw.close(WS_IP_BLOCKED)
    sess = store.get(raw.query_params.get("k", ""))
    if sess is None:
        return await raw.close(WS_REKEY)
    ws = SecureWS(raw, sess)
    try:                                              # birinchi shifrlangan kadr: token
        token = str(_parse(await asyncio.wait_for(ws.receive_text(), 10)).get("a") or "")
    except WebSocketDisconnect:
        return
    except Exception:
        return await raw.close(WS_UNAUTHORIZED)
    user = auth.authenticate(token)
    if not user:
        return await raw.close(WS_UNAUTHORIZED)
    if user["banned"]:
        return await raw.close(WS_FORBIDDEN)

    uid, token_hash = user["id"], hash_token(token)
    first = manager.connect(uid, ws, ip)
    if first:
        activity.record("session", ip=ip, user=user)
    try:
        await ws.send_text(json.dumps({"type": "init", "me": views.user_view(uid),
                                       "history": chat.history(), "online_ids": manager.online_ids(),
                                       "chat": modsettings.public()}))
        if first:
            await manager.broadcast({"type": "presence", "uid": uid, "online": True}, exclude_uid=uid)
        while True:
            data = _parse(await ws.receive_text())
            if not data:
                continue
            if ipblock.is_blocked(ip):                   # ulanish ochiq paytda bloklangan bo'lishi mumkin
                await ws.close(WS_IP_BLOCKED)
                break
            user = auth.authenticate(token)              # har safar yangi holat: ban/rol/sessiya
            if not user:
                await ws.close(WS_UNAUTHORIZED)
                break
            if user["banned"]:
                await ws.close(WS_FORBIDDEN)
                break
            await _handle(user, data, token_hash, ip)
    except WebSocketDisconnect:
        pass
    except (ValueError, KeyError):                      # shifr/replay xatosi: ulanishni jimgina uzamiz
        try:
            await raw.close(WS_UNAUTHORIZED)
        except Exception:
            pass
    except Exception:
        log.exception("WebSocket xatosi (uid=%s)", uid)
    finally:
        if manager.disconnect(uid, ws):
            await manager.broadcast({"type": "presence", "uid": uid, "online": False})
