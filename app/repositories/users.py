from app.db import db


def count() -> int:
    return db.one("SELECT COUNT(*) AS c FROM users")["c"]


def create(username: str, nickname: str, password_hash: str, role: str, now: float, e2ee: dict | None = None) -> int:
    """`e2ee` berilsa (ommaviy kalitlar + parol bilan o'ralgan maxfiy kalitlar), akkaunt darrov E2EE (auth_v=1)."""
    if e2ee:
        return db.run(
            "INSERT INTO users(username,nickname,password_hash,role,created_at,ecdh_pub,sign_pub,key_blob,kdf_iter,auth_v) "
            "VALUES(?,?,?,?,?,?,?,?,?,1)",
            (username, nickname, password_hash, role, now, e2ee["ecdh_pub"], e2ee["sign_pub"], e2ee["key_blob"], e2ee["kdf_iter"]),
        )
    return db.run(
        "INSERT INTO users(username,nickname,password_hash,role,created_at) VALUES(?,?,?,?,?)",
        (username, nickname, password_hash, role, now),
    )


def set_e2ee(uid: int, password_hash: str, e2ee: dict) -> None:
    """Eski (auth_v=0) akkauntni E2EE'ga o'tkazadi: yangi parol hash'i + kalitlar. Bir marta."""
    db.run("UPDATE users SET password_hash=?, ecdh_pub=?, sign_pub=?, key_blob=?, kdf_iter=?, auth_v=1 WHERE id=? AND auth_v=0",
           (password_hash, e2ee["ecdh_pub"], e2ee["sign_pub"], e2ee["key_blob"], e2ee["kdf_iter"], uid))


def set_key_blob(uid: int, password_hash: str, key_blob: str, kdf_iter: int) -> None:
    """Parol almashganda: yangi hash va qayta o'ralgan maxfiy kalitlar (ommaviy kalitlar O'ZGARMAYDI)."""
    db.run("UPDATE users SET password_hash=?, key_blob=?, kdf_iter=? WHERE id=?", (password_hash, key_blob, kdf_iter, uid))


def key_rows(ids: list[int]):
    """Ommaviy kalitlar (o'chirilgan akkauntlarniki bo'sh)."""
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return db.all(f"SELECT id, ecdh_pub, sign_pub FROM users WHERE id IN ({marks})", tuple(ids))


def keyed_active():
    """Kalitli, o'chirilmagan, banlanmagan foydalanuvchilar (guruh kalitini olishi kerak bo'lganlar)."""
    return db.all("SELECT id, ecdh_pub, sign_pub FROM users WHERE deleted=0 AND banned=0 AND ecdh_pub IS NOT NULL ORDER BY id")


def get(uid: int):
    return db.one("SELECT * FROM users WHERE id=?", (uid,))


def get_by_username(name: str):
    return db.one("SELECT * FROM users WHERE username=?", (name.strip().lstrip("@").lower(),))


def get_view(uid: int):
    """Foydalanuvchi + faol avatar fayl nomi."""
    return db.one(
        """SELECT u.id, u.username, u.nickname, u.role, u.bio, u.color, u.created_at, u.deleted, u.badge, u.badge_anim, a.filename AS avatar
           FROM users u LEFT JOIN avatars a ON a.id = u.active_avatar_id WHERE u.id=?""",
        (uid,),
    )


def list_staff():
    return db.all("SELECT * FROM users WHERE role IN ('owner','admin') ORDER BY role='owner' DESC, id")


def set_nickname(uid: int, nickname: str) -> None:
    db.run("UPDATE users SET nickname=? WHERE id=?", (nickname, uid))


def set_password(uid: int, password_hash: str) -> None:
    db.run("UPDATE users SET password_hash=? WHERE id=?", (password_hash, uid))


def set_role(uid: int, role: str) -> None:
    db.run("UPDATE users SET role=? WHERE id=?", (role, uid))


def set_ban(uid: int, banned: bool, reason: str | None = None) -> None:
    db.run("UPDATE users SET banned=?, ban_reason=? WHERE id=?", (int(banned), reason or None, uid))


def set_mute(uid: int, until: float, reason: str | None = None) -> None:
    db.run("UPDATE users SET muted_until=?, mute_reason=? WHERE id=?", (until, reason or None, uid))


def set_active_avatar(uid: int, avatar_id: int | None) -> None:
    db.run("UPDATE users SET active_avatar_id=? WHERE id=?", (avatar_id, uid))


def set_color(uid: int, color: str | None) -> None:
    db.run("UPDATE users SET color=? WHERE id=?", (color or None, uid))


def set_badge(uid: int, badge: str | None, anim: str | None) -> None:
    db.run("UPDATE users SET badge=?, badge_anim=? WHERE id=?", (badge or None, anim or None, uid))


def set_warns(uid: int, n: int) -> None:
    db.run("UPDATE users SET warns=? WHERE id=?", (max(0, n), uid))


def staff_ids() -> list[int]:
    return [r["id"] for r in db.all("SELECT id FROM users WHERE role IN ('owner','admin') AND deleted=0 AND banned=0")]


def set_bio(uid: int, bio: str) -> None:
    db.run("UPDATE users SET bio=? WHERE id=?", (bio, uid))


def list_members(include_banned: bool = False):
    """Barcha a'zolar (ega, adminlar, keyin nickname bo'yicha). Banlanganlar faqat adminlarga ko'rinadi."""
    where = "WHERE u.deleted=0" + ("" if include_banned else " AND u.banned=0")   # o'chirilganlar ro'yxatda yo'q
    return db.all(
        f"""SELECT u.id, u.username, u.nickname, u.role, u.bio, u.color, u.created_at, u.banned, u.muted_until,
                   u.badge, u.badge_anim, u.warns, u.ecdh_pub, u.sign_pub, a.filename AS avatar
            FROM users u LEFT JOIN avatars a ON a.id = u.active_avatar_id {where}
            ORDER BY CASE u.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, u.nickname COLLATE NOCASE"""
    )


def mark_deleted(uid: int, now: float) -> None:
    """Akkauntni "Deleted account"ga aylantiradi: shaxsiy ma'lumotlar tozalanadi, kirish imkoni yo'qoladi.
    Qator o'chirilmaydi — yozgan xabarlari chatda qoladi. Username bo'shaydi (deleted_<id> bilan almashadi).
    Maxfiy kalit zaxirasi o'chadi; OMMAVIY kalitlar qoladi (eski xabarlar imzosini tekshirish va lichka tarixini ochish uchun)."""
    db.run("DELETE FROM room_keys WHERE user_id=?", (uid,))
    db.run(
        "UPDATE users SET deleted=1, deleted_at=?, username=?, nickname='Deleted account', bio='', color=NULL, "
        "role='user', banned=0, ban_reason=NULL, muted_until=0, mute_reason=NULL, active_avatar_id=NULL, badge=NULL, badge_anim=NULL, warns=0, "
        "password_hash='!', key_blob=NULL WHERE id=?",
        (now, f"deleted_{uid}", uid),
    )
