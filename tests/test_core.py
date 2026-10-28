"""Servis va buyruq qatlami testlari (FastAPI talab qilinmaydi)."""
import asyncio
import json

import pytest

import app.commands  # noqa: F401  (buyruqlarni ro'yxatdan o'tkazadi)
from app.commands import Ctx, dispatch
from app.errors import ChatError
from app.realtime.manager import manager
from app.repositories import messages, users
from app.security import hash_token
from app.services import auth, bootstrap, chat, moderation


class FakeWS:
    def __init__(self):
        self.sent, self.closed = [], None

    async def send_text(self, s):
        self.sent.append(json.loads(s))

    async def close(self, code):
        self.closed = code

    def system_lines(self):
        return [" ".join(m["lines"]) for m in self.sent if m["type"] == "system"]



def _real_png(size=(8, 8)):
    import io
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", size, (30, 120, 200)).save(b, "PNG"); return b.getvalue()

def run(coro):
    return asyncio.run(coro)


def cmd(user, text, token="t"):
    return run(dispatch(Ctx.parse(users.get(user["id"]), text, hash_token(token))))


@pytest.fixture(scope="module")
def people():
    bootstrap.ensure_owner()
    owner = users.get_by_username("hevorix")
    _, bob = auth.register("bob", "Bob", "secret12")
    _, carol = auth.register("carol", "Carol", "secret12")
    return {"alice": users.get(owner["id"]), "bob": users.get(bob["id"]), "carol": users.get(carol["id"])}


def test_hevorix_is_owner_and_username_reserved(people):
    assert people["alice"]["username"] == "Hevorix" and people["alice"]["role"] == "owner"
    assert people["bob"]["role"] == "user"
    for variant in ("hevorix", "HEVORIX", "HeVoRiX", "@Hevorix"):      # katta-kichik harfda ham band
        with pytest.raises(ChatError) as e:
            auth.register(variant, "Other", "secret12")
        assert e.value.status == 409 and "band" in e.value.message
        assert auth.username_status(variant) == (False, "Bu username band")
    assert auth.username_status("BOB")[0] is False and auth.username_status("freeone")[0] is True
    with pytest.raises(ChatError) as e:
        auth.register("BOB", "Other", "secret12")
    assert e.value.status == 409
    with pytest.raises(ChatError):
        auth.register("ab", "x", "secret12")           # juda qisqa
    with pytest.raises(ChatError):
        auth.register("system", "x", "secret12")       # band so'z


def test_login(people):
    with pytest.raises(ChatError) as e:
        auth.login("bob", "wrong-pass")
    assert e.value.status == 401
    token, me = auth.login("BOB", "secret12")
    assert me["username"] == "bob" and auth.authenticate(token)


def test_post_edit_delete_and_logs(people):
    alice, bob = people["alice"], people["bob"]
    msg = chat.post(bob, "salom")
    chat.edit(bob, msg["id"], "salom dunyo")
    with pytest.raises(ChatError):
        chat.edit(alice, msg["id"], "boshqa birovniki")      # begona xabarni tahrirlab bo'lmaydi
    chat.delete(alice, msg["id"])                             # admin o'chira oladi
    sock = FakeWS()
    manager.connect(alice["id"], sock)
    cmd(alice, "/logs")
    text = "\n".join(sock.system_lines())
    assert "EDIT" in text and "DELETE" in text and "salom dunyo" not in text      # adminga faqat shifrlangan ko'rinish
    manager.disconnect(alice["id"], sock)


def test_mute_blocks_writing_and_unmute(people):
    alice, carol = people["alice"], people["carol"]
    moderation.mute(alice, "carol", "5 spam")
    with pytest.raises(ChatError):
        chat.post(users.get(carol["id"]), "yozaman")
    moderation.unmute(alice, "carol")
    assert chat.post(users.get(carol["id"]), "endi mumkin")["content"] == "endi mumkin"


