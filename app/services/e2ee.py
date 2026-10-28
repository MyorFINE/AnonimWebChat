"""E2EE: kalitlar, guruh kaliti avlodlari (epoch) va "server nimani ko'radi" inspektori.

SERVER HECH QACHON: xabar matnini, fayl mazmunini/nomini, guruh kalitini, foydalanuvchining maxfiy kalitini yoki
parolini bilmaydi. U faqat: kim, qachon, qaysi suhbatga, necha bayt yuborganini va shifrlangan konvertlarni saqlaydi.
"""
from __future__ import annotations

import re
import time

from app import crypto, e2ee
from app.config import settings
from app.errors import ChatError
from app.repositories import activity as activity_repo
from app.repositories import e2ee as repo
from app.repositories import messages, users
from app.roles import is_admin
from app.security import hash_password, limiter, verify_password

KDF_DEFAULT, KDF_MIN, KDF_MAX = 600_000, 100_000, 3_000_000
AUTH_RE = re.compile(r"^[0-9a-f]{64}$")            # mijoz parolidan hosil qilgan 256-bitli "kirish kaliti" (hex)
MAX_WRAPS = 2000


def bad(msg: str = "E2EE ma'lumotlari noto'g'ri", status: int = 400) -> ChatError:
    return ChatError(msg, status)


# ----------------------------------------------------------------------------------------------- hisob va kalitlar
def validate_account_keys(data) -> dict:
    """Ro'yxatdan o'tish / yangilash paytida kelgan kalit to'plamini tekshiradi."""
    if not isinstance(data, dict):
        raise bad("E2EE kalitlari kerak")
    try:
        kdf = data.get("kdf_iter")
        if isinstance(kdf, bool) or not isinstance(kdf, int) or not KDF_MIN <= kdf <= KDF_MAX:
            raise ValueError
        return {"ecdh_pub": e2ee.check_pub(data.get("ecdh_pub")), "sign_pub": e2ee.check_pub(data.get("sign_pub")),
                "key_blob": e2ee.check_key_blob(data.get("key_blob")), "kdf_iter": kdf}
    except (ValueError, TypeError):
        raise bad("E2EE kalitlari noto'g'ri")


def check_auth(secret: str) -> str:
    if not isinstance(secret, str) or not AUTH_RE.match(secret):
        raise bad("Parol shifrlangan ko'rinishda yuborilishi kerak (brauzer buni o'zi bajaradi)")
    return secret


def kdf_params(username: str) -> dict:
    """Kirishdan oldin: mijoz parolni qanday qayta ishlashini biladi. Noma'lum username uchun ham bir xil shakl."""
    u = users.get_by_username(username or "") if isinstance(username, str) else None
    if u and not u["deleted"]:
        return {"auth_v": int(u["auth_v"] or 0), "kdf_iter": int(u["kdf_iter"] or KDF_DEFAULT)}
    return {"auth_v": 1, "kdf_iter": KDF_DEFAULT}


def own_info(user) -> dict:
    """Foydalanuvchining O'Z kalit ma'lumoti (login javobida): parol bilan o'ralgan maxfiy kalitlar serverdan
    ochilmaydi — ularni faqat foydalanuvchi parolidan hosil bo'lgan kalit ocha oladi."""
    return {"auth_v": int(user["auth_v"] or 0), "kdf_iter": user["kdf_iter"], "ecdh_pub": user["ecdh_pub"],
            "sign_pub": user["sign_pub"], "key_blob": user["key_blob"]}


def upgrade_legacy(user, old_password: str, new_auth: str, keys) -> None:
    """Eski (ochiq parol serverga kelgan) akkauntni E2EE'ga o'tkazadi: parol hash'i endi mijoz hosil qilgan kalitdan."""
    if int(user["auth_v"] or 0) != 0:
        raise bad("Akkaunt allaqachon E2EE'da", 409)
    if not verify_password(old_password or "", user["password_hash"]):
        raise ChatError("Parol noto'g'ri", 403)
    k = validate_account_keys(keys)
    users.set_e2ee(user["id"], hash_password(check_auth(new_auth)), k)


def public_keys(ids) -> dict:
    out = {}
    for r in users.key_rows([i for i in ids if isinstance(i, int) and not isinstance(i, bool)][:500]):
        if r["ecdh_pub"] and r["sign_pub"]:
            out[str(r["id"])] = {"e": r["ecdh_pub"], "s": r["sign_pub"]}
    return out


