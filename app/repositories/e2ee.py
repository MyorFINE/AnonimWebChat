"""E2EE jadvallari: guruh kaliti avlodlari (epoch), a'zolar uchun o'ralgan kalitlar va shifrlangan fayllar.

Serverda guruh kalitining o'zi YO'Q: faqat har bir a'zoning ommaviy kaliti bilan o'ralgan nusxasi yotadi.
"""
import time

from app.db import db


# ----------------------------------------------------------------------------------------------- epochlar
def current_epoch() -> int:
    r = db.one("SELECT MAX(epoch) AS e FROM room_epochs")
    return int(r["e"] or 0)


def epochs():
    return db.all("SELECT epoch, created_by, created_at, check_blob, reason FROM room_epochs ORDER BY epoch")


def create_epoch(epoch: int, by: int, check_blob: str, wraps: list[tuple[int, str]], reason: str) -> bool:
    """Yangi avlodni va unga tegishli o'ralgan kalitlarni BITTA tranzaksiyada yozadi.
    Shu epoch allaqachon bo'lsa False (birinchi yozgan g'olib: poyga holati)."""
    now = time.time()
    with db._lock:
        c = db._conn
        try:
            c.execute("INSERT INTO room_epochs(epoch,created_by,created_at,check_blob,reason) VALUES(?,?,?,?,?)",
                      (epoch, by, now, check_blob, reason))
        except Exception:
            c.rollback()
            return False
        for uid, wrapped in wraps:
            c.execute("INSERT OR IGNORE INTO room_keys(epoch,user_id,wrapped,wrapper_id,created_at) VALUES(?,?,?,?,?)",
                      (epoch, uid, wrapped, by, now))
        c.commit()
    return True


# ----------------------------------------------------------------------------------------------- o'ralgan kalitlar
def keys_for(uid: int):
    return db.all("SELECT epoch, wrapped, wrapper_id, created_at FROM room_keys WHERE user_id=? ORDER BY epoch", (uid,))


def add_wraps(epoch: int, by: int, wraps: list[tuple[int, str]]) -> list[int]:
    """Faqat YO'Q bo'lgan juftliklarga qo'shadi (mavjudini bosib ketmaydi). Qo'shilgan foydalanuvchi id'lari qaytadi."""
    now, added = time.time(), []
    with db._lock:
        c = db._conn
        for uid, wrapped in wraps:
            cur = c.execute("INSERT OR IGNORE INTO room_keys(epoch,user_id,wrapped,wrapper_id,created_at) VALUES(?,?,?,?,?)",
                            (epoch, uid, wrapped, by, now))
            if cur.rowcount:
                added.append(uid)
        c.commit()
    return added


def drop_own_wrap(epoch: int, uid: int) -> None:
    db.run("DELETE FROM room_keys WHERE epoch=? AND user_id=?", (epoch, uid))


def missing(limit: int = 200):
    """Kalitli faol foydalanuvchilardan qaysi epochlar uchun o'ralgan kaliti YO'Q (eng yangi epoch birinchi)."""
    return db.all(
        """SELECT e.epoch AS epoch, u.id AS user_id, u.ecdh_pub AS ecdh_pub
           FROM room_epochs e JOIN users u ON u.deleted=0 AND u.banned=0 AND u.ecdh_pub IS NOT NULL
           WHERE NOT EXISTS (SELECT 1 FROM room_keys k WHERE k.epoch=e.epoch AND k.user_id=u.id)
           ORDER BY e.epoch DESC, u.id LIMIT ?""", (limit,))


def wrap_log(limit: int = 200):
    """Kim kimga guruh kalitini bergani (audit): server-view va inspektor uchun."""
    return db.all("SELECT epoch, user_id, wrapper_id, created_at FROM room_keys ORDER BY created_at DESC LIMIT ?", (limit,))


# ----------------------------------------------------------------------------------------------- fayllar
def add_blob(name: str, uid: int, size: int) -> None:
    db.run("INSERT INTO e2e_blobs(name,user_id,size,created_at) VALUES(?,?,?,?)", (name, uid, size, time.time()))


def get_blob(name: str):
    return db.one("SELECT * FROM e2e_blobs WHERE name=?", (name,))


def blob_attached(name: str) -> bool:
    return db.one("SELECT 1 FROM messages WHERE file=?", (name,)) is not None


def stale_blobs(older_than: float):
    """Yuklangan, lekin hech bir xabarga biriktirilmagan eski fayllar."""
    return db.all("SELECT name FROM e2e_blobs b WHERE created_at<? AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.file=b.name)",
                  (older_than,))


def drop_blob(name: str) -> None:
    db.run("DELETE FROM e2e_blobs WHERE name=?", (name,))