def test_ban_closes_sessions_and_login(people):
    alice, bob = people["alice"], people["bob"]
    token, _ = auth.login("bob", "secret12")
    sock = FakeWS()
    manager.connect(bob["id"], sock)
    cmd(alice, "/ban bob reklama")
    assert sock.closed == 4403 and any(m["type"] == "banned" for m in sock.sent)
    assert auth.authenticate(token) is None
    with pytest.raises(ChatError) as e:
        auth.login("bob", "secret12")
    assert e.value.status == 403
    cmd(alice, "/unban bob")
    assert auth.login("bob", "secret12")


def test_permissions(people):
    alice, bob, carol = people["alice"], people["bob"], people["carol"]
    sock = FakeWS()
    manager.connect(bob["id"], sock)
    cmd(bob, "/ban carol")                                     # oddiy foydalanuvchi ban qila olmaydi
    cmd(bob, "/logs")
    assert sum("faqat adminlar" in s for s in sock.system_lines()) == 2
    assert users.get(carol["id"])["banned"] == 0
    cmd(alice, "/addadmin bob")
    assert users.get(bob["id"])["role"] == "admin"
    with pytest.raises(ChatError):
        moderation.ban(users.get(bob["id"]), "alice", "")      # egaga qo'llab bo'lmaydi
    cmd(alice, "/rmadmin bob")
    manager.disconnect(bob["id"], sock)


def test_nick_and_unknown_command(people):
    bob = people["bob"]
    sock = FakeWS()
    manager.connect(bob["id"], sock)
    cmd(bob, "/nick Yangi Bob")
    assert users.get(bob["id"])["nickname"] == "Yangi Bob"
    cmd(bob, "/yoq")
    assert any("Noma'lum buyruq" in s for s in sock.system_lines())
    manager.disconnect(bob["id"], sock)


def test_help_lists_by_role(people):
    sock_a, sock_b = FakeWS(), FakeWS()
    manager.connect(people["alice"]["id"], sock_a)
    manager.connect(people["carol"]["id"], sock_b)
    cmd(people["alice"], "/help")
    cmd(people["carol"], "/help")
    a, c = "\n".join(sock_a.system_lines()), "\n".join(sock_b.system_lines())
    assert "/addadmin" in a and "/ban" in a and "/addadmin" not in c and "/ban" not in c
    manager.disconnect(people["alice"]["id"], sock_a)
    manager.disconnect(people["carol"]["id"], sock_b)


def test_direct_messages_are_private(people):
    alice, bob, carol = (users.get(people[k]["id"]) for k in ("alice", "bob", "carol"))
    m = chat.post(bob, "faqat Alisa uchun", to=alice["id"])
    assert m["to"] == alice["id"] and m["read"] is False
    assert chat.audience({"recipient_id": m["to"], "user_id": bob["id"]}) == [bob["id"], alice["id"]]
    # umumiy chat tarixida ko'rinmaydi, begona suhbatda ham
    assert all(h["id"] != m["id"] for h in chat.history())
    assert [h["id"] for h in chat.dm_history(alice, bob["id"])] == [m["id"]]
    assert chat.dm_history(carol, bob["id"]) == []
    # suhbatlar ro'yxati va o'qilmaganlar
    d = chat.dialogs(alice)
    assert d[0]["user"]["username"] == "bob" and d[0]["unread"] == 1 and d[0]["last"]["id"] == m["id"]
    assert chat.dialogs(carol) == []
    assert chat.mark_read(alice, bob["id"]) == 1
    assert chat.dialogs(alice)[0]["unread"] == 0
    assert chat.dm_history(bob, alice["id"])[0]["read"] is True


def test_dm_rules(people):
    alice, bob = users.get(people["alice"]["id"]), users.get(people["bob"]["id"])
    with pytest.raises(ChatError):
        chat.post(bob, "o'zimga", to=bob["id"])                 # o'ziga yozib bo'lmaydi
    with pytest.raises(ChatError) as e:
        chat.post(bob, "yo'q odam", to=99999)
    assert e.value.status == 404
    m = chat.post(bob, "maxfiy", to=alice["id"])
    with pytest.raises(ChatError):
        chat.delete(alice, m["id"])                             # ega ham begona shaxsiy xabarni o'chira olmaydi
    chat.edit(bob, m["id"], "maxfiy 2")                         # tahrirlash/o'chirish adminlar logiga tushmaydi
    row = chat.delete(bob, m["id"])
    assert row["recipient_id"] == alice["id"]
    for r in chat_logs():
        assert r["message_id"] != m["id"]


