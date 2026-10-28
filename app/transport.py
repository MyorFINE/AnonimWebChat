"""Ilova darajasidagi shifrlangan kanal (TLS ustiga qo'shimcha qatlam).

Qo'l siqish (POST /api/handshake): brauzer va server ECDH P-256 kalit almashadi, HKDF-SHA256 bilan ikkita
AES-256-GCM kalit hosil bo'ladi (c2s va s2c). Shundan so'ng:

  * HTTP: har bir so'rov BITTA manzilga (POST /api/x) ketadi, tanasi shifrlangan. Haqiqiy metod, yo'l,
    so'rov parametrlari, token va tana shifr ichida. Javob ham shifrlangan. Wireshark / DevTools faqat
    `iv|ciphertext` ni ko'radi.
  * WebSocket: har bir kadr shifrlangan (base64). Token URL'da emas, birinchi shifrlangan kadrda.
  * Rasmlar (/uploads, /avatars) ham shu kanal orqali olinadi.

Eslatma: bu faqat KANAL qatlami (server uni ochadi). Xabar mazmunini himoyalovchi uchdan-uchga shifrlash (E2EE) alohida,
xabar konverti ichida: app/e2ee.py va app/static/js/e2ee.js. Kanal tarmoq tinglovchisidan, E2EE esa serverdan ham himoya qiladi.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import time
from collections import OrderedDict
from types import SimpleNamespace
from urllib.parse import unquote

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.config import settings
from app.netutil import real_ip
from app.security import limiter

log = logging.getLogger("termchat.transport")

TUNNEL_PATH = "/api/x"
HANDSHAKE_PATH = "/api/handshake"
ALLOWED_PREFIXES = ("/api/", "/uploads/", "/avatars/")
STATIC_GET_PREFIXES = ("/uploads/", "/avatars/")
METHODS = {"GET", "POST", "PATCH", "PUT", "DELETE"}

AAD_REQ, AAD_RES = b"termchat/v1/http-req", b"termchat/v1/http-res"
AAD_WS_C2S, AAD_WS_S2C = b"termchat/v1/ws-c2s", b"termchat/v1/ws-s2c"

MAX_BODY = settings.max_media_bytes + 4 * 1024 * 1024     # shifrlangan so'rov tanasi chegarasi (fayl + multipart/shifr qo'shimchasi)
SESSION_TTL = 24 * 3600
MAX_SESSIONS = 5000
CLOCK_SKEW = 300                      # soniya
REPLAY_WINDOW = 2 * CLOCK_SKEW


class CryptoSession:
    __slots__ = ("kid", "up", "down", "created", "last", "seen")

    def __init__(self, kid: str, key_c2s: bytes, key_s2c: bytes):
        self.kid = kid
        self.up = AESGCM(key_c2s)       # mijoz -> server (ochish)
        self.down = AESGCM(key_s2c)     # server -> mijoz (yopish)
        self.created = self.last = time.time()
        self.seen: dict[bytes, float] = {}

    def check_fresh(self, iv: bytes, ts_ms) -> None:
        """Eski yoki takrorlangan so'rovni rad etadi (replay himoyasi)."""
        now = time.time()
        if not isinstance(ts_ms, (int, float)) or abs(now - ts_ms / 1000.0) > CLOCK_SKEW:
            raise ValueError("vaqt mos emas")
        if len(self.seen) > 2000:
            self.seen = {k: v for k, v in self.seen.items() if v > now}
        if iv in self.seen:
            raise ValueError("takroriy so'rov")
        self.seen[iv] = now + REPLAY_WINDOW


class SessionStore:
    def __init__(self) -> None:
        self._s: OrderedDict[str, CryptoSession] = OrderedDict()

    def create(self, client_pub: bytes) -> tuple[CryptoSession, bytes]:
        peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), client_pub)   # ValueError: noto'g'ri nuqta
        priv = ec.generate_private_key(ec.SECP256R1())
        server_pub = priv.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        shared = priv.exchange(ec.ECDH(), peer)
        salt = client_pub + server_pub

        def derive(info: bytes) -> bytes:
            return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(shared)

        sess = CryptoSession(secrets.token_urlsafe(18), derive(b"termchat/v1/c2s"), derive(b"termchat/v1/s2c"))
        self._s[sess.kid] = sess
        while len(self._s) > MAX_SESSIONS:
            self._s.popitem(last=False)
        return sess, server_pub

    def get(self, kid: str) -> CryptoSession | None:
        s = self._s.get(kid)
        if s is None:
            return None
        if time.time() - s.created > SESSION_TTL:
            self._s.pop(kid, None)
            return None
        s.last = time.time()
        self._s.move_to_end(kid)
        return s


