"""HTTP + WebSocket integratsion testlari (fastapi, httpx kerak)."""
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from secure_client import SecureClient, SecWS  # noqa: E402


def _real_png(size=(8, 8)):
    import io
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", size, (30, 120, 200)).save(b, "PNG"); return b.getvalue()

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def recv_where(ws, pred, limit=30):
    for _ in range(limit):
        m = ws.receive_json()
        if pred(m):
            return m
    raise AssertionError("kutilgan hodisa kelmadi")


def test_pages_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/static/js/app.js").status_code == 200
    csp = client.get("/").headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "object-src 'none'" in csp
    index = client.get("/").text
    assert 'integrity="sha384-' in index and "Anonim Chat by Hevorix" in index and "data-sri" not in index
    # ovozli xabar: skript SRI bilan beriladi, mikrofon FAQAT shu sayt uchun ochiq (boshqa ruxsatlar yopiq), media faqat self/blob
    assert client.get("/static/js/voice.js").status_code == 200 and "/static/js/voice.js?v=" in index
    pp = client.get("/").headers["permissions-policy"]
    assert "microphone=(self)" in pp and "camera=()" in pp and "geolocation=()" in pp
    assert "media-src 'self' blob:" in csp


def test_register_login_flow(client):
    r = client.post("/api/register", json={"username": "api_alice", "nickname": "A", "password": "secret12"})
    assert r.status_code == 200
    assert client.post("/api/register", json={"username": "API_ALICE", "nickname": "B", "password": "secret12"}).status_code == 409
    assert client.post("/api/login", json={"username": "api_alice", "password": "bad-pass"}).status_code == 401
    token = r.json()["token"]
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).json()["me"]["username"] == "api_alice"
    assert client.get("/api/me").status_code == 401


def test_websocket_chat_and_ban(client):
    a = client.post("/api/login", json={"username": "hevorix", "password": "owner-pass-1"}).json()["token"]
    b = client.post("/api/register", json={"username": "api_bob", "nickname": "B", "password": "secret12"}).json()["token"]
    with SecWS(client, a) as wa, SecWS(client, b) as wb:
        assert wa.receive_json()["type"] == "init"
        assert wb.receive_json()["type"] == "init"
        wb.send_json({"text": "salom"})
        assert recv_where(wa, lambda m: m["type"] == "message")["content"] == "salom"
        wa.send_json({"type": "cmd", "text": "/ban api_bob test"})
        assert recv_where(wb, lambda m: m["type"] == "banned")["reason"] == "test"
    assert client.post("/api/login", json={"username": "api_bob", "password": "secret12"}).status_code == 403


def test_avatar_upload_validation(client):
    t = client.post("/api/login", json={"username": "api_alice", "password": "secret12"}).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    png = _real_png()
    assert client.post("/api/avatar", headers=h, files={"file": ("a.png", png, "image/png")}).status_code == 200
    assert client.post("/api/avatar", headers=h, files={"file": ("a.png", b"not an image", "image/png")}).status_code == 400
    for _ in range(2):
        client.post("/api/avatar", headers=h, files={"file": ("a.png", png, "image/png")})
    assert client.post("/api/avatar", headers=h, files={"file": ("a.png", png, "image/png")}).status_code == 400   # 3 tadan oshdi


