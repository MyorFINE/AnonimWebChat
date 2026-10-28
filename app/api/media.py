"""Fayllarni berish: /uploads/<nom>. Diskda shifrlangan fayl serverda ochilib, faqat tizimga kirgan foydalanuvchiga beriladi.
Lichka (shaxsiy) fayllari — faqat ikki ishtirokchiga. Fayl hech qachon sahifa sifatida emas, yuklab olinadigan sifatida beriladi."""
from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.deps import current_user
from app.errors import ChatError
from app.repositories import messages
from app.services import media

router = APIRouter(tags=["media"])


@router.get("/uploads/{name}")
def serve(name: str, user=Depends(current_user)):
    if not media.NAME_RE.match(name):
        raise ChatError("Topilmadi", 404)
    msg = messages.find_media(name)
    if not msg or (msg["recipient_id"] is not None and user["id"] not in (msg["user_id"], msg["recipient_id"])):
        raise ChatError("Topilmadi", 404)
    data = media.read(name)
    if data is None:
        raise ChatError("Topilmadi", 404)
    headers = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
    if name.endswith((".bin", ".e2e")):
        headers["Content-Disposition"] = 'attachment; filename="fayl"'
    return Response(content=data, media_type=media.content_type(name), headers=headers)
