"""Mijoz IP manzilini aniqlash va normallashtirish."""
from __future__ import annotations

import ipaddress

from app.config import settings


def normalize_ip(raw: str | None) -> str | None:
    """To'g'ri IP bo'lsa, yagona ko'rinishga keltiradi (IPv4-mapped IPv6 -> IPv4); aks holda None."""
    if not raw:
        return None
    try:
        addr = ipaddress.ip_address(raw.strip())
    except ValueError:
        return None
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return str(addr)


def real_ip(headers, client) -> str:
    """Haqiqiy mijoz IP'si.

    Render Cloudflare ortida ishlaydi va CF-Connecting-IP ni o'zi qo'yadi (mijoz soxtalashtira olmaydi).
    Bu sarlavha yo'q bo'lsa, uvicorn aniqlagan manzil (--proxy-headers) ishlatiladi.
    """
    if settings.trust_proxy:
        ip = normalize_ip(headers.get("cf-connecting-ip"))
        if ip:
            return ip
    host = getattr(client, "host", None) if client else None
    return normalize_ip(host) or host or "?"
