"""E2EE: server-tomon xizmatlari (FastAPI shart emas) + protokol mosligi. Qat'iy rejim (server ochiq matnni rad etadi)."""
import secrets

import pytest

import e2e_client as C
from app.config import settings
from app.errors import ChatError
from app.repositories import e2ee as e2ee_repo
from app.repositories import messages, users
from app import crypto
from app.services import auth, chat, e2ee as svc


@pytest.fixture(autouse=True)
def strict():
    object.__setattr__(settings, "require_e2ee", True)
    yield
    object.__setattr__(settings, "require_e2ee", False)


class Cli:
    """Brauzer mijozi o'rnida: kalitlar bor, serverga faqat kirish kaliti va shifrlangan narsa boradi."""
    def __init__(self, name):
        self.name = name
        self.kek, self.auth = C.derive(name, "pw-" + name)
        self.ident = C.Identity()
        token, me = auth.register(name, name.upper(), self.auth, self.ident.account_keys(self.kek, name))
        self.token, self.id = token, me["id"]
        self.row = users.get(self.id)
        self.keys = {}

    def refresh(self):
        self.row = users.get(self.id)


def mk(prefix="e2e"):
    return Cli(f"{prefix}_{secrets.token_hex(3)}")


ROOM = {}


def ensure_room(*clients):
    """Guruh kaliti butun testlar uchun bitta (birinchi mijoz yaratadi); keyingilarga mavjud a'zo o'raydi — brauzer mantig'i."""
    if not ROOM:
        first, key = clients[0], secrets.token_bytes(32)
        wraps = [{"user_id": c.id, "wrapped": C.wrap_room_key(first.ident, key, 1, first.id, c.ident.ecdh_pub, c.id)} for c in clients]
        svc.room_init(first.row, C.epoch_check(key, 1), wraps)
        ROOM.update(key=key, ep=1, owner=first)
    else:
        o = ROOM["owner"]
        wraps = [{"user_id": c.id, "wrapped": C.wrap_room_key(o.ident, ROOM["key"], ROOM["ep"], o.id, c.ident.ecdh_pub, c.id)} for c in clients]
        svc.room_wrap(users.get(o.id), ROOM["ep"], wraps)
    return ROOM["key"], ROOM["ep"]


def test_register_requires_keys_and_derived_password():
    with pytest.raises(ChatError):
        auth.register("plainuser1", "P", "secret12")                    # kalitsiz va ochiq parol — rad
    c = mk()
    assert users.get(c.id)["auth_v"] == 1 and users.get(c.id)["key_blob"]
    token, me = auth.login(c.name, c.auth)
    assert me["id"] == c.id
    with pytest.raises(ChatError):
        auth.login(c.name, "pw-" + c.name)                              # asl parol serverda ISHLAMAYDI: faqat hosila


def test_server_never_sees_password_or_private_keys():
    c = mk()
    row = users.get(c.id)
    blob = row["key_blob"]
    assert "pw-" + c.name not in blob and C.b64u(c.ident.pkcs8(c.ident.ecdh)) not in blob
    # noto'g'ri parol bilan zaxira ochilmaydi
    bad_kek, _ = C.derive(c.name, "wrong")
    with pytest.raises(Exception):
        C.Identity.unwrap(blob, bad_kek, c.name)
    assert C.Identity.unwrap(blob, c.kek, c.name).ecdh_pub == c.ident.ecdh_pub


def test_plaintext_rejected_in_strict_mode():
    c = mk()
    with pytest.raises(ChatError):
        chat.post(c.row, "salom")
    with pytest.raises(ChatError):
        chat.post_e2e(c.row, "salom oddiy matn")


