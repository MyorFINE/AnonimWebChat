"""Mijozga yuboriladigan JSON ko'rinishlar."""
import time

from app.repositories import messages, users


def _avatar_url(filename):
    return f"/avatars/{filename}" if filename else None


def _ghost(r) -> dict:
    return {"id": r["id"], "username": "", "nickname": "Deleted account", "role": "user", "bio": "",
            "color": None, "joined": None, "avatar": None, "deleted": True, "badge": None, "badge_anim": None}


def user_view(uid: int) -> dict:
    r = users.get_view(uid)
    if r["deleted"]:
        return _ghost(r)
    return {
        "id": r["id"],
        "username": r["username"],
        "nickname": r["nickname"],
        "role": r["role"],
        "bio": r["bio"] or "",
        "color": r["color"],
        "joined": r["created_at"],
        "avatar": _avatar_url(r["avatar"]),
        "badge": r["badge"],
        "badge_anim": r["badge_anim"],
    }


def member_view(r, *, admin_view: bool) -> dict:
    """A'zolar ro'yxati uchun (bitta so'rovdan). Adminga ban/mute holati ham ko'rsatiladi."""
    v = {
        "id": r["id"],
        "username": r["username"],
        "nickname": r["nickname"],
        "role": r["role"],
        "bio": r["bio"] or "",
        "color": r["color"],
        "joined": r["created_at"],
        "avatar": _avatar_url(r["avatar"]),
        "badge": r["badge"],
        "badge_anim": r["badge_anim"],
    }
    v["ek"], v["sk"] = r["ecdh_pub"], r["sign_pub"]          # ommaviy E2EE kalitlari (xabarlarni imzolash/lichka kaliti)
    if admin_view:
        v["banned"] = bool(r["banned"])
        v["muted"] = r["muted_until"] > time.time()
        v["warns"] = r["warns"] or 0
    return v


def reply_view(rid: int | None) -> dict | None:
    """Javob berilgan xabarning qisqa ko'rinishi (o'chirilgan bo'lsa deleted=True)."""
    if rid is None:
        return None
    r = messages.get(rid)
    if not r or r["deleted"]:
        return {"id": rid, "deleted": True}
    author = users.get_view(r["user_id"])
    text = "🔒 shifrlangan xabar" if r["e2e"] else " ".join((r["content"] or "").split())
    return {
        "id": rid,
        "uid": r["user_id"],
        "nickname": author["nickname"] if author else "Noma'lum",
        "text": text[:100],
        "image": bool(r["image"]),
        "file": bool(r["file"]),
        "file_name": r["file_name"] if r["file"] else None,
        "deleted": False,
    }


def _e2e_view(m) -> dict:
    """E2EE xabar: server FAQAT konvertni (shifr) beradi. Matn, javob, fayl nomi/turi — hammasi konvert ichida."""
    to = m["recipient_id"]
    view = {
        "type": "message", "id": m["id"], "user": user_view(m["user_id"]), "to": to,
        "e2e": m["content"], "ts": m["created_at"], "edited": bool(m["edited_at"]),
        "blob": {"url": f"/uploads/{m['file']}", "size": m["file_size"] or 0} if m["file"] else None,
        "image": None, "file": None, "thumb": None, "w": None, "h": None, "reply": None,
    }
    if to is not None:
        view["read"] = bool(m["read"])
    return view


def message_view(m) -> dict:
    if m["e2e"]:
        return _e2e_view(m)
    to = m["recipient_id"]
    view = {
        "legacy": True,
        "type": "message",
        "id": m["id"],
        "user": user_view(m["user_id"]),
        "to": to,
        "content": m["content"],
        "ts": m["created_at"],
        "edited": bool(m["edited_at"]),
        "image": f"/uploads/{m['image']}" if m["image"] else None,
        "file": ({"url": f"/uploads/{m['file']}", "name": m["file_name"] or "fayl", "size": m["file_size"] or 0,
                  "mime": m["file_mime"] or "application/octet-stream"} if m["file"] else None),
        "thumb": f"/uploads/{m['image'].rsplit('.', 1)[0]}_t.jpg" if m["image"] else None,
        "w": m["img_w"] if m["image"] else None,
        "h": m["img_h"] if m["image"] else None,
        "reply": reply_view(m["reply_to"]),
    }
    if to is not None:
        view["read"] = bool(m["read"])
    return view


def mute_left(user) -> float:
    """Mute tugashiga qolgan soniyalar (0 = mute emas)."""
    return max(0.0, user["muted_until"] - time.time())
