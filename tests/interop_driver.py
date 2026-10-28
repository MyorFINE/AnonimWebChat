"""JS <-> Python E2EE mosligi (node kerak). pytest: test_e2ee.py ichida chaqiriladi; qo'lda: python interop_driver.py"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path
from cryptography.hazmat.primitives import serialization
import e2e_client as C

HERE = Path(__file__).parent

def run():
    d = Path(tempfile.mkdtemp())
    js = ["node", str(HERE / "e2e_js_interop.mjs")]
    subprocess.run(js + ["gen", str(d / "a.json")], check=True)
    j = json.loads((d / "a.json").read_text())
    kek, auth = C.derive("Alice", "secret-pass")
    assert auth == j["auth"]
    ident = C.Identity.unwrap(j["blob"], kek, "Alice")
    assert ident.ecdh_pub == j["idA"]["e"]
    idb = C.Identity(*(serialization.load_der_private_key(C.unb64u(j["bPkcs8"][k]), None) for k in ("e", "s")))
    rk = C.unwrap_room_key(idb, j["wrapped"], 1, 2, j["idA"]["e"], 1)
    assert C.verify_epoch_check(j["check"], rk, 1)
    assert C.open_(j["gEnv"], 1, None, rk, j["idA"]["s"])["t"] == "salom guruh 🌍"
    dk = C.dm_key(idb, j["idA"]["e"], 1, 2)
    assert C.open_(j["dEnv"], 1, 2, dk, j["idA"]["s"])["t"] == "lichka matni"
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    blob = C.unb64u(j["file"]["blob"])
    assert AESGCM(C.unb64u(j["file"]["key"])).decrypt(blob[:12], blob[12:], b"ac/blob/v1") == "fayl mazmuni".encode()
    # Python -> JS
    me = C.Identity(); peer_priv = ident                       # Alice (JS tomonda ochadi) = ident, yuboruvchi = me
    rk2 = __import__("secrets").token_bytes(32)
    out = {"auth": auth, "blob": j["blob"], "peer": {"e": me.ecdh_pub, "s": me.sign_pub}, "rk": C.b64u(rk2),
           "wrapped": C.wrap_room_key(me, rk2, 1, 1, ident.ecdh_pub, 2), "check": C.epoch_check(rk2, 1),
           "gEnv": C.seal(me, 1, None, 1, rk2, {"t": "py guruh"}),
           "dEnv": C.seal(me, 1, 2, 0, C.dm_key(me, ident.ecdh_pub, 1, 2), {"t": "py lichka"})}
    iv = b"\x01" * 12
    out["file"] = {"key": C.b64u(b"\x02" * 32), "blob": C.b64u(iv + AESGCM(b"\x02" * 32).encrypt(iv, "py fayl".encode(), b"ac/blob/v1"))}
    (d / "b.json").write_text(json.dumps(out))
    subprocess.run(js + ["check", str(d / "b.json")], check=True)
    shutil.rmtree(d)

if __name__ == "__main__":
    run(); print("interop OK")