def test_group_flow_server_stores_only_ciphertext():
    a, b = mk("ga"), mk("gb")
    key, ep = ensure_room(a, b)
    with pytest.raises(ChatError):
        svc.room_init(a.row, C.epoch_check(key, 1), [])                  # epoch 1 ikkinchi marta yaratilmaydi
    # B o'z o'ralgan kalitini oladi, tekshiradi va ochadi
    mine = {r["epoch"]: r for r in e2ee_repo.keys_for(b.id)}[ep]
    wrapper = users.get(mine["wrapper_id"])
    got = C.unwrap_room_key(b.ident, mine["wrapped"], ep, b.id, wrapper["ecdh_pub"], mine["wrapper_id"])
    chk = [e for e in svc.room_state(b.row)["epochs"] if e["epoch"] == ep][0]["check"]
    assert got == key and C.verify_epoch_check(chk, got, ep)
    env = C.seal(a.ident, a.id, None, ep, key, {"t": "SIRXYZ987"})
    v = chat.post_e2e(a.row, env)
    assert v["e2e"] == env and "content" not in v and "SIRXYZ987" not in repr(v)
    raw = messages.raw_group(1)[0]
    assert raw["e2e"] == 1 and "SIRXYZ987" not in raw["content"] and raw["content"] == env      # bazada AYNAN shifr
    assert C.open_(v["e2e"], a.id, None, got, a.ident.sign_pub)["t"] == "SIRXYZ987"
    # admin ko'rinishi — faqat shifr
    assert crypto.admin_view(raw["content"]) == env and "SIRXYZ987" not in crypto.admin_view(raw["content"])
    # server-view ham ochiq matn bermaydi
    sv = svc.server_view(a.row, None, 3)
    assert sv["server_can_decrypt"] is False and "SIRXYZ987" not in repr(sv)
    assert sv["rows"][0]["stored"] == env and sv["rows"][0]["admin_sees"] == env


def test_epoch_must_match_and_wrong_kind_rejected():
    a, b = mk("ea"), mk("eb")
    key, ep = ensure_room(a, b)
    cur = e2ee_repo.current_epoch()
    stale = C.seal(a.ident, a.id, None, cur + 5, key, {"t": "x"})
    with pytest.raises(ChatError):
        chat.post_e2e(a.row, stale)                                      # noto'g'ri epoch
    dmenv = C.seal(a.ident, a.id, b.id, 0, C.dm_key(a.ident, b.ident.ecdh_pub, a.id, b.id), {"t": "x"})
    with pytest.raises(ChatError):
        chat.post_e2e(a.row, dmenv)                                      # lichka konverti guruhga
    genv = C.seal(a.ident, a.id, None, cur, key, {"t": "x"})
    with pytest.raises(ChatError):
        chat.post_e2e(a.row, genv, to=b.id)                              # guruh konverti lichkaga


def test_dm_and_edit_and_only_author_can_edit():
    a, b = mk("da"), mk("db")
    ensure_room(a, b)
    k = C.dm_key(a.ident, b.ident.ecdh_pub, a.id, b.id)
    v = chat.post_e2e(a.row, C.seal(a.ident, a.id, b.id, 0, k, {"t": "sir"}), to=b.id)
    kb = C.dm_key(b.ident, a.ident.ecdh_pub, a.id, b.id)
    assert kb == k and C.open_(v["e2e"], a.id, b.id, kb, a.ident.sign_pub)["t"] == "sir"
    with pytest.raises(ChatError):
        chat.edit_e2e(b.row, v["id"], C.seal(b.ident, b.id, a.id, 0, kb, {"t": "hack"}))
    msg, env = chat.edit_e2e(a.row, v["id"], C.seal(a.ident, a.id, b.id, 0, k, {"t": "sir2"}))
    assert messages.get(v["id"])["content"] == env
    # ucinchi shaxs lichka konvertini boshqa xonada ocholmaydi (AAD xona + yuboruvchiga bog'langan)
    with pytest.raises(Exception):
        C.open_(env, b.id, a.id, kb, a.ident.sign_pub)


