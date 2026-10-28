"""Xabar buyruqlari: /edit /del (veb-interfeys xuddi shu servislardan foydalanadi)."""
from app.commands.base import Ctx, command, parse_id
from app.errors import ChatError
from app.services import chat
from app.realtime.events import publish_deleted, publish_edited


@command("edit", "/edit <id> <yangi matn>", "o'z xabaringizni tahrirlash", min_args=2)
async def edit_cmd(ctx: Ctx) -> None:
    head, _, text = ctx.rest.partition(" ")
    if not text.strip():
        raise ChatError("Foydalanish: /edit <id> <yangi matn>")
    mid = parse_id(head)
    msg, new_text = chat.edit(ctx.user, mid, text)
    await publish_edited(msg, new_text)


@command("del", "/del <id>", "xabarni o'chirish (o'zingiznikini; adminlar istalganini)", min_args=1)
async def del_cmd(ctx: Ctx) -> None:
    msg = chat.delete(ctx.user, parse_id(ctx.args[0]))
    await publish_deleted(msg)
