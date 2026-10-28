"""Testlar uchun: brauzer mijozining (crypto.js) Python nusxasi — qo'l siqish, tunnel va shifrlangan WebSocket."""
import base64
import json
import secrets
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app import transport


class SecureClient:
    def __init__(self, kid, up, down):
        self.kid, self.up, self.down = kid, AESGCM(up), AESGCM(down)

    @classmethod
    def handshake(cls, http):
        """Haqiqiy /api/handshake endpointi orqali (TestClient)."""
        priv = ec.generate_private_key(ec.SECP256R1())
        pub = priv.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        r = http.post("/api/handshake", json={"pub": base64.b64encode(pub).decode()})
        assert r.status_code == 200, r.text
        j = r.json()
        spub = base64.b64decode(j["pub"])
        shared = priv.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), spub))
        d = lambda info: HKDF(algorithm=hashes.SHA256(), length=32, salt=pub + spub, info=info).derive(shared)
        return cls(j["kid"], d(b"termchat/v1/c2s"), d(b"termchat/v1/s2c"))

    # --- HTTP tunnel
    def call(self, http, method, path, *, json_body=None, token=None):
        body = json.dumps(json_body).encode() if json_body is not None else b""
        meta = json.dumps({"t": int(time.time() * 1000), "m": method, "p": path, "a": token,
                           "c": "application/json" if json_body is not None else None})
        iv = secrets.token_bytes(12)
        pkt = iv + self.up.encrypt(iv, meta.encode() + b"\n" + body, transport.AAD_REQ)
        r = http.post("/api/x", content=pkt, headers={"X-Kid": self.kid, "Content-Type": "application/octet-stream"})
        assert r.status_code == 200, r.text
        plain = self.down.decrypt(r.content[:12], r.content[12:], transport.AAD_RES)
        i = plain.index(b"\n")
        m = json.loads(plain[:i])
        return m["s"], plain[i + 1:]


class SecWS:
    """TestClient WebSocket ustida: Starlette sessiyasi bilan bir xil receive_json/send_json interfeysi."""

    def __init__(self, http, token):
        self.http, self.token = http, token
        self.sc = SecureClient.handshake(http)
        self._tx, self._pre = 0, secrets.token_bytes(4)

    def __enter__(self):
        self._cm = self.http.websocket_connect(f"/ws?k={self.sc.kid}")
        self.ws = self._cm.__enter__()
        self.send_json({"a": self.token})
        return self

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)

    def send_json(self, obj):
        self._tx += 1
        iv = self._pre + self._tx.to_bytes(8, "big")
        ct = self.sc.up.encrypt(iv, json.dumps(obj).encode(), transport.AAD_WS_C2S)
        self.ws.send_text(base64.b64encode(iv + ct).decode())

    def receive_json(self):
        blob = base64.b64decode(self.ws.receive_text())
        return json.loads(self.sc.down.decrypt(blob[:12], blob[12:], transport.AAD_WS_S2C))
