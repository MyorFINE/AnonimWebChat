"""Ega buyruqlari: /addadmin /rmadmin"""
from app.commands.base import Ctx, command
from app.realtime.manager import manager
from app.roles import Role
from app.services import moderation, views


async def _change(ctx: Ctx, role: Role) -> None:
    t = moderation.set_role(ctx.user, ctx.args[0], role)
    await manager.broadcast({"type": "user_update", "user": views.user_view(t["id"])})
    await manager.system(t["id"], f"Sizning rolingiz: {role.db_name}", "ok")
    await ctx.reply(f"@{t['username']} endi: {role.db_name}", "ok")


@command("addadmin", "/addadmin <user>", "admin tayinlash", Role.OWNER, min_args=1)
async def addadmin_cmd(ctx: Ctx) -> None:
    await _change(ctx, Role.ADMIN)


@command("rmadmin", "/rmadmin <user>", "adminlikdan olish", Role.OWNER, min_args=1)
async def rmadmin_cmd(ctx: Ctx) -> None:
    await _change(ctx, Role.USER)
