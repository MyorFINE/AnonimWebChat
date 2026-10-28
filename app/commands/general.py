"""Umumiy buyruqlar: /help /settings /admins /online"""
from app.commands.base import Ctx, command, commands_for
from app.realtime.manager import manager
from app.repositories import users
from app.roles import Role, role_of
from app.services import avatars as avatar_service
from app.services import views
from app.config import settings

_SECTIONS = (("Buyruqlar", Role.USER), ("Admin buyruqlari", Role.ADMIN), ("Ega buyruqlari", Role.OWNER))


@command("help", "/help", "platforma buyruqlarini ko'rsatadi")
async def help_cmd(ctx: Ctx) -> None:
    rank = role_of(ctx.user)
    lines: list[str] = []
    for title, role in _SECTIONS:
        if rank < role:
            continue
        lines.append(f"{title}:")
        lines += [f"  {c.usage:<36} {c.description}" for c in commands_for(role)]
        lines.append("")
    await ctx.reply(lines[:-1])


@command("settings", "/settings", "sozlamalar va profil ma'lumoti")
async def settings_cmd(ctx: Ctx) -> None:
    u = ctx.user
    count = len(avatar_service.list_for(u))
    await ctx.reply([
        "Sozlamalar:",
        f"  username : @{u['username']}  (o'zgartirib bo'lmaydi)",
        f"  nickname : {u['nickname']}    -> /nick <yangi>",
        f"  rol      : {u['role']}",
        f"  rasmlar  : {count}/{settings.max_avatars}    -> /avatar list",
        "  parol    : /passwd <eski> <yangi>",
    ])


@command("admins", "/admins", "adminlar ro'yxati")
async def admins_cmd(ctx: Ctx) -> None:
    lines = ["Adminlar:"]
    for r in users.list_staff():
        dot = "●" if manager.is_online(r["id"]) else "○"
        lines.append(f"  {dot} {r['nickname']} (@{r['username']}) - {r['role']}")
    await ctx.reply(lines)


@command("online", "/online", "onlayn foydalanuvchilar")
async def online_cmd(ctx: Ctx) -> None:
    ids = manager.online_ids()
    lines = [f"Onlayn: {len(ids)}"]
    for uid in ids:
        v = views.user_view(uid)
        lines.append(f"  ● {v['nickname']} (@{v['username']})")
    await ctx.reply(lines)

