"""Testlar uchun: brauzer E2EE mijozining (app/static/js/e2ee.js) Python nusxasi. Protokol mosligi shu bilan tekshiriladi."""
import base64
import hashlib
import json
import secrets

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

U = serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
KDF_ITER = 100_000          # testlarda tez bo'lishi uchun (server 100k..3M ni qabul qiladi)


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def derive(username: str, password: str, iters: int = KDF_ITER):
    salt = hashlib.sha256(("anonim-chat/e2ee/v1/" + username.strip().lower()).encode()).digest()
    bits = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iters, 64)
    return bits[:32], bits[32:].hex()                      # (kek, auth)


class Identity:
    def __init__(self, ecdh=None, sign=None):
        self.ecdh = ecdh or ec.generate_private_key(ec.SECP256R1())
        self.sign = sign or ec.generate_private_key(ec.SECP256R1())

    @property
    def ecdh_pub(self) -> str:
        return b64u(self.ecdh.public_key().public_bytes(*U))

    @property
    def sign_pub(self) -> str:
        return b64u(self.sign.public_key().public_bytes(*U))

    def pkcs8(self, k):
        return k.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())

    def wrap(self, kek: bytes, username: str) -> str:
        iv = secrets.token_bytes(12)
        plain = json.dumps({"e": b64u(self.pkcs8(self.ecdh)), "s": b64u(self.pkcs8(self.sign))}).encode()
        ct = AESGCM(kek).encrypt(iv, plain, b"ac/keyblob/v1|" + username.strip().lower().encode())
        return json.dumps({"v": 1, "n": b64u(iv), "c": b64u(ct)})

    @classmethod
    def unwrap(cls, blob: str, kek: bytes, username: str):
        o = json.loads(blob)
        plain = AESGCM(kek).decrypt(unb64u(o["n"]), unb64u(o["c"]), b"ac/keyblob/v1|" + username.strip().lower().encode())
        j = json.loads(plain)
        load = lambda s: serialization.load_der_private_key(unb64u(s), None)
        return cls(load(j["e"]), load(j["s"]))

    def account_keys(self, kek: bytes, username: str, iters: int = KDF_ITER) -> dict:
        return {"ecdh_pub": self.ecdh_pub, "sign_pub": self.sign_pub, "key_blob": self.wrap(kek, username), "kdf_iter": iters}


def pub(b64: str):
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(b64))


def _hk(shared, salt, info):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(shared)


def dm_key(me: Identity, peer_ecdh_pub: str, a: int, b: int) -> bytes:
    return _hk(me.ecdh.exchange(ec.ECDH(), pub(peer_ecdh_pub)), f"ac/dm/v1|{min(a, b)}|{max(a, b)}".encode(), b"msg")


def aad(room: str, sender: int, ep: int) -> bytes:
    return f"ac/e2e1|{room}|{sender}|{ep}".encode()


def room_tag(a, b) -> str:
    return "g" if b is None else f"d:{min(a, b)}:{max(a, b)}"


def seal(me: Identity, sender: int, peer, ep: int, key: bytes, payload: dict) -> str:
    room, a = room_tag(sender, peer), aad(room_tag(sender, peer), sender, ep if peer is None else 0)
    ep = ep if peer is None else 0
    plain = json.dumps({**payload, "p": ""}, separators=(",", ":"), ensure_ascii=False).encode()
    pad = (64 - len(plain) % 64) % 64
    plain = json.dumps({**payload, "p": "0" * pad}, separators=(",", ":"), ensure_ascii=False).encode()
    iv = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(iv, plain, a)
    r, s = decode_dss_signature(me.sign.sign(a + iv + ct, ec.ECDSA(hashes.SHA256())))
    sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    body = {"v": 1, "k": "g" if peer is None else "d", "ep": ep, "n": b64u(iv), "c": b64u(ct), "s": b64u(sig)}
    return "e2e1:" + b64u(json.dumps(body, separators=(",", ":")).encode())


def open_(env: str, sender: int, peer, key: bytes, sender_sign_pub: str):
    o = json.loads(unb64u(env[5:]))
    a = aad(room_tag(sender, peer), sender, o["ep"])
    iv, ct, sig = unb64u(o["n"]), unb64u(o["c"]), unb64u(o["s"])
    pub(sender_sign_pub).verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
                                a + iv + ct, ec.ECDSA(hashes.SHA256()))
    return json.loads(AESGCM(key).decrypt(iv, ct, a))


def _wrap_key(me: Identity, peer_ecdh_pub: str, epoch: int, frm: int, to: int) -> bytes:
    return _hk(me.ecdh.exchange(ec.ECDH(), pub(peer_ecdh_pub)), f"ac/wrap/v1|{epoch}".encode(), f"{frm}|{to}".encode())


def wrap_room_key(me: Identity, room_key: bytes, epoch: int, frm: int, peer_ecdh_pub: str, to: int) -> str:
    iv = secrets.token_bytes(12)
    return b64u(iv + AESGCM(_wrap_key(me, peer_ecdh_pub, epoch, frm, to)).encrypt(iv, room_key, f"ac/wrap|{epoch}|{frm}|{to}".encode()))


def unwrap_room_key(me: Identity, wrapped: str, epoch: int, my_id: int, wrapper_ecdh_pub: str, wrapper_id: int) -> bytes:
    w = unb64u(wrapped)
    return AESGCM(_wrap_key(me, wrapper_ecdh_pub, epoch, wrapper_id, my_id)).decrypt(w[:12], w[12:], f"ac/wrap|{epoch}|{wrapper_id}|{my_id}".encode())


def epoch_check(room_key: bytes, epoch: int) -> str:
    iv = secrets.token_bytes(12)
    return b64u(iv + AESGCM(room_key).encrypt(iv, b"ok", f"ac/epoch|{epoch}".encode()))


def verify_epoch_check(check: str, room_key: bytes, epoch: int) -> bool:
    w = unb64u(check)
    try:
        return AESGCM(room_key).decrypt(w[:12], w[12:], f"ac/epoch|{epoch}".encode()) == b"ok"
    except Exception:
        return False
