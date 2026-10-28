"""Xabar hodisalarini to'g'ri auditoriyaga yuborish (umumiy chat -> hamma, shaxsiy -> faqat ikki ishtirokchi)."""
from app.realtime.manager import manager
from app.services import chat


async def deliver(msg_row, payload: dict) -> None:
    aud = chat.audience(msg_row)
    if aud is None:
        await manager.broadcast(payload)
    else:
        await manager.send_many(aud, payload)


async def publish_edited(msg_row, new_text: str, e2e: bool = False) -> None:
    """`e2e=True`: `new_text` — yangi shifrlangan konvert (server mazmunini bilmaydi)."""
    await deliver(msg_row, {"type": "message_edited", "id": msg_row["id"], "to": msg_row["recipient_id"],
                            "from": msg_row["user_id"], ("e2e" if e2e else "content"): new_text})


async def publish_rotate_hint(reason: str) -> None:
    """Ban/akkaunt o'chirilganda adminlar mijozlariga: guruh kalitini yangilash vaqti (server kalitni o'zi yarata olmaydi)."""
    from app.repositories import users
    await manager.send_many(users.staff_ids(), {"type": "e2ee_rotate_hint", "reason": reason})


async def publish_deleted(msg_row) -> None:
    await deliver(msg_row, {"type": "message_deleted", "id": msg_row["id"], "to": msg_row["recipient_id"],
                            "from": msg_row["user_id"]})


async def publish_user_removed(uid: int) -> None:
    """Akkaunt o'chirilganda: egasini chiqarib yuboradi, boshqalarga "Deleted account" holatini yuboradi."""
    from app.constants import WS_UNAUTHORIZED
    from app.services import views
    await manager.send_to(uid, {"type": "account_removed"})
    await manager.kick(uid, WS_UNAUTHORIZED)
    await manager.broadcast({"type": "user_removed", "user": views.user_view(uid)})
    await manager.broadcast({"type": "members_changed"})