def chat_logs():
    from app.repositories import logs
    return logs.recent(500)


def test_profile_bio_and_members(people):
    from app.services import directory
    bob = users.get(people["bob"]["id"])
    view = auth.update_profile(bob, bio="  Salom, men Bobman  ")
    assert view["bio"] == "Salom, men Bobman"
    with pytest.raises(ChatError):
        auth.update_profile(bob, bio="x" * 141)
    alice, carol = users.get(people["alice"]["id"]), users.get(people["carol"]["id"])
    names = [m["username"] for m in directory.members(carol)]
    assert names[0] == "Hevorix" and set(names) >= {"bob", "carol"}      # ega birinchi
    assert "banned" not in directory.members(carol)[0]                 # oddiy foydalanuvchi ban holatini ko'rmaydi
    assert "banned" in directory.members(alice)[0]


def test_avatar_gallery_by_id(people):
    from app.services import avatars as av
    carol = users.get(people["carol"]["id"])
    png = _real_png()
    av.upload(carol, png)
    carol = users.get(carol["id"])
    g = av.gallery(carol)
    assert len(g) == 1 and g[0]["active"]
    av.remove_id(carol, g[0]["id"])
    assert av.gallery(users.get(carol["id"])) == []
    with pytest.raises(ChatError):
        av.activate_id(carol, 999999)


# ---------- yangi imkoniyatlar: reply, rasm, rang, IP blok, harakatlar logi ----------
PNG = _real_png()


def test_reply_group_and_dm_scoping(people):
    alice, bob, carol = (users.get(people[k]["id"]) for k in ("alice", "bob", "carol"))
    base = chat.post(alice, "savol bormi?")
    r = chat.post(bob, "ha, bor", reply_to=base["id"])
    assert r["reply"]["id"] == base["id"] and r["reply"]["text"] == "savol bormi?" and r["reply"]["deleted"] is False
    assert r["reply"]["nickname"] == "Hevorix"
    # lichka xabariga umumiy chatdan javob berib bo'lmaydi va aksincha
    dm = chat.post(alice, "maxfiy", to=bob["id"])
    with pytest.raises(ChatError):
        chat.post(bob, "x", reply_to=dm["id"])
    with pytest.raises(ChatError):
        chat.post(bob, "x", to=alice["id"], reply_to=base["id"])
    # begona (carol) ikkovining lichkasiga javob bera olmaydi
    with pytest.raises(ChatError):
        chat.post(carol, "x", to=alice["id"], reply_to=dm["id"])
    ok = chat.post(bob, "javob", to=alice["id"], reply_to=dm["id"])
    assert ok["reply"]["id"] == dm["id"]
    # asl xabar o'chirilsa, javobda "deleted" ko'rinadi
    chat.delete(alice, base["id"])
    assert [h for h in chat.history() if h["id"] == r["id"]][0]["reply"] == {"id": base["id"], "deleted": True}


def test_image_with_caption(people):
    from app.config import settings
    from app.services import media
    bob, alice = users.get(people["bob"]["id"]), users.get(people["alice"]["id"])
    m = chat.post_media(bob, PNG, "r.png", "image/png", "  mana rasm  ")
    assert m["content"] == "mana rasm" and m["image"].startswith("/uploads/") and m["image"].endswith(".png")
    name = m["image"].split("/")[-1]
    assert not (settings.uploads_dir / name).exists()                       # ochiq nusxa yo'q
    assert (settings.media_dir / (name + ".enc")).read_bytes()[:4] == b"ACM1"   # diskda shifrlangan
    assert media.read(name)[:4] == b"\x89PNG"
    only = chat.post_media(bob, PNG, "", "", "")                            # izohsiz rasm ham bo'ladi
    assert only["content"] == "" and only["image"]
    with pytest.raises(ChatError):
        chat.post_media(bob, b"", "a.txt", "text/plain", "x")
    chat.edit(bob, only["id"], "keyin izoh")
    chat.edit(bob, only["id"], "")
    d = chat.post_media(bob, PNG, "r.png", "image/png", "lichka rasm", to=alice["id"])
    assert d["to"] == alice["id"]
    chat.delete(bob, m["id"])
    assert media.read(name) is None                                         # o'chirilganda fayl ham o'chadi
    assert chat.post(bob, "rasmga javob", reply_to=only["id"])["reply"]["image"] is True