store = SessionStore()


# ----------------------------------------------------------------------------------- paket formati
def _split(plain: bytes) -> tuple[dict, bytes]:
    i = plain.find(b"\n")
    if i < 0:
        raise ValueError("format")
    meta = json.loads(plain[:i].decode("utf-8"))
    if not isinstance(meta, dict):
        raise ValueError("format")
    return meta, plain[i + 1:]


def open_request(sess: CryptoSession, blob: bytes) -> tuple[dict, bytes]:
    if len(blob) < 12 + 16:
        raise ValueError("qisqa")
    iv, ct = blob[:12], blob[12:]
    meta, body = _split(sess.up.decrypt(iv, ct, AAD_REQ))
    sess.check_fresh(iv, meta.get("t"))
    return meta, body


def seal_response(sess: CryptoSession, status: int, content_type: str, body: bytes) -> bytes:
    meta = json.dumps({"s": status, "c": content_type}, separators=(",", ":")).encode()
    iv = secrets.token_bytes(12)
    return iv + sess.down.encrypt(iv, meta + b"\n" + body, AAD_RES)


# ----------------------------------------------------------------------------------- ASGI middleware
def _hdrs(scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def _client_ip(scope) -> str:
    c = scope.get("client")
    return real_ip(_hdrs(scope), SimpleNamespace(host=c[0]) if c else None)


async def _respond(send, status: int, body: bytes, ctype: str) -> None:
    await send({"type": "http.response.start", "status": status, "headers": [
        (b"content-type", ctype.encode()), (b"content-length", str(len(body)).encode()),
        (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]})
    await send({"type": "http.response.body", "body": body})


async def _json(send, status: int, obj: dict) -> None:
    await _respond(send, status, json.dumps(obj).encode(), "application/json")


async def _read(receive, limit: int) -> bytes | None:
    chunks, size = [], 0
    while True:
        m = await receive()
        if m["type"] == "http.disconnect":
            return None
        chunk = m.get("body", b"")
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
        if not m.get("more_body"):
            return b"".join(chunks)


class TunnelMiddleware:
    """Eng tashqi ASGI qatlami: shifrlangan so'rovni ochib, ichki ilovaga oddiy so'rov sifatida beradi."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path, method = scope["path"], scope["method"]
            if path == HANDSHAKE_PATH and method == "POST":
                return await self._handshake(scope, receive, send)
            if path == TUNNEL_PATH and method == "POST":
                return await self._tunnel(scope, receive, send)
            if settings.require_tunnel and path.startswith(ALLOWED_PREFIXES):
                return await _json(send, 403, {"detail": "Faqat shifrlangan kanal orqali"})
        await self.app(scope, receive, send)

    async def _handshake(self, scope, receive, send):
        if not limiter.allow(f"hs:{_client_ip(scope)}", 40, 60):
            return await _json(send, 429, {"detail": "Juda ko'p urinish"})
        body = await _read(receive, 1024)
        try:
            pub = base64.b64decode(json.loads(body or b"{}")["pub"], validate=True)
            if len(pub) != 65 or pub[0] != 4:
                raise ValueError
            sess, server_pub = store.create(pub)
        except Exception:
            return await _json(send, 400, {"detail": "Noto'g'ri qo'l siqish"})
        await _json(send, 200, {"kid": sess.kid, "pub": base64.b64encode(server_pub).decode(), "ttl": SESSION_TTL})

    async def _tunnel(self, scope, receive, send):
        sess = store.get(_hdrs(scope).get("x-kid", ""))
        if sess is None:
            return await _json(send, 428, {"detail": "rekey"})
        blob = await _read(receive, MAX_BODY)
        if blob is None:
            return await _json(send, 413, {"detail": "So'rov juda katta"})
        try:
            meta, inner_body = open_request(sess, blob)
            method = str(meta.get("m", "")).upper()
            target = str(meta.get("p", ""))
            path, _, query = target.partition("?")
            upath = unquote(path)
            if (method not in METHODS or not upath.startswith(ALLOWED_PREFIXES) or ".." in upath or "\x00" in upath
                    or upath in (TUNNEL_PATH, HANDSHAKE_PATH)
                    or (upath.startswith(STATIC_GET_PREFIXES) and method != "GET")):
                raise ValueError("yo'l")
            ctype, token = meta.get("c") or "", meta.get("a") or ""
            if not isinstance(ctype, str) or not isinstance(token, str) or any(c in ctype + token for c in "\r\n"):
                raise ValueError("sarlavha")
        except (InvalidTag, ValueError, KeyError, UnicodeDecodeError, TypeError):
            return await _json(send, 400, {"detail": "Shifrni ochib bo'lmadi"})

        headers = [(k, v) for k, v in scope["headers"]
                   if k not in (b"content-type", b"content-length", b"authorization", b"x-kid", b"cookie")]
        if ctype:
            headers.append((b"content-type", ctype.encode("latin-1", "ignore")))
        headers.append((b"content-length", str(len(inner_body)).encode()))
        if token:
            headers.append((b"authorization", b"Bearer " + token.encode("latin-1", "ignore")))
        inner = dict(scope)
        inner.update(method=method, path=upath, raw_path=path.encode("utf-8"),
                     query_string=query.encode("utf-8"), headers=headers, extensions={},
                     state={**(scope.get("state") or {}), "tunnel": True})

        sent_body = False
        never = asyncio.Event()

        async def inner_receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": inner_body, "more_body": False}
            await never.wait()                # javob tugaguncha "uzilish" signali yubormaymiz

        status, rheaders, chunks = 500, [], []

        async def inner_send(msg):
            nonlocal status, rheaders
            if msg["type"] == "http.response.start":
                status, rheaders = msg["status"], msg.get("headers", [])
            elif msg["type"] == "http.response.body":
                chunks.append(msg.get("body", b""))

        try:
            await self.app(inner, inner_receive, inner_send)
        except Exception:
            log.exception("Ichki so'rov xatosi: %s %s", method, upath)
            if not chunks:
                status, rheaders, chunks = 500, [(b"content-type", b"application/json")], [b'{"detail":"Server xatosi"}']
        rtype = next((v.decode("latin-1") for k, v in rheaders if k.lower() == b"content-type"), "application/octet-stream")
        await _respond(send, 200, seal_response(sess, status, rtype, b"".join(chunks)), "application/octet-stream")


# ----------------------------------------------------------------------------------- WebSocket
class SecureWS:
    """Starlette WebSocket ustidan: har bir matn kadrini shifrlaydi/ochadi. Ulanishlar menejeri bilan mos
    (`send_text`, `close`)."""

    def __init__(self, ws, sess: CryptoSession):
        self.raw, self._sess = ws, sess
        self._prefix = secrets.token_bytes(4)
        self._tx = 0
        self._rx_prefix: bytes | None = None
        self._rx = -1
        self._lock = asyncio.Lock()

    async def send_text(self, text: str) -> None:
        async with self._lock:              # tartib va hisoblagich buzilmasligi uchun
            self._tx += 1
            iv = self._prefix + self._tx.to_bytes(8, "big")
            ct = self._sess.down.encrypt(iv, text.encode("utf-8"), AAD_WS_S2C)
            await self.raw.send_text(base64.b64encode(iv + ct).decode("ascii"))

    async def receive_text(self) -> str:
        blob = base64.b64decode(await self.raw.receive_text(), validate=True)
        if len(blob) < 12 + 16:
            raise ValueError("qisqa kadr")
        iv, ct = blob[:12], blob[12:]
        prefix, ctr = iv[:4], int.from_bytes(iv[4:], "big")
        if self._rx_prefix is None:
            self._rx_prefix = prefix
        if prefix != self._rx_prefix or ctr <= self._rx:
            raise ValueError("takroriy kadr")
        text = self._sess.up.decrypt(iv, ct, AAD_WS_C2S).decode("utf-8")
        self._rx = ctr
        return text

    async def close(self, code: int = 1000) -> None:
        await self.raw.close(code)
