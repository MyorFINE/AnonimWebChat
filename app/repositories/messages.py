from app import crypto
from app.db import db

CTX = "msg"
FNAME = "fname"


def _dec(r):
    """Qatorni lug'atga aylantirib, matnini shifrdan ochadi (bazada matn shifrlangan yotadi)."""
    if r is None:
        return None
    d = dict(r)
    d["content"] = crypto.open_(d["content"], CTX)
    d["file_name"] = crypto.open_(d.get("file_name"), FNAME)
    return d


def create(uid: int, content: str, now: float, recipient_id: int | None = None,
           image: str | None = None, reply_to: int | None = None,
           img_w: int | None = None, img_h: int | None = None,
           file: str | None = None, file_name: str | None = None,
           file_mime: str | None = None, file_size: int | None = None, e2e: bool = False) -> int:
    """`e2e=True`: `content` — E2EE konvert (allaqachon shifr); bazaga O'ZGARTIRISHSIZ yoziladi, server ocha olmaydi."""
    return db.run(
        "INSERT INTO messages(user_id,content,created_at,recipient_id,image,reply_to,img_w,img_h,"
        "file,file_name,file_mime,file_size,e2e) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, content if e2e else crypto.seal(content, CTX), now, recipient_id, image, reply_to, img_w, img_h,
         file, crypto.seal(file_name, FNAME), file_mime, file_size, int(e2e)),
    )


def find_media(name: str):
    """Fayl nomi bo'yicha (rasm, uning xira nusxasi yoki boshqa fayl) faol xabarni topadi."""
    if name.endswith("_t.jpg"):
        return _dec(db.one("SELECT * FROM messages WHERE deleted=0 AND image LIKE ?", (name[:-6] + ".%",)))
    return _dec(db.one("SELECT * FROM messages WHERE deleted=0 AND (image=? OR file=?)", (name, name)))


def group_media(before: int, limit: int, kind: str = "", sender: str = "", min_size: int = 0):
    """Media boshqaruvi uchun: umumiy chatdagi faol xabarlar (rasm/fayl bilan). Matn/nom OCHILMAYDI."""
    where = ["m.deleted=0", "m.recipient_id IS NULL", "(m.image IS NOT NULL OR m.file IS NOT NULL)"]
    args: list = []
    if before:
        where.append("m.id<?"); args.append(before)
    if sender:
        where.append("u.username LIKE ?"); args.append(f"%{sender.lstrip('@')}%")
    if min_size:
        where.append("COALESCE(m.file_size,0)>=?"); args.append(min_size)
    if kind == "image":
        where.append("m.image IS NOT NULL")
    elif kind == "video":
        where.append("m.file_mime LIKE 'video/%'")
    elif kind == "audio":
        where.append("m.file_mime LIKE 'audio/%'")
    elif kind == "other":
        where.append("m.file IS NOT NULL AND COALESCE(m.file_mime,'') NOT LIKE 'video/%' AND COALESCE(m.file_mime,'') NOT LIKE 'audio/%'")
    return db.all(
        "SELECT m.id, m.user_id, m.created_at, m.image, m.file, m.file_mime, m.file_size, u.username, u.nickname "
        "FROM messages m JOIN users u ON u.id=m.user_id WHERE " + " AND ".join(where) + " ORDER BY m.id DESC LIMIT ?",
        (*args, limit))


def media_totals() -> dict:
    r = db.one("SELECT COUNT(*) AS n, COALESCE(SUM(file_size),0) AS size FROM messages "
               "WHERE deleted=0 AND recipient_id IS NULL AND (image IS NOT NULL OR file IS NOT NULL)")
    return {"count": r["n"], "size": r["size"]}


def clear_media(mid: int) -> None:
    """Xabardan faqat faylni olib tashlaydi (matn qoladi)."""
    db.run("UPDATE messages SET image=NULL, img_w=NULL, img_h=NULL, file=NULL, file_name=NULL, file_mime=NULL, file_size=NULL WHERE id=?", (mid,))


def group_by_user(uid: int, limit: int):
    """Foydalanuvchining umumiy chatdagi faol xabarlari (yangisi birinchi)."""
    return db.all("SELECT * FROM messages WHERE deleted=0 AND recipient_id IS NULL AND user_id=? ORDER BY id DESC LIMIT ?",
                  (uid, limit))


def purge_deleted_group() -> int:
    """O'chirilgan (soft-delete) umumiy chat xabarlarini bazadan butunlay o'chiradi."""
    with db._lock:
        cur = db._conn.execute("DELETE FROM messages WHERE deleted=1 AND recipient_id IS NULL")
        db._conn.commit()
        return cur.rowcount


def get(mid: int):
    return _dec(db.one("SELECT * FROM messages WHERE id=?", (mid,)))


def get_active(mid: int):
    return _dec(db.one("SELECT * FROM messages WHERE id=? AND deleted=0", (mid,)))


def group_page(before: int, limit: int) -> list:
    """Admin logi uchun: umumiy chatdagi barcha xabarlar (o'chirilganlari ham), matni HALI shifrlangan holda."""
    return db.all(
        "SELECT * FROM messages WHERE recipient_id IS NULL AND (?=0 OR id<?) ORDER BY id DESC LIMIT ?",
        (before, before, limit))


