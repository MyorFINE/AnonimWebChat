"""Brauzerda bajariladigan buyruqlar (server faqat /help uchun ro'yxatga oladi)."""
from app.commands.base import client_command

client_command("clear", "/clear", "ekranni tozalash")
client_command("logout", "/logout", "tizimdan chiqish")