def test_staff_color(people):
    alice, bob = users.get(people["alice"]["id"]), users.get(people["bob"]["id"])
    assert auth.update_profile(alice, color="#FF8800")["color"] == "#ff8800"
    assert auth.update_profile(alice, color="")["color"] is None
    with pytest.raises(ChatError):
        auth.update_profile(alice, color="qizil")
    with pytest.raises(ChatError) as e:
        auth.update_profile(bob, color="#112233")              # oddiy foydalanuvchi tanlay olmaydi
    assert e.value.status == 403


def test_ip_block_rules_and_activity_log(people):
    from app.repositories import activity as arepo
    from app.services import activity, ipblock
    alice, bob = users.get(people["alice"]["id"]), users.get(people["bob"]["id"])
    activity.record("login", ip="203.0.113.7", user=bob)
    activity.record("login", ip="203.0.113.7", user=bob)
    activity.record("login_failed", ip="203.0.113.7", username="nomalum")
    activity.record("msg", ip="203.0.113.7", user=bob, detail="salom")
    activity.record("login", ip="198.51.100.1", user=alice)
    rows = [r for r in arepo.ip_profiles("203.0.113.7")]
    by = {(r["username"]): r for r in rows}
    assert by["bob"]["logins"] == 2 and by["bob"]["msgs"] == 1 and by["nomalum"]["failed"] == 1
    assert [r["action"] for r in arepo.query(ip="203.0.113.7", user="bob", action="msg")] == ["msg"]
    # bloklash
    assert ipblock.block(alice, "203.0.113.7", "spam", actor_ip="198.51.100.1") == "203.0.113.7"
    assert ipblock.is_blocked("203.0.113.7")
    with pytest.raises(ChatError):
        ipblock.block(alice, "198.51.100.1", "", actor_ip="198.51.100.1")      # o'zini bloklay olmaydi
    with pytest.raises(ChatError):
        ipblock.block(alice, "not-an-ip", "", actor_ip="198.51.100.1")
    assert ipblock.block(alice, "::ffff:203.0.113.9", "", actor_ip="198.51.100.1") == "203.0.113.9"   # IPv4-mapped normallashadi
    users.set_role(bob["id"], "admin")           # admin ishlatgan IP'ni oddiy admin bloklay olmaydi
    with pytest.raises(ChatError):
        ipblock.block(users.get(bob["id"]), "198.51.100.1", "", actor_ip="192.0.2.50")
    users.set_role(bob["id"], "user")
    ipblock.unblock(alice, "203.0.113.7", "198.51.100.1")
    assert not ipblock.is_blocked("203.0.113.7") and ipblock.is_blocked("203.0.113.9")
    assert [b["ip"] for b in ipblock.listing()] == ["203.0.113.9"]
    ipblock.unblock(alice, "203.0.113.9", "198.51.100.1")


def test_moderation_command_is_audited_but_passwd_is_not(people):
    from app.repositories import activity as arepo
    alice, bob = users.get(people["alice"]["id"]), users.get(people["bob"]["id"])
    sock = FakeWS()
    manager.connect(alice["id"], sock)
    run(dispatch(Ctx.parse(alice, "/mute bob 1 test", "t", "192.0.2.1")))
    run(dispatch(Ctx.parse(alice, "/unmute bob", "t", "192.0.2.1")))
    run(dispatch(Ctx.parse(bob, "/passwd secret12 yangiparol1", "t", "192.0.2.2")))
    manager.disconnect(alice["id"], sock)
    rows = arepo.query(ip="192.0.2")
    assert any(r["action"] == "mod" and "/mute bob" in r["detail"] for r in rows)
    assert not any("yangiparol1" in (r["detail"] or "") or "secret12" in (r["detail"] or "") for r in arepo.query(limit=200))


