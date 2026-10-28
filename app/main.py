"""Ilova fabrikasi: Anonim Chat by Hevorix."""
import logging
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import admin as admin_api
from app.api import auth as auth_api
from app.api import e2ee as e2ee_api
from app.api import media as media_api
from app.api import avatars as avatars_api
from app.api import social as social_api
from app.api import ws as ws_api
from app import crypto, sri
from app.config import ROOT, settings
from app.db import db
from app.errors import ChatError
from app.netutil import real_ip
from app.services import activity, bootstrap, ipblock, media
from app.transport import TunnelMiddleware

STATIC_DIR = ROOT / "app" / "static"
_blocked_logged: dict[str, float] = {}

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; "
       "connect-src 'self' ws: wss:; manifest-src 'self'; object-src 'none'; frame-src 'none'; worker-src 'none'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = FastAPI(title="Anonim Chat by Hevorix", version=__version__, docs_url=None, redoc_url=None)
    crypto.migrate_legacy(db)                     # eski ochiq matnlar bir marta shifrlanadi
    media.migrate_legacy()                        # eski ochiq fayllar bir marta shifrlanadi
    bootstrap.ensure_owner()                      # @Hevorix doim mavjud

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        path = request.url.path
        if path != "/healthz":
            ip = real_ip(request.headers, request.client)
            if ipblock.is_blocked(ip):            # bloklangan IP: hech narsa ko'rsatilmaydi
                now = time.monotonic()
                if now - _blocked_logged.get(ip, 0) > 60:      # bir IP'dan daqiqada ko'pi bilan 1 ta yozuv
                    _blocked_logged[ip] = now
                    activity.record("blocked", ip=ip, detail=f"{request.method} {path}"[:120])
                if path.startswith("/api/"):
                    return JSONResponse({"detail": "IP manzilingiz bloklangan"}, status_code=403)
                return PlainTextResponse("403 — IP manzilingiz bloklangan", status_code=403)
        response = await call_next(request)
        if path.startswith("/avatars/"):
            response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(self), geolocation=(), payment=(), usb=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if path.startswith("/api/") or path == "/":
            response.headers.setdefault("Cache-Control", "no-store")
        elif path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.exception_handler(ChatError)
    async def chat_error(_: Request, exc: ChatError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, __: RequestValidationError):
        return JSONResponse({"detail": "Ma'lumotlar noto'g'ri to'ldirilgan"}, status_code=422)

    app.add_middleware(TunnelMiddleware)          # eng tashqi qatlam: shifrlangan so'rovlarni ochadi

    app.include_router(auth_api.router)
    app.include_router(avatars_api.router)
    app.include_router(e2ee_api.router)
    app.include_router(social_api.router)
    app.include_router(media_api.router)
    app.include_router(admin_api.router)
    app.include_router(ws_api.router)

    app.mount("/avatars", StaticFiles(directory=settings.avatars_dir), name="avatars")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return HTMLResponse(sri.render_index(STATIC_DIR))

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
