import time

from app import crypto
from app.db import db

OLD, NEW = "log-old", "log-new"


def add(type_: str, *, message_id=None, user_id=None, actor_id=None, old=None, new=None) -> None:
    db.run(
        "INSERT INTO logs(type,message_id,user_id,actor_id,old_content,new_content,created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (type_, message_id, user_id, actor_id, crypto.seal(old, OLD), crypto.seal(new, NEW), time.time()),
    )


def _dec(r) -> dict:
    """Adminlar uchun: xabar tahrir/o'chirish yozuvlari FAQAT shifrlangan ko'rinishda (E2EE konvert yoki server shifri).
    Boshqa turdagi yozuvlar (mute, ban...) — oddiy xizmat matni, ular ochiladi."""
    d = dict(r)
    if d["type"] in ("edit", "delete"):
        d["old_content"] = crypto.admin_view(d["old_content"], OLD)
        d["new_content"] = crypto.admin_view(d["new_content"], NEW)
    else:
        d["old_content"] = crypto.open_(d["old_content"], OLD)
        d["new_content"] = crypto.open_(d["new_content"], NEW)
    return d


def recent(limit: int):
    return [_dec(r) for r in db.all("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))[::-1]]


def for_messages(ids: list[int]) -> list[dict]:
    """Berilgan xabarlarning tahrir/o'chirish tarixi (shifrdan ochilgan), eskisi birinchi."""
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = db.all(f"SELECT * FROM logs WHERE message_id IN ({marks}) ORDER BY id", tuple(ids))
    return [_dec(r) for r in rows]


def clear_all() -> int:
    """Tahrir/o'chirish/moderatsiya tarixini (logs jadvali) butunlay o'chiradi."""
    with db._lock:
        cur = db._conn.execute("DELETE FROM logs")
        db._conn.commit()
        return cur.rowcount