def test_owner_password_from_env_and_role_restore(people):
    from app.config import settings
    owner = users.get_by_username("HEVORIX")
    assert auth.login("hevorix", "owner-pass-1")[1]["username"] == "Hevorix"
    users.set_role(owner["id"], "user")
    bootstrap.ensure_owner()                                      # egalik qaytariladi
    assert users.get_by_username("hevorix")["role"] == "owner"
    assert settings.admin_password == "owner-pass-1"


def test_image_metadata_is_stripped():
    import io
    from PIL import Image
    from PIL.ExifTags import Base
    from app.services import imgclean
    ex = Image.Exif(); ex[Base.Make] = "SecretCam"
    b = io.BytesIO(); Image.new("RGB", (40, 20), (200, 30, 30)).save(b, "JPEG", exif=ex)
    assert b"SecretCam" in b.getvalue()
    c = imgclean.clean(b.getvalue())
    assert b"SecretCam" not in c.data and c.ext == "jpg" and (c.width, c.height) == (40, 20) and c.thumb
    with pytest.raises(ChatError):                                 # soxta sarlavha bilan fayl rad etiladi
        imgclean.clean(b"\x89PNG\r\n\x1a\n" + b"0" * 40)


def test_delete_dm_for_both_sides(people):
    from app.services import chat
    alice, bob = people["alice"], people["bob"]
    chat.post(alice, "salom", to=bob["id"]); chat.post(bob, "alik", to=alice["id"])
    assert chat.dialogs(alice) and chat.dialogs(bob)
    assert chat.delete_dm(alice, bob["id"]) == 2
    assert not chat.dialogs(alice) and not chat.dialogs(bob)
    assert chat.dm_history(bob, alice["id"]) == []


def test_removed_account_becomes_deleted_account(people):
    from app.services import accounts, chat, directory, views
    alice, bob, carol = people["alice"], people["bob"], people["carol"]
    chat.post(bob, "umumiy xabar")
    accounts.delete_self(bob, "secret12")
    v = views.user_view(bob["id"])
    assert v["deleted"] and v["nickname"] == "Deleted account" and v["username"] == "" and v["avatar"] is None
    assert bob["id"] not in [m["id"] for m in directory.members(alice)]
    assert [m["content"] for m in chat.history()] == ["umumiy xabar"]       # xabarlari qoladi
    with pytest.raises(ChatError):
        chat.post(carol, "salom", to=bob["id"])                              # unga yozib bo'lmaydi
    with pytest.raises(ChatError):
        from app.services import auth
        auth.login("bob", "secret12")


_seq = [0]


def _fresh():
    """Boshqa testlarga ta'sir qilmaydigan yangi oddiy foydalanuvchi."""
    _seq[0] += 1
    return users.get(auth.register(f"fresh{_seq[0]}", "Fresh", "secret12")[1]["id"])


def test_any_file_type_up_to_limit(people):
    from app.config import settings
    from app.services import media
    bob = _fresh()
    for fname, mime in (("hisobot.pdf", "application/pdf"), ("kino.mp4", "video/mp4"), ("run.exe", "application/x-msdownload")):
        data = b"MAXFIY-" + fname.encode() + bytes(range(200))
        m = chat.post_media(bob, data, "../" + fname, mime, "")
        assert m["image"] is None and m["file"]["name"] == fname and m["file"]["size"] == len(data)
        stored = m["file"]["url"].split("/")[-1]
        assert media.read(stored) == data
        assert data not in (settings.media_dir / (stored + ".enc")).read_bytes()
    with pytest.raises(ChatError) as e:
        chat.post_media(bob, b"0" * (settings.max_media_bytes + 1), "katta.bin", "", "")
    assert "50 MB" in e.value.message


