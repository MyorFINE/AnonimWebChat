"""Admin: media boshqaruvi. Faqat UMUMIY chatdagi fayllar ko'rinadi; lichka fayllari bu yerga tushmaydi.

Maxfiylik: bu yerda fayl NOMI va MAZMUNI ochilmaydi — faqat tur, hajm, vaqt va yuboruvchi. Fayllar diskda shifrlangan.
"""
from app.errors import ChatError
from app.repositories import messages
from app.services import media

MAX_BATCH = 200


def category(r) -> str:
    if r["e2e"]:
        return "e2e"                                    # shifrlangan: server turini ham bilmaydi
    if r["image"]:
        return "image"
    mime = r["file_mime"] or ""
    return "video" if mime.startswith("video/") else "audio" if mime.startswith("audio/") else "other"


def listing(before: int = 0, limit: int = 50, kind: str = "", sender: str = "", min_mb: float = 0) -> dict:
    limit = max(1, min(limit, 100))
    rows = messages.group_media(max(0, before), limit, kind if kind in ("image", "video", "audio", "other") else "",
                                sender.strip()[:30], int(max(0.0, min_mb) * 1024 * 1024))
    items = [{"id": r["id"], "ts": r["created_at"], "username": r["username"], "nickname": r["nickname"],
              "kind": category(r), "size": r["file_size"] or 0} for r in rows]
    return {"items": items, "next": items[-1]["id"] if len(items) >= limit else 0, "totals": messages.media_totals()}


def remove(actor, ids: list[int]):
    """Tanlangan xabarlardan faylni o'chiradi. Matni bo'lmasa xabar ham o'chadi. [(xabar_qatori, xabar_ham_o'chdimi)]."""
    done = []
    for mid in list(dict.fromkeys(i for i in ids if isinstance(i, int) and not isinstance(i, bool)))[:MAX_BATCH]:
        row = messages.get_active(mid)
        if not row or row["recipient_id"] is not None or not (row["image"] or row["file"]):
            continue                                        # lichka yoki fayli yo'q xabarga tegilmaydi
        media.remove_row(row)
        gone = bool(row["e2e"]) or not (row["content"] or "").strip()     # E2EE xabarda izoh bor-yo'qligi noma'lum: butun xabar o'chadi
        if gone:
            messages.mark_deleted(mid)
        else:
            messages.clear_media(mid)
        done.append((row, gone))
    if not done and ids:
        raise ChatError("O'chiriladigan media topilmadi")
    return done
