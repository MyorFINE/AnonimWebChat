"""Shikoyatlar: foydalanuvchi umumiy chatdagi xabarga shikoyat qiladi, adminlar ko'rib chiqadi."""
import re
import time

from app.errors import ChatError
from app.repositories import messages, reports, users
from app.security import limiter

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_REASON = 200
ACTIONS = {"dismiss": "Rad etildi", "delete": "Xabar o'chirildi", "done": "Hal qilindi"}


MAX_EVIDENCE = 1000


def create(user, mid, reason: str = "", evidence: str = "") -> int:
    """E2EE chatda server xabarni o'qiy olmaydi. Shuning uchun shikoyatchi XOHLASA o'sha BITTA xabar matnini adminlarga
    ochib beradi (`evidence`); admin buni o'z qurilmasida asl shifrlangan xabar bilan solishtirib tekshiradi."""
    if not isinstance(mid, int) or isinstance(mid, bool):
        raise ChatError("Xabar topilmadi", 404)
    m = messages.get_active(mid)
    if not m or m["recipient_id"] is not None:
        raise ChatError("Faqat umumiy chatdagi xabarga shikoyat qilish mumkin")
    if m["user_id"] == user["id"]:
        raise ChatError("O'z xabaringizga shikoyat qila olmaysiz")
    if reports.exists(mid, user["id"]):
        raise ChatError("Bu xabarga allaqachon shikoyat qilgansiz")
    limiter.check(f"rep:{user['id']}", 5, 60, "Juda ko'p shikoyat. Biroz kuting")
    reason = _CTRL.sub("", reason or "").strip()[:MAX_REASON]
    if m["e2e"]:
        evidence = _CTRL.sub("", evidence or "").strip()[:MAX_EVIDENCE] if isinstance(evidence, str) else ""
        return reports.create(mid, user["id"], m["user_id"], reason, evidence, time.time(), envelope=m["content"])
    snap = (m["content"] or "") or ("[fayl]" if m["image"] or m["file"] else "")
    return reports.create(mid, user["id"], m["user_id"], reason, snap, time.time())


def listing(status: str = "open", before: int = 0, limit: int = 50) -> dict:
    items = []
    for r in reports.listing(status, max(0, before), max(1, min(limit, 100))):
        rep, tgt = users.get(r["reporter_id"]), users.get(r["target_id"])
        by = users.get(r["handled_by"]) if r["handled_by"] else None
        live = messages.get_active(r["message_id"])
        items.append({
            "id": r["id"], "ts": r["created_at"], "message_id": r["message_id"], "status": r["status"],
            "reporter": rep["username"] if rep else "?", "target": tgt["username"] if tgt else "?",
            "target_nick": tgt["nickname"] if tgt else "", "target_id": r["target_id"],
            "reason": r["reason"], "text": r["snapshot"], "alive": live is not None,
            "cipher": r["envelope"], "disclosed": bool(r["envelope"]),
            "action": ACTIONS.get(r["action"] or "", ""), "by": by["username"] if by else "",
        })
    return {"items": items, "open": reports.open_count(), "next": items[-1]["id"] if len(items) >= limit else 0}
