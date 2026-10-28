"""Profil buyruqlari: /nick /avatar /passwd"""
import asyncio

from app.commands.base import Ctx, command
from app.config import settings
from app.errors import ChatError
from app.realtime.manager import manager
from app.services import auth
from app.services import avatars as avatar_service
from app.services import views


async def _publish_user(uid: int) -> None:
    await manager.broadcast({"type": "user_update", "user": views.user_view(uid)})


@command("nick", "/nick <yangi nickname>", "nickname o'zgartirish", min_args=1)
async def nick_cmd(ctx: Ctx) -> None:
    view = auth.change_nickname(ctx.user, ctx.rest)
    await manager.broadcast({"type": "user_update", "user": view})
    await ctx.reply(f"Nickname o'zgardi: {view['nickname']}", "ok")


@command("avatar", "/avatar list|upload|use N|del N|none", "profil rasmlari (3 tagacha)")
async def avatar_cmd(ctx: Ctx) -> None:
    args = ctx.args
    sub = args[0].lower() if args else "list"
    uid = ctx.user["id"]

    if sub == "list":
        items = avatar_service.list_for(ctx.user)
        lines = [f"Profil rasmlari ({len(items)}/{settings.max_avatars}):"]
        lines += [f"  {i}. {'[faol] ' if active else ''}/avatars/{a['filename']}" for i, a, active in items]
        if not items:
            lines.append("  (hali yo'q)  -> /avatar upload")
        return await ctx.reply(lines)
    if sub == "upload":
        return await ctx.reply("/avatar upload brauzerda rasm tanlash oynasini ochadi", "error")
    if sub == "none":
        avatar_service.clear_active(ctx.user)
        msg = "Rasm olib tashlandi (rasmlar saqlanib qoldi)"
    elif sub in ("use", "del") and len(args) > 1:
        if sub == "use":
            avatar_service.activate(ctx.user, args[1])
            msg = f"{args[1]}-rasm faollashtirildi"
        else:
            avatar_service.remove(ctx.user, args[1])
            msg = f"{args[1]}-rasm o'chirildi"
    else:
        raise ChatError("Foydalanish: /avatar list | upload | use N | del N | none")
    await _publish_user(uid)
    await ctx.reply(msg, "ok")


@command("passwd", "/passwd <eski> <yangi>", "parolni almashtirish", min_args=2)
async def passwd_cmd(ctx: Ctx) -> None:
    old, new = ctx.args[0], ctx.args[1]
    await asyncio.to_thread(auth.change_password, ctx.user, old, new, ctx.token_hash)
    await ctx.reply("Parol almashtirildi (boshqa qurilmalardan chiqarildingiz)", "ok")