# ----------------------------------------------------------------------------------------------- guruh kaliti
def _need_keys(user) -> None:
    if not user["ecdh_pub"]:
        raise bad("Avval E2EE kalitlaringiz yaratilishi kerak", 409)


def room_state(user) -> dict:
    return {
        "epoch": repo.current_epoch(),
        "epochs": [{"epoch": r["epoch"], "check": r["check_blob"], "by": r["created_by"], "ts": r["created_at"],
                    "reason": r["reason"] or ""} for r in repo.epochs()],
        "mine": [{"epoch": r["epoch"], "wrapped": r["wrapped"], "by": r["wrapper_id"], "ts": r["created_at"]}
                 for r in repo.keys_for(user["id"])],
    }


def _clean_wraps(raw, allowed: set[int]) -> list[tuple[int, str]]:
    if not isinstance(raw, list) or len(raw) > MAX_WRAPS:
        raise bad()
    out, seen = [], set()
    for w in raw:
        if not isinstance(w, dict) or isinstance(w.get("user_id"), bool) or not isinstance(w.get("user_id"), int):
            raise bad()
        uid = w["user_id"]
        if uid not in allowed or uid in seen:
            continue                                 # banlangan/o'chirilgan/kalitsiz yoki takror: jimgina o'tkazib yuboriladi
        try:
            out.append((uid, e2ee.check_wrap(w.get("wrapped"))))
        except ValueError:
            raise bad()
        seen.add(uid)
    return out


def _active_keyed() -> set[int]:
    return {r["id"] for r in users.keyed_active()}


def room_init(user, check: str, wraps) -> int:
    """Birinchi guruh kalitini (epoch 1) yaratadi. Poyga: birinchi kelgan so'rov g'olib, qolganlari 409 oladi."""
    _need_keys(user)
    limiter.check(f"e2e-room:{user['id']}", 20, 60, "Juda tez-tez so'raldi")
    try:
        check = e2ee.check_epoch_check(check)
    except (ValueError, TypeError):
        raise bad()
    ws = _clean_wraps(wraps, _active_keyed())
    if user["id"] not in {u for u, _ in ws}:
        raise bad("Kalit o'zingiz uchun ham o'ralgan bo'lishi kerak")
    if not repo.create_epoch(1, user["id"], check, ws, "init"):
        raise ChatError("Guruh kaliti allaqachon yaratilgan", 409)
    return 1


def room_rotate(admin, from_epoch, check: str, wraps, reason: str = "rotate") -> int:
    """Kalitni yangilash (masalan, ban qilinganidan keyin): faqat adminlar; eski avlod bo'yicha bitta g'olib."""
    if not is_admin(admin):
        raise ChatError("Kalitni faqat adminlar yangilay oladi", 403)
    _need_keys(admin)
    cur = repo.current_epoch()
    if isinstance(from_epoch, bool) or from_epoch != cur or cur < 1:
        raise ChatError("Guruh kaliti allaqachon yangilangan", 409)
    try:
        check = e2ee.check_epoch_check(check)
    except (ValueError, TypeError):
        raise bad()
    ws = _clean_wraps(wraps, _active_keyed())
    if admin["id"] not in {u for u, _ in ws}:
        raise bad("Kalit o'zingiz uchun ham o'ralgan bo'lishi kerak")
    if not repo.create_epoch(cur + 1, admin["id"], check, ws, (reason or "rotate")[:20]):
        raise ChatError("Guruh kaliti allaqachon yangilangan", 409)
    return cur + 1


def room_wrap(user, epoch, wraps) -> list[int]:
    """Kaliti bor a'zo, hali kalit olmagan yangi a'zolar uchun uni ularning ommaviy kaliti bilan o'rab qo'shadi."""
    _need_keys(user)
    limiter.check(f"e2e-wrap:{user['id']}", 60, 60, "Juda tez-tez so'raldi")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1 or epoch > repo.current_epoch():
        raise bad("Epoch topilmadi", 404)
    return repo.add_wraps(epoch, user["id"], _clean_wraps(wraps, _active_keyed()))


def room_missing() -> list[dict]:
    return [{"epoch": r["epoch"], "user_id": r["user_id"], "ecdh_pub": r["ecdh_pub"]} for r in repo.missing(200)]


def drop_own_wrap(user, epoch: int) -> None:
    repo.drop_own_wrap(epoch, user["id"])


