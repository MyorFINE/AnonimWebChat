"""Rollar va ularning darajalari."""
from enum import IntEnum


class Role(IntEnum):
    USER = 0
    ADMIN = 1
    OWNER = 2

    @property
    def db_name(self) -> str:
        return self.name.lower()


def role_of(user) -> Role:
    return Role[user["role"].upper()]


def is_admin(user) -> bool:
    return role_of(user) >= Role.ADMIN
