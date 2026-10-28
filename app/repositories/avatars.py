from app.db import db


def list_for_user(uid: int):
    return db.all("SELECT * FROM avatars WHERE user_id=? ORDER BY id", (uid,))


def add(uid: int, filename: str, now: float) -> int:
    return db.run("INSERT INTO avatars(user_id,filename,created_at) VALUES(?,?,?)", (uid, filename, now))


def delete(avatar_id: int) -> None:
    db.run("DELETE FROM avatars WHERE id=?", (avatar_id,))
