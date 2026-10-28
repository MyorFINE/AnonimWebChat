"""Xabarlar: umumiy chat va shaxsiy yozishmalar (yuborish, tahrirlash, o'chirish, o'qilgan deb belgilash)."""
import re
import time
from math import ceil

from app import e2ee as envelope_fmt
from app.config import settings
from app.errors import ChatError
from app.repositories import e2ee as e2ee_repo
from app.repositories import logs, messages, users
from app.roles import Role, role_of
from app.security import limiter
from app.services import media, modsettings, views

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize(text: str) -> str:
    return _CTRL.sub("", text).strip()[: settings.max_message_length]


def _ensure_can_write(user) -> None:
    left = views.mute_left(user)
    if left > 0:
        raise ChatError(f"Siz mute holatidasiz (~{ceil(left / 60)} daqiqa qoldi)")


def audience(msg) -> list[int] | None:
    """Xabarni kimlar ko'radi: shaxsiy xabarda [yuboruvchi, qabul qiluvchi], umumiyda None (hamma)."""
    if msg["recipient_id"] is None:
        return None
    return [msg["user_id"], msg["recipient_id"]]


def _partner(user, partner_id: int, *, allow_deleted: bool = False):
    p = users.get(partner_id) if isinstance(partner_id, int) else None
    if not p or p["banned"]:
        raise ChatError("Foydalanuvchi topilmadi", 404)
    if p["id"] == user["id"]:
        raise ChatError("O'zingizga yoza olmaysiz")
    if p["deleted"] and not allow_deleted:
        raise ChatError("Bu akkaunt o'chirilgan. Unga xabar yuborib bo'lmaydi", 403)
    return p


def history() -> list[dict]:
    return [views.message_view(m) for m in messages.recent(settings.history_limit)]


def dm_history(user, partner_id: int) -> list[dict]:
    _partner(user, partner_id, allow_deleted=True)          # o'chirilgan akkaunt bilan eski yozishmani ko'rish mumkin
    return [views.message_view(m) for m in messages.dm_history(user["id"], partner_id, settings.history_limit)]


def dialogs(user) -> list[dict]:
    out = []
    for r in messages.dialogs(user["id"]):
        partner = users.get(r["partner"])
        if not partner or partner["banned"]:
            continue
        out.append({
            "user": views.user_view(partner["id"]),
            "last": views.message_view(messages.get(r["last_id"])),
            "unread": r["unread"] or 0,
        })
    return out


def _reply_target(user, to: int | None, reply_to: int | None) -> int | None:
    """Javob berilayotgan xabar shu suhbatga tegishli ekanini tekshiradi."""
    if reply_to is None:
        return None
    m = messages.get_active(reply_to)
    if not m:
        raise ChatError("Javob beriladigan xabar topilmadi")
    if to is None:
        if m["recipient_id"] is not None:
            raise ChatError("Bu xabar boshqa suhbatga tegishli")
    elif m["recipient_id"] is None or {m["user_id"], m["recipient_id"]} != {user["id"], to}:
        raise ChatError("Bu xabar boshqa suhbatga tegishli")
    return m["id"]


def _rate_limit(user) -> None:
    try:
        limiter.check(f"msg:{user['id']}", settings.msg_rate_count, settings.msg_rate_window,
                      "Sekinroq yozing (spam himoyasi)")
    except ChatError:
        auto = modsettings.spam_strike(user)         # qayta-qayta urilsa — avtomatik mute
        if auto:
            raise ChatError(auto, 429)
        raise


def _plain_allowed() -> None:
    """Server ochiq matnni qabul qilmaydi (standart). Faqat sinov/eski rejim (TERMCHAT_REQUIRE_E2EE=0) uchun ochiq."""
    if settings.require_e2ee:
        raise ChatError("Xabar shifrlanmagan: server ochiq matnni qabul qilmaydi (E2EE majburiy). Sahifani yangilang", 400)