def test_direct_message_over_websocket(client):
    a = client.post("/api/login", json={"username": "api_alice", "password": "secret12"}).json()["token"]
    c = client.post("/api/register", json={"username": "api_carol", "nickname": "C", "password": "secret12"}).json()
    d = client.post("/api/register", json={"username": "api_dave", "nickname": "D", "password": "secret12"}).json()
    ha = {"Authorization": f"Bearer {a}"}
    hc = {"Authorization": f"Bearer {c['token']}"}
    with SecWS(client, a) as wa, \
         SecWS(client, c['token']) as wc, \
         SecWS(client, d['token']) as wd:
        for w in (wa, wc, wd):
            assert w.receive_json()["type"] == "init"
        wc.send_json({"type": "send", "text": "lichka", "to": client.get("/api/me", headers=ha).json()["me"]["id"]})
        got = recv_where(wa, lambda m: m["type"] == "message")
        assert got["content"] == "lichka" and got["user"]["username"] == "api_carol"
        assert recv_where(wc, lambda m: m["type"] == "message")["id"] == got["id"]     # yuboruvchiga ham keladi
        # uchinchi odam hech narsa olmaydi: umumiy xabar yuboramiz va faqat u kelishini tekshiramiz
        wa.send_json({"type": "send", "text": "hammaga"})
        assert recv_where(wd, lambda m: m["type"] == "message")["content"] == "hammaga"
        # o'qilgan deb belgilash
        wa.send_json({"type": "read", "with": got["user"]["id"]})
        assert recv_where(wc, lambda m: m["type"] == "read")["by"] == got["to"]
    hist = client.get(f"/api/dm/{got['user']['id']}", headers=ha).json()["history"]
    assert [h["content"] for h in hist] == ["lichka"] and hist[0]["read"] is True
    assert client.get(f"/api/dm/{got['to']}", headers={"Authorization": f"Bearer {d['token']}"}).json()["history"] == []
    assert client.get("/api/dialogs", headers=ha).json()["dialogs"][0]["user"]["username"] == "api_carol"
    members = client.get("/api/members", headers=hc).json()["members"]
    assert {"api_alice", "api_carol", "api_dave"} <= {m["username"] for m in members}


def test_profile_update_api(client):
    t = client.post("/api/login", json={"username": "api_alice", "password": "secret12"}).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    r = client.patch("/api/profile", headers=h, json={"nickname": "Alisa", "bio": "salom"})
    assert r.status_code == 200 and r.json()["me"]["nickname"] == "Alisa" and r.json()["me"]["bio"] == "salom"
    assert client.patch("/api/profile", headers=h, json={}).status_code == 400
    assert client.get("/api/avatars", headers=h).json()["max"] == 3


def _owner(client):
    t = client.post("/api/login", json={"username": "HEVORIX", "password": "owner-pass-1"}).json()["token"]
    return {"Authorization": f"Bearer {t}"}


def test_username_check_is_case_insensitive(client):
    for name in ("hevorix", "HEVORIX", "Hevorix"):
        assert client.get(f"/api/username/{name}").json() == {"available": False, "reason": "Bu username band"}
    assert client.get("/api/username/ozod_nom").json()["available"] is True
    assert client.post("/api/register", json={"username": "HeVoRiX", "nickname": "x", "password": "secret12"}).status_code == 409


