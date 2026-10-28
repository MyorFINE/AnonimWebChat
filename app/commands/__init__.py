"""Buyruqlar paketi. Modullarni import qilish ularni reyestrga ro'yxatdan o'tkazadi (tartib = /help tartibi)."""
from app.commands import general, messaging, profile, moderation, owner, client  # noqa: F401
from app.commands.base import Ctx, dispatch  # noqa: F401