def _check_envelope(user, envelope, to: int | None) -> dict:
    """Konvert SHAKLINI tekshiradi (ochmaydi!): to'g'ri tur, to'g'ri guruh kaliti avlodi, hajm chegarasi."""
    if not user["ecdh_pub"]:
        raise ChatError("Avval E2EE kalitlaringiz yaratilishi kerak", 409)
    try:
        h = envelope_fmt.parse_envelope(envelope, settings.e2e_max_envelope)
    except ValueError:
        raise ChatError("Xabar shifrlanmagan yoki konvert noto'g'ri", 400)
    if to is None:
        cur = e2ee_repo.current_epoch()
        if h["k"] != "g":
            raise ChatError("Konvert turi mos emas", 400)
        if cur < 1:
            raise ChatError("Guruh kaliti hali yaratilmagan, biroz kuting", 409)
        if h["ep"] != cur:
            raise ChatError("Guruh kaliti yangilangan, qayta urinib ko'ring", 409)
    elif h["k"] != "d":
        raise ChatError("Konvert turi mos emas", 400)
    return h


def post_e2e(user, envelope, to: int | None = None, blob: str | None = None) -> dict:
    """E2EE xabar (matn yoki shifrlangan fayl bilan). Server faqat konvertni saqlaydi; ma'nosini bilmaydi."""
    _ensure_can_write(user)
    if to is not None:
        p = _partner(user, to)
        if not p["ecdh_pub"]:
            raise ChatError("Bu foydalanuvchi hali E2EE kalitlarini yaratmagan (u bir marta kirishi kerak)", 409)
    _check_envelope(user, envelope, to)
    size = None
    if blob is not None:
        b = e2ee_repo.get_blob(blob) if isinstance(blob, str) else None
        if not b or b["user_id"] != user["id"] or e2ee_repo.blob_attached(blob):
            raise ChatError("Fayl topilmadi, qayta yuklang")
        size = b["size"]
    if to is None:
        modsettings.check_group(user, "")              # qulf va sekin rejim (matn ko'rinmagani uchun so'z filtri YO'Q)
    _rate_limit(user)
    mid = messages.create(user["id"], envelope, time.time(), to, None, None, None, None, blob, None, None, size, e2e=True)
    if to is None:
        modsettings.note_post(user)
    return views.message_view(messages.get(mid))


def edit_e2e(user, mid: int, envelope):
    """(xabar_qatori, yangi_konvert) qaytaradi."""
    _ensure_can_write(user)
    msg = messages.get_active(mid)
    if not msg or msg["user_id"] != user["id"]:
        raise ChatError("Faqat o'z xabaringizni tahrirlay olasiz")
    if not msg["e2e"]:
        raise ChatError("Bu eski (E2EE emas) xabar, uni tahrirlab bo'lmaydi")
    _check_envelope(user, envelope, msg["recipient_id"])
    messages.update_content(mid, envelope, time.time(), e2e=True)
    if msg["recipient_id"] is None:                      # adminlar logiga FAQAT shifrlangan konvertlar tushadi
        logs.add("edit", message_id=mid, user_id=user["id"], actor_id=user["id"], old=msg["content"], new=envelope)
    return msg, envelope


def purge_legacy(actor) -> int:
    """Egasi uchun: server o'qiy oladigan eski (E2EE bo'lmagan) xabarlar va ularning fayllarini butunlay o'chiradi."""
    if role_of(actor) != Role.OWNER:
        raise ChatError("Buni faqat ega bajara oladi", 403)
    rows = messages.purge_legacy()
    for r in rows:
        media.remove_row(r)
    logs.add("clear", user_id=actor["id"], actor_id=actor["id"], new=f"eski xabarlar: {len(rows)} ta")
    return len(rows)


def post(user, text: str, to: int | None = None, reply_to: int | None = None) -> dict:
    _plain_allowed()
    _ensure_can_write(user)
    if to is not None:
        _partner(user, to)
    text = _sanitize(text)
    if not text:
        raise ChatError("Bo'sh xabar")
    if to is None:
        modsettings.check_group(user, text)            # qulf, taqiqlangan so'z, sekin rejim (adminlarga qo'llanmaydi)
    reply = _reply_target(user, to, reply_to)
    _rate_limit(user)
    mid = messages.create(user["id"], text, time.time(), to, None, reply)
    if to is None:
        modsettings.note_post(user)
    return views.message_view(messages.get(mid))


