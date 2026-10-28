"""Foydalanuvchi shikoyatlari. Matn va sabab bazada shifrlangan."""
from app import crypto
from app.db import db

SNAP, WHY = "rep-snap", "rep-why"


def create(message_id: int, reporter_id: int, target_id: int, reason: str, snapshot: str, now: float,
           envelope: str | None = None) -> int:
    """`envelope` — shikoyat vaqtidagi shifrlangan xabar (E2EE). `snapshot` — shikoyatchi O'ZI ixtiyoriy ochib bergan matn."""
    return db.run(
        "INSERT INTO reports(message_id,reporter_id,target_id,reason,snapshot,created_at,envelope) VALUES(?,?,?,?,?,?,?)",
        (message_id, reporter_id, target_id, crypto.seal(reason, WHY), crypto.seal(snapshot, SNAP), now, envelope))


def exists(message_id: int, reporter_id: int) -> bool:
    return db.one("SELECT 1 FROM reports WHERE message_id=? AND reporter_id=?", (message_id, reporter_id)) is not None


def _dec(r) -> dict:
    d = dict(r)
    d["reason"] = crypto.open_(d["reason"], WHY) or ""
    d["snapshot"] = crypto.open_(d["snapshot"], SNAP) or ""
    d["envelope"] = d.get("envelope") or ""
    return d


def get(rid: int):
    r = db.one("SELECT * FROM reports WHERE id=?", (rid,))
    return _dec(r) if r else None


def listing(status: str, before: int, limit: int) -> list[dict]:
    where, args = [], []
    if status in ("open", "closed"):
        where.append("status=?"); args.append(status)
    if before:
        where.append("id<?"); args.append(before)
    sql = "SELECT * FROM reports" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
    return [_dec(r) for r in db.all(sql, (*args, limit))]


def close(rid: int, admin_id: int, action: str, now: float) -> None:
    db.run("UPDATE reports SET status='closed', handled_by=?, handled_at=?, action=? WHERE id=?", (admin_id, now, action, rid))


def close_for_message(message_id: int, admin_id: int, action: str, now: float) -> None:
    db.run("UPDATE reports SET status='closed', handled_by=?, handled_at=?, action=? WHERE message_id=? AND status='open'",
           (admin_id, now, action, message_id))


def open_count() -> int:
    return db.one("SELECT COUNT(*) AS c FROM reports WHERE status='open'")["c"]
