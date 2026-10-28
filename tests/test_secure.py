"""Shifrlash testlari: bazada shifr (at-rest), shifrlangan kanal (tunnel/WebSocket). FastAPI talab qilinmaydi."""
import asyncio
import base64
import json
import secrets

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app import crypto, transport
from app.config import settings
from app.db import db
from app.repositories import logs, messages, users
from app.services import auth, chat


@pytest.fixture(scope="module")
def alice():
    token, me = auth.register("sec_alice", "Alice", "secret12")
    return users.get(me["id"])


# ------------------------------------------------------------------ bazada shifrlash
def test_message_text_is_encrypted_in_db_but_readable_through_repo(alice):
    m = chat.post(alice, "maxfiy salom 123")
    raw = db.one("SELECT content FROM messages WHERE id=?", (m["id"],))["content"]
    assert raw.startswith(crypto.PREFIX) and "maxfiy" not in raw
    assert chat.history()[-1]["content"] == "maxfiy salom 123"
    assert messages.get(m["id"])["content"] == "maxfiy salom 123"


def test_edit_and_delete_logs_are_sealed_and_decoded_for_admin(alice):
    m = chat.post(alice, "birinchi matn")
    chat.edit(alice, m["id"], "ikkinchi matn")
    chat.delete(alice, m["id"])
    rows = db.all("SELECT old_content, new_content FROM logs WHERE message_id=?", (m["id"],))
    blob = " ".join((r["old_content"] or "") + (r["new_content"] or "") for r in rows)
    assert "birinchi" not in blob and "ikkinchi" not in blob and crypto.PREFIX in blob
    hist = logs.for_messages([m["id"]])
    assert [(h["type"], h["old_content"], h["new_content"]) for h in hist] == [
        ("edit", "birinchi matn", "ikkinchi matn"), ("delete", "ikkinchi matn", None)]
    # o'chirilgan xabar ham bazada shifrlangan holda qoladi va admin uchun ochiladi
    assert crypto.open_(messages.group_page(0, 500)[0]["content"], "msg") is not None


def test_ciphertext_cannot_be_moved_between_columns():
    blob = crypto.seal("sir", "msg")
    assert crypto.open_(blob, "msg") == "sir"
    assert crypto.open_(blob, "act") == crypto.BROKEN


def test_legacy_plaintext_rows_are_migrated(alice):
    mid = db.run("INSERT INTO messages(user_id,content,created_at) VALUES(?,?,?)", (alice["id"], "eski ochiq matn", 1.0))
    assert crypto.migrate_legacy(db) >= 1
    assert db.one("SELECT content FROM messages WHERE id=?", (mid,))["content"].startswith(crypto.PREFIX)
    assert messages.get(mid)["content"] == "eski ochiq matn"


# ------------------------------------------------------------------ shifrlangan kanal (Python mijoz)
class Client:
    """JS mijozning (crypto.js) Python nusxasi."""

    def __init__(self, kid, up, down):
        self.kid, self.up, self.down = kid, AESGCM(up), AESGCM(down)

    @classmethod
    def connect(cls):
        priv = ec.generate_private_key(ec.SECP256R1())
        pub = priv.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        sess, spub = transport.store.create(pub)
        shared = priv.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), spub))
        d = lambda info: HKDF(algorithm=hashes.SHA256(), length=32, salt=pub + spub, info=info).derive(shared)
        return cls(sess.kid, d(b"termchat/v1/c2s"), d(b"termchat/v1/s2c"))

    def request(self, method, path, body=b"", token=None, ts=None):
        import time
        meta = json.dumps({"t": ts if ts is not None else int(time.time() * 1000), "m": method, "p": path, "a": token, "c": None})
        iv = secrets.token_bytes(12)
        return iv + self.up.encrypt(iv, meta.encode() + b"\n" + body, transport.AAD_REQ)

    def open_response(self, blob):
        plain = self.down.decrypt(blob[:12], blob[12:], transport.AAD_RES)
        i = plain.index(b"\n")
        return json.loads(plain[:i]), plain[i + 1:]