def post_media(user, raw: bytes, filename: str = "", mime: str = "", caption: str = "",
               to: int | None = None, reply_to: int | None = None) -> dict:
    """Istalgan turdagi fayl (rasm, video, hujjat...; 50 MB gacha) + ixtiyoriy izoh yuborish."""
    _plain_allowed()
    _ensure_can_write(user)
    if to is not None:
        _partner(user, to)
    caption = _sanitize(caption or "")
    media.validate(raw)
    if to is None:
        modsettings.check_group(user, caption)
    reply = _reply_target(user, to, reply_to)
    _rate_limit(user)
    st = media.store(raw, filename, mime)               # rasm tozalanadi; hammasi shifrlanib saqlanadi
    try:
        mid = messages.create(user["id"], caption, time.time(), to, st.image, reply, st.width, st.height,
                              st.file, st.file_name, st.file_mime, st.size)
    except Exception:
        media.remove(st.image or st.file)
        raise
    if to is None:
        modsettings.note_post(user)
    return views.message_view(messages.get(mid))


def mark_read(user, partner_id: int) -> int:
    """Hamkorning bizga yozgan xabarlarini o'qilgan deb belgilaydi."""
    if not isinstance(partner_id, int):
        return 0
    return messages.mark_read(user["id"], partner_id)


def edit(user, mid: int, new_text: str):
    """(xabar_qatori, yangi_matn) qaytaradi."""
    _plain_allowed()
    _ensure_can_write(user)
    msg = messages.get_active(mid)
    if not msg or msg["user_id"] != user["id"]:
        raise ChatError("Faqat o'z xabaringizni tahrirlay olasiz")
    new_text = _sanitize(new_text)
    if not new_text and not (msg["image"] or msg["file"]):
        raise ChatError("Matn bo'sh bo'lishi mumkin emas")
    if msg["recipient_id"] is None:
        modsettings.check_words(user, new_text)
    if new_text == msg["content"]:
        raise ChatError("Matn o'zgarmagan")
    messages.update_content(mid, new_text, time.time())
    if msg["recipient_id"] is None:                 # shaxsiy yozishmalar adminlar logiga tushmaydi
        logs.add("edit", message_id=mid, user_id=user["id"], actor_id=user["id"], old=msg["content"], new=new_text)
    return msg, new_text


def delete(actor, mid: int):
    """O'chirilgan xabar qatorini qaytaradi (kimga xabar yuborishni aniqlash uchun)."""
    msg = messages.get_active(mid)
    if not msg:
        raise ChatError("Xabar topilmadi")
    is_dm = msg["recipient_id"] is not None
    if msg["user_id"] != actor["id"]:
        if is_dm:
            raise ChatError("Shaxsiy xabarni faqat yuboruvchi o'chira oladi")
        if role_of(actor) < Role.ADMIN:
            raise ChatError("Faqat o'z xabaringizni o'chira olasiz")
        owner_of_msg = users.get(msg["user_id"])
        if role_of(owner_of_msg) >= Role.ADMIN and role_of(actor) != Role.OWNER:
            raise ChatError("Admin xabarini faqat ega o'chira oladi")
    messages.mark_deleted(mid)
    media.remove_row(msg)
    if not is_dm:
        logs.add("delete", message_id=mid, user_id=msg["user_id"], actor_id=actor["id"], old=msg["content"])
    return msg


MAX_BULK_DELETE = 200


def delete_many(actor, ids: list[int]):
    """Belgilangan xabarlarni birdaniga o'chiradi. (o'chirilgan_qatorlar, o'tkazib_yuborilganlar_soni)."""
    done, skipped = [], 0
    for mid in list(dict.fromkeys(ids))[:MAX_BULK_DELETE]:
        try:
            done.append(delete(actor, mid))
        except ChatError:                           # ruxsat yo'q yoki allaqachon o'chirilgan
            skipped += 1
    return done, skipped


def clear_group(actor) -> int:
    """Umumiy chatni to'liq tozalaydi (faqat admin/ega). O'chirilgan xabarlar sonini qaytaradi."""
    if role_of(actor) < Role.ADMIN:
        raise ChatError("Chatni faqat adminlar tozalay oladi")
    rows = messages.clear_group()
    for r in rows:
        media.remove_row(r)
    logs.add("clear", user_id=actor["id"], actor_id=actor["id"], new=f"{len(rows)} ta xabar")
    return len(rows)


def delete_dm(user, partner_id: int) -> int:
    """Shaxsiy suhbatni ikki tomon uchun ham butunlay o'chiradi. O'chirilgan xabarlar sonini qaytaradi."""
    p = users.get(partner_id) if isinstance(partner_id, int) else None
    if not p or p["id"] == user["id"]:
        raise ChatError("Suhbat topilmadi", 404)
    rows = messages.clear_dm(user["id"], p["id"])
    for r in rows:
        media.remove_row(r)
    return len(rows)
