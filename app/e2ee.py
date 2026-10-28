"""E2EE (uchdan-uchga shifrlash): konvert formati va kalitlarni FAQAT tekshirish.

Muhim: bu modul hech qachon xabarni OCHMAYDI — serverda guruh kaliti ham, foydalanuvchining maxfiy kaliti ham yo'q.
Server faqat konvertning *shakli* to'g'riligini (ochiq matn emas, o'lcham chegarasi, to'g'ri epoch) tekshiradi.

Konvert:   "e2e1:" + base64url( JSON {"v":1, "k":"g"|"d", "ep":<guruh kaliti avlodi|0>, "n":<iv>, "c":<shifr>, "s":<imzo>} )
  * shifr  — AES-256-GCM (guruh kaliti yoki ikki kishining ECDH kaliti), AAD = "ac/e2e1|<xona>|<yuboruvchi id>|<epoch>"
  * imzo   — ECDSA P-256 / SHA-256 (r||s, 64 bayt), yuboruvchining imzo kaliti bilan: AAD || iv || shifr ustidan
To'liq protokol: README.md → "E2EE protokoli" bo'limi va app/static/js/e2ee.js.
"""
from __future__ import annotations

import base64
import binascii
import json

from cryptography.hazmat.primitives.asymmetric import ec

PREFIX = "e2e1:"
IV_LEN, SIG_LEN, TAG_LEN = 12, 64, 16
WRAP_LEN = IV_LEN + 32 + TAG_LEN                    # o'ralgan guruh kaliti: iv | AES-GCM(32 bayt kalit) | teg
MAX_KEY_BLOB = 4096


def b64u_decode(s: str) -> bytes:
    if not isinstance(s, str) or not s or len(s) > 400_000:
        raise ValueError("b64")
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (binascii.Error, ValueError):
        raise ValueError("b64")


def b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def is_envelope(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def parse_envelope(value, max_len: int) -> dict:
    """Konvert shaklini tekshiradi. ValueError — shakl noto'g'ri. Qaytadi: {"k","ep","iv","ct_len","sig_len"}."""
    if not is_envelope(value) or len(value) > max_len:
        raise ValueError("konvert")
    try:
        obj = json.loads(b64u_decode(value[len(PREFIX):]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("konvert")
    if not isinstance(obj, dict) or set(obj) != {"v", "k", "ep", "n", "c", "s"} or obj["v"] != 1:
        raise ValueError("konvert")
    k, ep = obj["k"], obj["ep"]
    if k not in ("g", "d") or isinstance(ep, bool) or not isinstance(ep, int) or ep < 0 or ep > 10**9:
        raise ValueError("konvert")
    if (k == "g") != (ep >= 1):
        raise ValueError("konvert")
    iv, ct, sig = b64u_decode(obj["n"]), b64u_decode(obj["c"]), b64u_decode(obj["s"])
    if len(iv) != IV_LEN or len(sig) != SIG_LEN or len(ct) < TAG_LEN + 2:
        raise ValueError("konvert")
    return {"k": k, "ep": ep, "iv": obj["n"], "ct_len": len(ct), "sig_len": len(sig)}


def describe(value) -> dict | None:
    """Admin/inspektor uchun: konvertning OCHIQ metama'lumoti (matn emas!). Konvert bo'lmasa None."""
    try:
        h = parse_envelope(value, 10**7)
    except ValueError:
        return None
    return {"kind": "guruh" if h["k"] == "g" else "lichka", "epoch": h["ep"], "iv": h["iv"],
            "cipher_bytes": h["ct_len"], "sig_bytes": h["sig_len"]}


def check_pub(value) -> str:
    """Ommaviy kalit: P-256 nuqtasi (65 bayt, siqilmagan), egri chiziqda yotishi tekshiriladi. Qiymatni qaytaradi."""
    raw = b64u_decode(value)
    if len(raw) != 65 or raw[0] != 4:
        raise ValueError("kalit")
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError:
        raise ValueError("kalit")
    return value


def check_wrap(value) -> str:
    if len(b64u_decode(value)) != WRAP_LEN:
        raise ValueError("o'ralgan kalit")
    return value


def check_epoch_check(value) -> str:
    if not 24 <= len(b64u_decode(value)) <= 128:
        raise ValueError("tekshiruv")
    return value


def check_key_blob(value) -> str:
    """Parol bilan o'ralgan maxfiy kalitlar (JSON {"v":1,"n":iv,"c":shifr}); server uni ocha olmaydi."""
    if not isinstance(value, str) or len(value) > MAX_KEY_BLOB:
        raise ValueError("kalit zaxirasi")
    try:
        obj = json.loads(value)
        if not isinstance(obj, dict) or set(obj) != {"v", "n", "c"} or obj["v"] != 1:
            raise ValueError
        if len(b64u_decode(obj["n"])) != IV_LEN or len(b64u_decode(obj["c"])) < 64:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("kalit zaxirasi")
    return value
