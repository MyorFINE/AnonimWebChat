"""Buyruqlar reyestri, kontekst va dispetcher.

Yangi buyruq qo'shish:
    @command("ping", "/ping", "javob tekshiruvi")
    async def ping(ctx): await ctx.reply("pong")
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from app.errors import ChatError
from app.realtime.manager import manager
from app.roles import Role, role_of
from app.services import activity

Handler = Callable[["Ctx"], Awaitable[None]]


@dataclass
class Ctx:
    user: object            # users jadvali qatori
    name: str               # buyruq nomi (kichik harfda, "/"siz)
    rest: str               # buyruq nomidan keyingi xom matn
    token_hash: str
    ip: str = ""

    @property
    def args(self) -> list[str]:
        return self.rest.split()

    @classmethod
    def parse(cls, user, text: str, token_hash: str, ip: str = "") -> "Ctx":
        head, _, rest = text.strip().partition(" ")
        return cls(user=user, name=head[1:].lower(), rest=rest.strip(), token_hash=token_hash, ip=ip)

    async def reply(self, lines, level: str = "info") -> None:
        await manager.system(self.user["id"], lines, level)


@dataclass(frozen=True)
class Command:
    name: str
    usage: str
    description: str
    role: Role
    handler: Handler | None      # None = buyruq brauzerda (mijozda) bajariladi
    min_args: int = 0


_REGISTRY: dict[str, Command] = {}


def command(name: str, usage: str, description: str, role: Role = Role.USER, min_args: int = 0):
    def deco(fn: Handler) -> Handler:
        _REGISTRY[name] = Command(name, usage, description, role, fn, min_args)
        return fn
    return deco


def client_command(name: str, usage: str, description: str) -> None:
    _REGISTRY[name] = Command(name, usage, description, Role.USER, None)


def commands_for(role: Role) -> list[Command]:
    return [c for c in _REGISTRY.values() if c.role == role]


def parse_id(raw: str) -> int:
    raw = raw.lstrip("#")
    if not raw.isdigit():
        raise ChatError("ID raqam bo'lishi kerak (masalan #12)")
    return int(raw)


_ROLE_LABEL = {Role.ADMIN: "adminlar", Role.OWNER: "ega"}
_AUDITED = {"mute", "unmute", "ban", "unban", "addadmin", "rmadmin", "warn", "unwarn", "purge"}


async def dispatch(ctx: Ctx) -> None:
    cmd = _REGISTRY.get(ctx.name)
    if cmd is None:
        return await ctx.reply(f"Noma'lum buyruq: /{ctx.name}. /help ni yozing", "error")
    if role_of(ctx.user) < cmd.role:
        return await ctx.reply(f"Bu buyruq faqat {_ROLE_LABEL.get(cmd.role, 'foydalanuvchilar')} uchun", "error")
    if cmd.handler is None:
        return await ctx.reply("Bu buyruq faqat brauzerda ishlaydi", "error")
    if len(ctx.args) < cmd.min_args:
        return await ctx.reply(f"Foydalanish: {cmd.usage}", "error")
    try:
        await cmd.handler(ctx)
    except ChatError as e:
        await ctx.reply(e.message, "error")
    else:
        if ctx.name in _AUDITED:                    # /passwd kabi buyruqlar (parol bor) hech qachon yozilmaydi
            activity.record("mod", ip=ctx.ip, user=ctx.user, detail=f"/{ctx.name} {ctx.rest[:120]}".strip())