def test_image_reply_color_over_http(client):
    h = _owner(client)
    png = _real_png()
    r = client.post("/api/messages/image", headers=h, files={"file": ("a.png", png, "image/png")}, data={"caption": "izoh"})
    assert r.status_code == 200
    mid = r.json()["id"]
    assert client.post("/api/messages/image", headers=h, files={"file": ("a.png", b"", "image/png")}).status_code == 400   # bo'sh fayl
    assert client.get("/uploads/nope.png", headers=h).status_code == 404
    assert client.get("/uploads/" + "a" * 32 + ".png").status_code == 401                                           # tizimga kirmagan — yo'q
    doc = client.post("/api/messages/media", headers=h, files={"file": ("hisobot.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert doc.status_code == 200
    with SecWS(client, h["Authorization"].split()[1]) as w:
        init = w.receive_json()
        img = [m for m in init["history"] if m["id"] == mid][0]
        assert img["image"].startswith("/uploads/") and img["content"] == "izoh"
        w.send_json({"type": "send", "text": "javob", "reply_to": mid})
        got = recv_where(w, lambda m: m["type"] == "message")
        assert got["reply"]["id"] == mid
    assert client.get(img["image"], headers=h).status_code == 200
    me = client.patch("/api/profile", headers=h, json={"color": "#22cc88"}).json()["me"]
    assert me["color"] == "#22cc88"
    bob = client.post("/api/login", json={"username": "api_alice", "password": "secret12"}).json()["token"]
    assert client.patch("/api/profile", headers={"Authorization": f"Bearer {bob}"}, json={"color": "#112233"}).status_code == 403


def test_admin_logs_and_ip_blocking(client):
    h = _owner(client)
    user_h = {"Authorization": "Bearer " + client.post("/api/login", json={"username": "api_alice", "password": "secret12"}).json()["token"]}
    assert client.get("/api/admin/ips", headers=user_h).status_code == 403          # oddiy foydalanuvchi kira olmaydi
    ips = client.get("/api/admin/ips", headers=h).json()["ips"]
    assert ips and any(p["username"].lower() == "hevorix" and p["logins"] >= 1 for e in ips for p in e["profiles"])
    log = client.get("/api/admin/activity?action=login", headers=h).json()
    assert log["items"] and all(i["action"] == "login" for i in log["items"])
    # begona IP'ni bloklash: keyin shu IP'dan so'rovlar rad etiladi
    assert client.post("/api/admin/blocks", headers=h, json={"ip": "203.0.113.50", "reason": "spam"}).status_code == 200
    spam = {"CF-Connecting-IP": "203.0.113.50"}
    assert client.get("/", headers=spam).status_code == 403
    assert client.post("/api/login", headers=spam, json={"username": "x", "password": "y"}).status_code == 403
    assert client.get("/healthz", headers=spam).status_code == 200
    assert [b["ip"] for b in client.get("/api/admin/blocks", headers=h).json()["blocks"]] == ["203.0.113.50"]
    assert client.post("/api/admin/unblock", headers=h, json={"ip": "203.0.113.50"}).status_code == 200
    assert client.get("/", headers=spam).status_code == 200


def test_tunnel_over_real_app_and_plain_access_refused(client):
    from app.config import settings
    sc = SecureClient.handshake(client)
    st, body = sc.call(client, "POST", "/api/login", json_body={"username": "hevorix", "password": "owner-pass-1"})
    assert st == 200
    token = json.loads(body)["token"]
    st, body = sc.call(client, "GET", "/api/me", token=token)
    assert st == 200 and json.loads(body)["me"]["username"].lower() == "hevorix"
    assert sc.call(client, "GET", "/api/me")[0] == 401                                   # token yo'q
    object.__setattr__(settings, "require_tunnel", True)
    try:
        assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 403
        assert client.get("/uploads/x.png").status_code == 403
        assert client.get("/healthz").status_code == 200
    finally:
        object.__setattr__(settings, "require_tunnel", False)


def test_admin_sees_only_ciphertext_in_message_log(client):
    from app.repositories import users
    from app.services import chat
    h = _owner(client)
    owner = users.get_by_username("hevorix")
    m = chat.post(owner, "log sinov birinchi")
    chat.edit(owner, m["id"], "log sinov ikkinchi")
    chat.delete(owner, m["id"])
    items = client.get("/api/admin/messages?state=deleted", headers=h).json()["items"]
    row = next(i for i in items if i["id"] == m["id"])
    assert "text" not in row and row["deleted"] and row["edited"] and row["legacy"]
    assert row["cipher"].startswith("enc1:") and "log sinov" not in row["cipher"]          # adminga ochiq matn berilmaydi
    assert [x["type"] for x in row["history"]] == ["edit", "delete"]
    assert all("log sinov" not in x["old"] + x["new"] for x in row["history"])
    user_h = {"Authorization": "Bearer " + client.post("/api/login", json={"username": "api_alice", "password": "secret12"}).json()["token"]}
    assert client.get("/api/admin/messages", headers=user_h).status_code == 403