async def _echo(scope, receive, send):
    body = b""
    while True:
        m = await receive()
        body += m.get("body", b"")
        if not m.get("more_body"):
            break
    auth_h = dict(scope["headers"]).get(b"authorization", b"").decode()
    out = json.dumps({"path": scope["path"], "auth": auth_h, "body": body.decode()}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": out})


def _call(app, path, headers, body, method="POST"):
    async def go():
        sent, first = [], [True]

        async def receive():
            if first[0]:
                first[0] = False
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.sleep(60)

        async def send(m):
            sent.append(m)

        await app({"type": "http", "method": method, "path": path, "raw_path": path.encode(), "query_string": b"",
                   "headers": headers, "client": ("203.0.113.5", 1), "state": {}}, receive, send)
        return sent[0]["status"], b"".join(m.get("body", b"") for m in sent[1:])
    return asyncio.run(go())


def test_tunnel_hides_path_token_and_body_and_blocks_replay():
    app = transport.TunnelMiddleware(_echo)
    c = Client.connect()
    pkt = c.request("POST", "/api/login", b'{"password":"hech kim ko\'rmasin"}', token="TOKEN-XYZ")
    assert b"login" not in pkt and b"TOKEN-XYZ" not in pkt and b"password" not in pkt
    st, out = _call(app, "/api/x", [(b"x-kid", c.kid.encode())], pkt)
    assert st == 200
    meta, body = c.open_response(out)
    got = json.loads(body)
    assert meta["s"] == 200 and got["path"] == "/api/login" and got["auth"] == "Bearer TOKEN-XYZ" and "hech kim" in got["body"]
    assert _call(app, "/api/x", [(b"x-kid", c.kid.encode())], pkt)[0] == 400            # replay
    bad = bytearray(c.request("GET", "/api/me")); bad[30] ^= 1
    assert _call(app, "/api/x", [(b"x-kid", c.kid.encode())], bytes(bad))[0] == 400     # buzilgan paket
    assert _call(app, "/api/x", [(b"x-kid", c.kid.encode())], c.request("GET", "/api/me", ts=1000))[0] == 400   # eski vaqt
    assert _call(app, "/api/x", [(b"x-kid", b"yo'q")], pkt)[0] == 428                   # sessiya yo'q -> qayta qo'l siqish
    assert _call(app, "/api/x", [(b"x-kid", c.kid.encode())], c.request("GET", "/api/x"))[0] == 400   # tunnel ichida tunnel yo'q
    assert _call(app, "/api/x", [(b"x-kid", c.kid.encode())], c.request("GET", "/healthz"))[0] == 400  # ruxsat etilmagan yo'l


def test_plain_api_access_is_refused_when_tunnel_required():
    app = transport.TunnelMiddleware(_echo)
    object.__setattr__(settings, "require_tunnel", True)
    try:
        assert _call(app, "/api/members", [], b"", "GET")[0] == 403
        assert _call(app, "/uploads/a.png", [], b"", "GET")[0] == 403
        assert _call(app, "/healthz", [], b"", "GET")[0] == 200
    finally:
        object.__setattr__(settings, "require_tunnel", False)


def test_secure_ws_frames_roundtrip_and_replay():
    class Raw:
        def __init__(self): self.out, self.inq = [], []
        async def send_text(self, t): self.out.append(t)
        async def receive_text(self): return self.inq.pop(0)
    c = Client.connect()
    raw = Raw()
    ws = transport.SecureWS(raw, transport.store.get(c.kid))

    def frame(n, text, prefix=b"ABCD"):
        iv = prefix + n.to_bytes(8, "big")
        return base64.b64encode(iv + c.up.encrypt(iv, text.encode(), transport.AAD_WS_C2S)).decode()

    async def go():
        await ws.send_text('{"type":"init"}')
        blob = base64.b64decode(raw.out[0])
        assert c.down.decrypt(blob[:12], blob[12:], transport.AAD_WS_S2C) == b'{"type":"init"}'
        assert "init" not in raw.out[0]
        raw.inq += [frame(1, '{"a":"tok"}'), frame(1, "takror"), frame(2, "salom", b"ZZZZ")]
        assert await ws.receive_text() == '{"a":"tok"}'
        for _ in range(2):                                   # takroriy hisoblagich va boshqa prefiks rad etiladi
            with pytest.raises(ValueError):
                await ws.receive_text()
    asyncio.run(go())
