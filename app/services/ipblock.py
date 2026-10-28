"""IP bloklash (spamga qarshi). Ro'yxat xotirada keshlanadi (bitta worker)."""
import time

from app.errors import ChatError
from app.netutil import normalize_ip
from app.repositories import activity as activity_repo
from app.repositories import ip_blocks
from app.roles import Role, role_of
from app.services import activity

_blocked: set[str] = set(ip_blocks.ips())


def is_blocked(ip: str) -> bool:
    return ip in _blocked


def listing() -> list[dict]:
    return [{"ip": r["ip"], "reason": r["reason"] or "", "ts": r["created_at"], "by": r["by_username"] or "?"}
            for r in ip_blocks.all_rows()]


def block(actor, raw_ip: str, reason: str, actor_ip: str) -> str:
    ip = normalize_ip(raw_ip)
    if not ip:
        raise ChatError("IP manzil noto'g'ri")
    if ip == actor_ip:
        raise ChatError("O'zingizning IP manzilingizni bloklab bo'lmaydi")
    if role_of(actor) < Role.OWNER and activity_repo.staff_used_ip(ip):
        raise ChatError("Bu IP'dan admin/ega foydalangan — uni faqat ega bloklay oladi")
    ip_blocks.add(ip, reason.strip()[:200], actor["id"], time.time())
    _blocked.add(ip)
    activity.record("ip_block", ip=actor_ip, user=actor, detail=f"{ip}" + (f" ({reason.strip()[:100]})" if reason.strip() else ""))
    return ip


def unblock(actor, raw_ip: str, actor_ip: str) -> str:
    ip = normalize_ip(raw_ip)
    if not ip:
        raise ChatError("IP manzil noto'g'ri")
    ip_blocks.remove(ip)
    _blocked.discard(ip)
    activity.record("ip_unblock", ip=actor_ip, user=actor, detail=ip)
    return ip
