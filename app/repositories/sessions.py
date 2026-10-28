from app.db import db


def create(token_hash: str, uid: int, now: float) -> None:
    db.run("INSERT INTO sessions(token_hash,user_id,created_at) VALUES(?,?,?)", (token_hash, uid, now))


def get_user(token_hash: str):
    return db.one(
        "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?", (token_hash,)
    )


def delete(token_hash: str) -> None:
    db.run("DELETE FROM sessions WHERE token_hash=?", (token_hash,))


def delete_for_user(uid: int, keep: str | None = None) -> None:
    if keep:
        db.run("DELETE FROM sessions WHERE user_id=? AND token_hash!=?", (uid, keep))
    else:
        db.run("DELETE FROM sessions WHERE user_id=?", (uid,))