def test_media_manager_and_privacy(people):
    from app.services import mediamgr
    bob, alice = _fresh(), users.get(people["alice"]["id"])
    g = chat.post_media(bob, b"%PDF" + b"1" * 50, "a.pdf", "application/pdf", "")
    dm = chat.post_media(bob, b"%PDF" + b"2" * 50, "b.pdf", "application/pdf", "", to=alice["id"])
    ids = [i["id"] for i in mediamgr.listing()["items"]]
    assert g["id"] in ids and dm["id"] not in ids                           # lichka fayllari ko'rinmaydi
    assert all(set(i) == {"id", "ts", "username", "nickname", "kind", "size"} for i in mediamgr.listing()["items"])
    done = mediamgr.remove(alice, [g["id"], dm["id"]])
    assert [(r["id"], gone) for r, gone in done] == [(g["id"], True)]       # izohsiz xabar fayl bilan birga o'chadi
    assert messages.get(dm["id"])["file"]                                   # lichkaga tegilmaydi


def test_badges(people):
    from app.services import badges
    alice, bob = users.get(people["alice"]["id"]), _fresh()
    assert badges.clean("🔥", "spin") == ("🔥", "spin")
    for bad in ("abc", "1", "<b>", "x🔥"):
        with pytest.raises(ChatError):
            badges.clean(bad, "")
    with pytest.raises(ChatError):
        badges.clean("🔥", "yo'q-animatsiya")
    badges.set_for(alice, alice["id"], "👑", "glow")
    badges.set_for(alice, bob["id"], "🔥", "bounce")
    from app.services import views
    assert views.user_view(bob["id"])["badge"] == "🔥"
    with pytest.raises(ChatError):
        badges.set_for(bob, bob["id"], "😀", "")                            # oddiy foydalanuvchi o'ziga qo'ya olmaydi
    badges.set_for(alice, bob["id"], "", "")
    badges.set_for(alice, alice["id"], "", "")


def test_moderation_tools(people):
    from app.services import modsettings
    alice, bob = users.get(people["alice"]["id"]), _fresh()
    for _ in range(2):
        moderation.warn(alice, bob["username"], "qoida")
    t, n, auto = moderation.warn(alice, bob["username"], "yana")
    assert auto and users.get(bob["id"])["warns"] == 0 and users.get(bob["id"])["muted_until"] > 0
    users.set_mute(bob["id"], 0, None)
    modsettings.set_words(alice, ["Yomon*", "qo'pol"])
    with pytest.raises(ChatError):
        chat.post(bob, "bu YOMONlik")
    chat.post(alice, "yomonlik")                                            # adminga qo'llanmaydi
    chat.post(bob, "lichka yomon", to=alice["id"])                          # lichka filtrlanmaydi
    modsettings.set_words(alice, [])
    modsettings.set_locked(alice, True)
    with pytest.raises(ChatError):
        chat.post(bob, "qulf")
    modsettings.set_locked(alice, False)
    modsettings.set_slowmode(alice, 30); modsettings._last_post.clear()
    chat.post(bob, "birinchi")
    with pytest.raises(ChatError) as e:
        chat.post(bob, "ikkinchi")
    assert e.value.status == 429
    modsettings.set_slowmode(alice, 0)
    t, rows = moderation.purge_user(alice, bob["username"], 5)
    assert 1 <= len(rows) <= 5


def test_reports(people):
    from app.services import reports
    alice, bob = users.get(people["alice"]["id"]), _fresh()
    m = chat.post(alice, "shikoyatlik xabar")
    reports.create(bob, m["id"], "sabab")
    with pytest.raises(ChatError):
        reports.create(bob, m["id"], "")                                    # ikki marta bo'lmaydi
    with pytest.raises(ChatError):
        reports.create(alice, m["id"], "")                                  # o'ziga bo'lmaydi
    item = reports.listing("open")["items"][0]
    assert item["text"] == "shikoyatlik xabar" and item["reason"] == "sabab"
