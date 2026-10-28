"""Harakatlar logi (IP, profil, amal) va IP bo'yicha jamlanmalar."""
import time

from app import crypto
from app.db import db

CTX = "act"

_inserts = 0


def add(action: str, *, ip=None, user_id=None, username=None, detail=None, keep_days: int = 90) -> None:
    global _inserts
    now = time.time()
    db.run(
        "INSERT INTO activity(created_at,ip,user_id,username,action,detail) VALUES(?,?,?,?,?,?)",
        (now, ip, user_id, username, action, crypto.seal(detail, CTX)),
    )
    _inserts += 1
    if _inserts % 500 == 0:                       # eskirgan yozuvlarni vaqti-vaqti bilan tozalash
        prune(keep_days)


def prune(keep_days: int) -> None:
    db.run("DELETE FROM activity WHERE created_at < ?", (time.time() - keep_days * 86400,))


def query(*, ip: str = "", user: str = "", action: str = "", before: int = 0, limit: int = 100):
    where, args = [], []
    if ip:
        where.append("ip LIKE ?")
        args.append(f"%{ip}%")
    if user:
        where.append("username LIKE ?")
        args.append(f"%{user.lstrip('@')}%")
    if action:
        where.append("action = ?")
        args.append(action)
    if before:
        where.append("id < ?")
        args.append(before)
    sql = "SELECT * FROM activity" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
    out = []
    for r in db.all(sql, (*args, limit)):
        d = dict(r)
        d["detail"] = crypto.open_(d["detail"], CTX)
        out.append(d)
    return out


def ip_profiles(q: str = "", limit: int = 400):
    """(ip, profil) juftliklari bo'yicha: kirishlar, ulanishlar, xabarlar, noto'g'ri urinishlar."""
    where, args = "WHERE a.ip IS NOT NULL", []
    if q:
        where += " AND (a.ip LIKE ? OR a.username LIKE ?)"
        args += [f"%{q}%", f"%{q.lstrip('@')}%"]
    return db.all(
        f"""SELECT a.ip AS ip, a.user_id AS user_id, a.username AS username, u.nickname AS nickname,
                   SUM(a.action IN ('login','register')) AS logins,
                   SUM(a.action = 'session') AS sessions,
                   SUM(a.action IN ('msg','dm','image')) AS msgs,
                   SUM(a.action = 'login_failed') AS failed,
                   MIN(a.created_at) AS first_seen, MAX(a.created_at) AS last_seen
            FROM activity a LEFT JOIN users u ON u.id = a.user_id
            {where}
            GROUP BY a.ip, COALESCE(a.user_id, 0), a.username
            ORDER BY MAX(a.created_at) DESC LIMIT ?""",
        (*args, limit),
    )


def staff_used_ip(ip: str) -> bool:
    return db.one(
        "SELECT 1 FROM activity a JOIN users u ON u.id=a.user_id "
        "WHERE a.ip=? AND u.role IN ('owner','admin') LIMIT 1", (ip,)) is not None


def _filters(ip: str, user: str, action: str):
    where, args = [], []
    if ip:
        where.append("ip LIKE ?"); args.append(f"%{ip}%")
    if user:
        where.append("username LIKE ?"); args.append(f"%{user.lstrip('@')}%")
    if action:
        where.append("action = ?"); args.append(action)
    return where, args


def delete_ids(ids: list[int], *, keep_owner: bool) -> int:
    """Tanlangan yozuvlarni o'chiradi. keep_owner=True bo'lsa, ega harakatlari o'chirilmaydi."""
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    cond = f"id IN ({marks})"
    if keep_owner:
        cond += " AND COALESCE(user_id,0) NOT IN (SELECT id FROM users WHERE role='owner')"
    with db._lock:
        cur = db._conn.execute(f"DELETE FROM activity WHERE {cond}", tuple(ids))
        db._conn.commit()
        return cur.rowcount


def delete_matching(ip: str = "", user: str = "", action: str = "", *, keep_owner: bool) -> int:
    """Filtrga mos (filtr bo'sh bo'lsa - hamma) yozuvlarni o'chiradi."""
    where, args = _filters(ip, user, action)
    if keep_owner:
        where.append("COALESCE(user_id,0) NOT IN (SELECT id FROM users WHERE role='owner')")
    sql = "DELETE FROM activity" + (" WHERE " + " AND ".join(where) if where else "")
    with db._lock:
        cur = db._conn.execute(sql, tuple(args))
        db._conn.commit()
        return cur.rowcount