def raw_group(limit: int) -> list:
    """Bazada AYNAN yotgan ko'rinishdagi so'nggi umumiy chat qatorlari (shifrlanmagan holda ochilmaydi). Inspektor uchun."""
    return db.all("SELECT * FROM messages WHERE recipient_id IS NULL ORDER BY id DESC LIMIT ?", (limit,))


def raw_dm(a: int, b: int, limit: int) -> list:
    return db.all(
        "SELECT * FROM messages WHERE recipient_id IS NOT NULL AND "
        "((user_id=? AND recipient_id=?) OR (user_id=? AND recipient_id=?)) ORDER BY id DESC LIMIT ?", (a, b, b, a, limit))


def recent(limit: int):
    """Umumiy chat tarixi (shaxsiy xabarlar kirmaydi)."""
    rows = db.all(
        "SELECT * FROM messages WHERE deleted=0 AND recipient_id IS NULL ORDER BY id DESC LIMIT ?", (limit,)
    )
    return [_dec(r) for r in rows[::-1]]


def dm_history(a: int, b: int, limit: int):
    rows = db.all(
        "SELECT * FROM messages WHERE deleted=0 AND recipient_id IS NOT NULL AND "
        "((user_id=? AND recipient_id=?) OR (user_id=? AND recipient_id=?)) ORDER BY id DESC LIMIT ?",
        (a, b, b, a, limit),
    )
    return [_dec(r) for r in rows[::-1]]


def dialogs(uid: int):
    """Foydalanuvchining shaxsiy suhbatlari: [(hamkor_id, oxirgi_xabar_id, o'qilmaganlar)], yangisi birinchi."""
    return db.all(
        """SELECT CASE WHEN user_id=? THEN recipient_id ELSE user_id END AS partner,
                  MAX(id) AS last_id,
                  SUM(CASE WHEN recipient_id=? AND read=0 THEN 1 ELSE 0 END) AS unread
           FROM messages
           WHERE deleted=0 AND recipient_id IS NOT NULL AND (user_id=? OR recipient_id=?)
           GROUP BY partner ORDER BY last_id DESC""",
        (uid, uid, uid, uid),
    )


def mark_read(reader: int, partner: int) -> int:
    """Hamkor yuborgan, hali o'qilmagan xabarlarni o'qilgan deb belgilaydi. Qancha o'zgargani qaytadi."""
    with db._lock:
        cur = db._conn.execute(
            "UPDATE messages SET read=1 WHERE recipient_id=? AND user_id=? AND read=0 AND deleted=0",
            (reader, partner),
        )
        db._conn.commit()
        return cur.rowcount


def update_content(mid: int, content: str, now: float, e2e: bool = False) -> None:
    db.run("UPDATE messages SET content=?, edited_at=? WHERE id=?", (content if e2e else crypto.seal(content, CTX), now, mid))


def legacy_count() -> int:
    """Hali server ocha oladigan (E2EE emas) xabarlar soni."""
    return db.one("SELECT COUNT(*) AS c FROM messages WHERE e2e=0")["c"]


def purge_legacy() -> list:
    """E2EE bo'lmagan (server o'qiy oladigan) BARCHA xabarlarni bazadan butunlay o'chiradi. (id, image, file) qatorlari qaytadi."""
    with db._lock:
        rows = db._conn.execute("SELECT id, image, file FROM messages WHERE e2e=0").fetchall()
        db._conn.execute("DELETE FROM messages WHERE e2e=0")
        db._conn.execute("UPDATE logs SET old_content=NULL, new_content=NULL WHERE type IN ('edit','delete')")
        db._conn.execute("UPDATE activity SET detail=NULL WHERE action IN ('msg','edit','delete','image','file')")
        db._conn.execute("UPDATE reports SET snapshot=NULL WHERE envelope IS NULL")
        db._conn.commit()
    return list(rows)


def mark_deleted(mid: int) -> None:
    db.run("UPDATE messages SET deleted=1 WHERE id=?", (mid,))


def clear_group() -> list:
    """Umumiy chatdagi barcha faol xabarlarni o'chirilgan deb belgilaydi. O'chirilgan qatorlarni (id, image) qaytaradi."""
    with db._lock:
        rows = db._conn.execute(
            "SELECT id, image, file FROM messages WHERE deleted=0 AND recipient_id IS NULL"
        ).fetchall()
        db._conn.execute("UPDATE messages SET deleted=1 WHERE deleted=0 AND recipient_id IS NULL")
        db._conn.commit()
    return list(rows)


def clear_dm(a: int, b: int) -> list:
    """Ikki kishi orasidagi butun shaxsiy yozishmani o'chirilgan deb belgilaydi. (id, image) qatorlarini qaytaradi."""
    cond = "recipient_id IS NOT NULL AND deleted=0 AND ((user_id=? AND recipient_id=?) OR (user_id=? AND recipient_id=?))"
    with db._lock:
        rows = db._conn.execute(f"SELECT id, image, file FROM messages WHERE {cond}", (a, b, b, a)).fetchall()
        db._conn.execute(f"UPDATE messages SET deleted=1 WHERE {cond}", (a, b, b, a))
        db._conn.commit()
    return list(rows)
