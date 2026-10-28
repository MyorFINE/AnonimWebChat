from app.db import db


def all_rows():
    return db.all(
        """SELECT b.ip, b.reason, b.created_at, u.username AS by_username
           FROM ip_blocks b LEFT JOIN users u ON u.id = b.blocked_by ORDER BY b.created_at DESC""")


def ips() -> list[str]:
    return [r["ip"] for r in db.all("SELECT ip FROM ip_blocks")]


def add(ip: str, reason: str | None, actor_id: int, now: float) -> None:
    db.run("INSERT OR REPLACE INTO ip_blocks(ip,reason,blocked_by,created_at) VALUES(?,?,?,?)",
           (ip, reason or None, actor_id, now))


def remove(ip: str) -> None:
    db.run("DELETE FROM ip_blocks WHERE ip=?", (ip,))
