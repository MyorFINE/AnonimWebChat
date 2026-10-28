"""Admin buyruqlari: /logs /mute /unmute /ban /unban"""
from datetime import datetime, timedelta, timezone

from app.commands.base import Ctx, command
from app.config import settings
from app.constants import WS_FORBIDDEN
from app.realtime.manager import manager
from app.repositories import logs, users
from app.roles import Role
from app.realtime.events import publish_deleted, publish_rotate_hint, publish_user_removed
from app.services import accounts, moderation


def _time(ts: float) -> str:
    tz = timezone(timedelta(hours=settings.tz_offset))
    return datetime.fromtimestamp(ts, tz).strftime("%m-%d %H:%M:%S")


def _name(uid) -> str:
    u = users.get(uid) if uid else None
    return f"@{u['username']}" if u else "?"


def _format_log(r) -> str:
    t, target, actor = _time(r["created_at"]), _name(r["user_id"]), _name(r["actor_id"])
    kind = r["type"]
    if kind == "edit":
        return f"[{t}] EDIT   #{r['message_id']} {target}: «{r['old_content']}» → «{r['new_content']}»"
    if kind == "delete":
        by = "" if r["actor_id"] == r["user_id"] else f" (o'chirdi: {actor})"
        return f"[{t}] DELETE #{r['message_id']} {target}: «{r['old_content']}»{by}"
    extra = f" ({r['new_content']})" if r["new_content"] else ""
    return f"[{t}] {kind.upper():<6} {actor} → {target}{extra}"


def _split_target(ctx: Ctx) -> tuple[str, str]:
    name, _, rest = ctx.rest.partition(" ")
    return name, rest.strip()


@command("logs", "/logs [n]", "o'chirilgan/tahrirlangan xabarlar va moderatsiya logi", Role.ADMIN)
async def logs_cmd(ctx: Ctx) -> None:
    args = ctx.args
    n = min(int(args[0]), 100) if args and args[0].isdigit() else 20
    rows = logs.recent(n)
    if not rows:
        return await ctx.reply("Log bo'sh")
    await ctx.reply([f"Oxirgi {len(rows)} ta log (UTC+{settings.tz_offset}):"] + [_format_log(r) for r in rows])


@command("mute", "/mute <user> [daqiqa|perm] [sabab]", "yozishdan mute qilish", Role.ADMIN, min_args=1)
async def mute_cmd(ctx: Ctx) -> None:
    name, rest = _split_target(ctx)
    t, label, reason = moderation.mute(ctx.user, name, rest)
    await manager.system(t["id"], f"Siz {label}ga yozishdan mute qilindingiz" + (f". Sabab: {reason}" if reason else ""), "error")
    await manager.broadcast_system(f"{t['nickname']} (@{t['username']}) mute qilindi: {label}", "warn")
    await manager.broadcast({"type": "members_changed"})


@command("unmute", "/unmute <user>", "mute'ni olib tashlash", Role.ADMIN, min_args=1)
async def unmute_cmd(ctx: Ctx) -> None:
    t = moderation.unmute(ctx.user, ctx.args[0])
    await manager.system(t["id"], "Mute olib tashlandi, yozishingiz mumkin", "ok")
    await ctx.reply(f"@{t['username']} unmute qilindi", "ok")
    await manager.broadcast({"type": "members_changed"})


@command("ban", "/ban <user> [sabab]", "ban (chatni ham ko'ra olmaydi)", Role.ADMIN, min_args=1)
async def ban_cmd(ctx: Ctx) -> None:
    name, reason = _split_target(ctx)
    t = moderation.ban(ctx.user, name, reason)
    await manager.send_to(t["id"], {"type": "banned", "reason": reason})
    await manager.kick(t["id"], WS_FORBIDDEN)
    await manager.broadcast_system(f"{t['nickname']} (@{t['username']}) ban qilindi", "warn")
    await manager.broadcast({"type": "members_changed"})
    await publish_rotate_hint("ban")                  # ban qilingan odam eski guruh kalitini bilib qoladi: adminlar uni yangilaydi


@command("unban", "/unban <user>", "bandan chiqarish", Role.ADMIN, min_args=1)
async def unban_cmd(ctx: Ctx) -> None:
    t = moderation.unban(ctx.user, ctx.args[0])
    await ctx.reply(f"@{t['username']} bandan chiqarildi", "ok")
    await manager.broadcast({"type": "members_changed"})


@command("remove", "/remove <user>", "akkauntni o'chirish (xabarlari 'Deleted account' nomi bilan qoladi)", Role.ADMIN, min_args=1)
async def remove_cmd(ctx: Ctx) -> None:
    t = accounts.remove(ctx.user, ctx.args[0])
    await publish_user_removed(t["id"])
    await publish_rotate_hint("remove")
    await ctx.reply(f"@{t['username']} akkaunti o'chirildi", "ok")


@command("warn", "/warn <user> [sabab]", "ogohlantirish (3 tadan keyin avtomatik mute)", Role.ADMIN, min_args=1)
async def warn_cmd(ctx: Ctx) -> None:
    name, reason = _split_target(ctx)
    t, n, auto = moderation.warn(ctx.user, name, reason)
    why = f". Sabab: {reason}" if reason else ""
    if auto:
        await manager.system(t["id"], f"{moderation.WARN_LIMIT} ta ogohlantirish: {moderation.WARN_MUTE_MINUTES} daqiqaga mute qilindingiz{why}", "error")
        await manager.broadcast_system(f"{t['nickname']} (@{t['username']}) ogohlantirishlar tufayli mute qilindi", "warn")
    else:
        await manager.system(t["id"], f"Ogohlantirish {n}/{moderation.WARN_LIMIT}{why}", "error")
        await ctx.reply(f"@{t['username']} ogohlantirildi ({n}/{moderation.WARN_LIMIT})", "ok")
    await manager.broadcast({"type": "members_changed"})


@command("unwarn", "/unwarn <user>", "bitta ogohlantirishni olib tashlash", Role.ADMIN, min_args=1)
async def unwarn_cmd(ctx: Ctx) -> None:
    t, n = moderation.unwarn(ctx.user, ctx.args[0])
    await ctx.reply(f"@{t['username']}: ogohlantirishlar {n}/{moderation.WARN_LIMIT}", "ok")
    await manager.broadcast({"type": "members_changed"})


@command("purge", "/purge <user> [n]", "foydalanuvchining oxirgi n ta (standart 200) xabarini o'chirish", Role.ADMIN, min_args=1)
async def purge_cmd(ctx: Ctx) -> None:
    n = int(ctx.args[1]) if len(ctx.args) > 1 and ctx.args[1].isdigit() else moderation.MAX_PURGE
    t, rows = moderation.purge_user(ctx.user, ctx.args[0], n)
    for r in rows:
        await publish_deleted(r)
    await ctx.reply(f"@{t['username']}: {len(rows)} ta xabar o'chirildi", "ok")
