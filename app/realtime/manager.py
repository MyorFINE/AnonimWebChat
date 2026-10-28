"""WebSocket ulanishlari va xabar tarqatish (bitta jarayon uchun)."""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("termchat.realtime")


class ConnectionManager:
    def __init__(self) -> None:
        self._conns: dict[int, set[Any]] = {}
        self._ips: dict[Any, str] = {}          # ws -> mijoz IP'si (IP bloklanganda ulanishlarni uzish uchun)

    # --- ulanish hayoti
    def connect(self, uid: int, ws: Any, ip: str = "") -> bool:
        """True qaytsa - bu foydalanuvchining birinchi ulanishi."""
        first = not self._conns.get(uid)
        if ip:
            self._ips[ws] = ip
        self._conns.setdefault(uid, set()).add(ws)
        return first

    def disconnect(self, uid: int, ws: Any) -> bool:
        """True qaytsa - foydalanuvchining oxirgi ulanishi yopildi."""
        self._ips.pop(ws, None)
        sockets = self._conns.get(uid)
        if not sockets:
            return False
        sockets.discard(ws)
        if not sockets:
            self._conns.pop(uid, None)
            return True
        return False

    # --- holat
    def is_online(self, uid: int) -> bool:
        return bool(self._conns.get(uid))

    def online_ids(self) -> list[int]:
        return [uid for uid, s in self._conns.items() if s]

    def count(self) -> int:
        return len(self.online_ids())

    # --- yuborish
    @staticmethod
    async def _send(ws: Any, payload: dict) -> None:
        import json
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            pass          # uzilgan ulanish: disconnect() o'zi tozalaydi

    async def send_to(self, uid: int, payload: dict) -> None:
        for ws in list(self._conns.get(uid, ())):
            await self._send(ws, payload)

    async def send_many(self, uids, payload: dict) -> None:
        for uid in dict.fromkeys(uids):          # takrorlarsiz, tartibni saqlab
            await self.send_to(uid, payload)

    async def broadcast(self, payload: dict, exclude_uid: int | None = None) -> None:
        for uid, sockets in list(self._conns.items()):
            if uid == exclude_uid:
                continue
            for ws in list(sockets):
                await self._send(ws, payload)

    @staticmethod
    def _sys(lines, level: str) -> dict:
        return {"type": "system", "level": level, "lines": [lines] if isinstance(lines, str) else lines}

    async def system(self, uid: int, lines, level: str = "info") -> None:
        await self.send_to(uid, self._sys(lines, level))

    async def broadcast_system(self, lines, level: str = "info", exclude_uid: int | None = None) -> None:
        await self.broadcast(self._sys(lines, level), exclude_uid=exclude_uid)

    async def kick_ip(self, ip: str, code: int) -> int:
        """Shu IP'dan ulangan barcha WebSocket'larni uzadi. Uzilganlar sonini qaytaradi."""
        n = 0
        for ws, wip in list(self._ips.items()):
            if wip == ip:
                n += 1
                try:
                    await ws.close(code)
                except Exception:
                    pass
        return n

    async def kick(self, uid: int, code: int) -> None:
        for ws in list(self._conns.get(uid, ())):
            try:
                await ws.close(code)
            except Exception:
                pass


manager = ConnectionManager()
