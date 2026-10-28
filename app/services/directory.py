"""A'zolar ro'yxati."""
from app.repositories import users
from app.roles import is_admin
from app.services import views


def members(viewer) -> list[dict]:
    admin = is_admin(viewer)
    return [views.member_view(r, admin_view=admin) for r in users.list_members(include_banned=admin)]