def test_rotate_and_wrap_for_newcomers_and_banned_cannot_join():
    a, b = mk("ra"), mk("rb")
    ensure_room(a, b)
    cur = e2ee_repo.current_epoch()
    late = mk("rl")
    miss = [m for m in svc.room_missing() if m["user_id"] == late.id]
    assert miss                                                           # yangi a'zoda kalit yo'q
    with pytest.raises(ChatError):
        svc.room_rotate(b.row, cur, "x", [])                              # oddiy foydalanuvchi yangilay olmaydi
    # adminlik: a'ni admin qilamiz
    users.set_role(a.id, "admin")
    a.refresh()
    k2 = secrets.token_bytes(32)
    wraps = [{"user_id": c.id, "wrapped": C.wrap_room_key(a.ident, k2, cur + 1, a.id, c.ident.ecdh_pub, c.id)} for c in (a, b, late)]
    assert svc.room_rotate(a.row, cur, C.epoch_check(k2, cur + 1), wraps) == cur + 1
    ROOM.update(key=k2, ep=cur + 1, owner=a)
    with pytest.raises(ChatError):
        svc.room_rotate(a.row, cur, C.epoch_check(k2, cur + 1), wraps)    # eski avlod bo'yicha qayta — 409
    users.set_ban(late.id, True, "t")
    assert all(m["user_id"] != late.id for m in svc.room_missing())       # banlanganlarga kalit o'ralmaydi


def test_blob_is_opaque_and_attaches_once():
    from app.services import media
    a = mk("fa")
    ensure_room(a)
    f = secrets.token_bytes(100)
    name = media.store_opaque(f)
    e2ee_repo.add_blob(name, a.id, len(f))
    key = C.unb64u(C.b64u(secrets.token_bytes(32)))
    cur = e2ee_repo.current_epoch()
    # guruh kalitini bilmaymiz — faqat server qabul qilishini tekshiramiz (kalit fixture'da boshqa bo'lishi mumkin)
    env = C.seal(a.ident, a.id, None, cur, key, {"t": "", "f": {"k": "x"}})
    v = chat.post_e2e(a.row, env, blob=name)
    assert v["blob"]["url"] == "/uploads/" + name and media.read(name) == f
    with pytest.raises(ChatError):
        chat.post_e2e(a.row, env, blob=name)                              # bir fayl ikki xabarga biriktirilmaydi
    other = mk("fo")
    n2 = media.store_opaque(f); e2ee_repo.add_blob(n2, a.id, len(f))
    with pytest.raises(ChatError):
        chat.post_e2e(other.row, env, blob=n2)                            # begona yuklamani biriktirib bo'lmaydi


def test_legacy_upgrade_and_owner_env_password_not_reset():
    object.__setattr__(settings, "require_e2ee", False)
    token, me = auth.register(f"leg_{secrets.token_hex(3)}", "L", "oddiy-parol")
    object.__setattr__(settings, "require_e2ee", True)
    u = users.get(me["id"])
    assert u["auth_v"] == 0
    ident = C.Identity()
    kek, new_auth = C.derive(u["username"], "oddiy-parol")
    svc.upgrade_legacy(u, "oddiy-parol", new_auth, ident.account_keys(kek, u["username"]))
    u = users.get(me["id"])
    assert u["auth_v"] == 1 and auth.login(u["username"], new_auth)
    with pytest.raises(ChatError):
        auth.login(u["username"], "oddiy-parol")                          # eski parol endi ishlamaydi
    with pytest.raises(ChatError):
        svc.upgrade_legacy(u, "oddiy-parol", new_auth, ident.account_keys(kek, u["username"]))   # ikki marta emas


def test_change_password_rewraps_keys():
    c = mk("cp")
    kek2, auth2 = C.derive(c.name, "yangi-parol")
    blob2 = c.ident.wrap(kek2, c.name)
    auth.change_password(c.row, c.auth, auth2, "keep", blob2, C.KDF_ITER)
    auth.login(c.name, auth2)
    assert C.Identity.unwrap(users.get(c.id)["key_blob"], kek2, c.name).ecdh_pub == c.ident.ecdh_pub
    with pytest.raises(ChatError):
        auth.change_password(users.get(c.id), auth2, auth2, "keep")       # kalitlarni qayta o'ramasdan almashtirib bo'lmaydi


def test_interop_with_browser_js():
    import shutil
    if not shutil.which("node"):
        pytest.skip("node yo'q")
    import interop_driver
    interop_driver.run()