# ----------------------------------------------------------------------------------------------- inspektor
KNOWS = {
    "biladi": [
        "Kim yozgani (username), qachon, qaysi suhbatda (umumiy chat yoki qaysi ikki kishi orasida)",
        "Konvert hajmi va fayl hajmi (shifrlangan bayt soni), xabar tahrirlangan/o'chirilganmi",
        "IP manzilingiz, qachon kirgan/chiqqaningiz, onlayn holatingiz",
        "Ommaviy kalitlaringiz va parolingiz bilan o'ralgan (ochib bo'lmaydigan) maxfiy kalit zaxirangiz",
    ],
    "bilmaydi": [
        "Xabar matni — u faqat qurilmangizda shifrlanadi va faqat qabul qiluvchi qurilmasida ochiladi",
        "Fayl mazmuni, fayl nomi va turi, rasm ko'rinishi (hammasi qurilmada shifrlanadi)",
        "Guruh kaliti va maxfiy kalitlaringiz (serverda ularni ochadigan hech narsa yo'q)",
        "Parolingiz (serverga faqat parolingizdan olingan, qaytarib bo'lmaydigan kirish kaliti keladi)",
        "Qaysi xabarga javob berilgani (javob ham shifr ichida)",
    ],
}


def _row_view(r, viewer_id: int) -> dict:
    u = users.get(r["user_id"])
    raw = r["content"] or ""
    is_e2e = bool(r["e2e"])
    return {
        "id": r["id"], "from": u["username"] if u else "?", "from_id": r["user_id"], "to": r["recipient_id"],
        "ts": r["created_at"], "edited": bool(r["edited_at"]), "deleted": bool(r["deleted"]),
        "e2e": is_e2e,
        "stored": raw if is_e2e else crypto.preview(raw, 120),        # bazada AYNAN shu yotadi
        "stored_bytes": len(raw.encode("utf-8")),
        "meta": e2ee.describe(raw) if is_e2e else None,
        "admin_sees": crypto.admin_view(raw),                          # admin panelida AYNAN shu ko'rinadi
        "blob_bytes": (r["file_size"] or 0) if r["file"] else 0,
        "mine": r["user_id"] == viewer_id,
    }


def server_view(user, partner: int | None, limit: int = 8) -> dict:
    """"Server nimani ko'radi": joriy suhbat bo'yicha bazadagi qatorlar (o'zgartirilmagan), o'zingiz haqingizdagi yozuvlar."""
    limit = max(1, min(int(limit or 8), 20))
    if partner is None:
        rows = messages.raw_group(limit)
    else:
        if users.get(partner) is None:
            raise ChatError("Foydalanuvchi topilmadi", 404)
        rows = messages.raw_dm(user["id"], partner, limit)
    mine_wrap = next((r for r in repo.keys_for(user["id"]) if r["epoch"] == repo.current_epoch()), None)
    acts = []
    for a in activity_repo.query(user=user["username"], limit=6):
        acts.append({"ts": a["created_at"], "ip": a["ip"] or "", "action": a["action"], "detail": public_detail(a["action"], a["detail"])})
    return {
        "scope": "group" if partner is None else "dm",
        "rows": [_row_view(r, user["id"]) for r in rows],
        "me": {"auth_v": int(user["auth_v"] or 0), "ecdh_pub": user["ecdh_pub"], "sign_pub": user["sign_pub"],
               "key_blob": user["key_blob"], "key_blob_bytes": len(user["key_blob"] or "")},
        "room": {"epoch": repo.current_epoch(),
                 "my_wrap": ({"epoch": mine_wrap["epoch"], "wrapped": mine_wrap["wrapped"], "by": mine_wrap["wrapper_id"]}
                             if mine_wrap else None),
                 "wrap_log": [{"epoch": r["epoch"], "user_id": r["user_id"], "by": r["wrapper_id"], "ts": r["created_at"]}
                              for r in repo.wrap_log(30)]},
        "knows": KNOWS,
        "legacy_messages": messages.legacy_count(),
        "activity": acts,
        "server_can_decrypt": False,
        "require_e2ee": settings.require_e2ee,
    }


_ID_HEAD = re.compile(r"^(#\d+)")
SNIPPET_ACTIONS = {"msg", "edit", "delete", "image", "file"}


def public_detail(action: str, detail: str | None) -> str:
    """Eski yozuvlarda xabar matnidan parcha bo'lishi mumkin: adminlarga ham, inspektorga ham matn ko'rsatilmaydi."""
    if not detail or action not in SNIPPET_ACTIONS:
        return detail or ""
    m = _ID_HEAD.match(detail)
    return (m.group(1) + " " if m else "") + "(matn yashirildi)"
