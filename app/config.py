"""Markaziy sozlamalar. Qiymatlar TERMCHAT_* muhit o'zgaruvchilari yoki .env fayldan olinadi."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env(name: str, default):
    raw = os.getenv(f"TERMCHAT_{name}")
    if raw is None or raw == "":
        return default
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return type(default)(raw)


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    tz_offset: int               # logdagi vaqt uchun UTC dan farq (Toshkent = 5)
    max_message_length: int
    history_limit: int
    max_avatars: int
    max_avatar_bytes: int
    max_media_bytes: int         # chatga yuboriladigan har qanday fayl (rasm, video, hujjat...) hajmi
    msg_rate_count: int          # window ichida ruxsat etilgan xabarlar soni
    msg_rate_window: int
    login_attempts: int          # (ip, username) uchun window ichidagi urinishlar
    login_window: int
    register_attempts: int       # ip uchun window ichida
    register_window: int
    default_mute_minutes: int
    admin_password: str          # Hevorix (ega) paroli; bo'sh bo'lsa birinchi ishga tushirishda tasodifiy yaratiladi
    trust_proxy: bool            # CF-Connecting-IP sarlavhasiga ishonish (Render/Cloudflare ortida True)
    activity_days: int           # harakatlar logi necha kun saqlanadi
    master_key: str              # bazadagi ma'lumotlarni shifrlash kaliti (bo'sh bo'lsa data/master.key yaratiladi)
    require_tunnel: bool         # True: /api faqat shifrlangan kanal (/api/x) orqali ishlaydi
    require_e2ee: bool           # True (standart): server ochiq matnli xabarni qabul qilmaydi, faqat E2EE konvert
    e2e_max_envelope: int        # E2EE konvertining eng katta hajmi (belgi)

    @property
    def master_key_path(self) -> Path:
        return self.data_dir / "master.key"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "chat.db"

    @property
    def avatars_dir(self) -> Path:
        return self.data_dir / "avatars"

    @property
    def uploads_dir(self) -> Path:
        """ESKI (shifrlanmagan) fayllar. Yangi fayllar `media_dir` da shifrlangan holda saqlanadi."""
        return self.data_dir / "uploads"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @classmethod
    def load(cls) -> "Settings":
        _load_dotenv(ROOT / ".env")
        data_dir = Path(_env("DATA_DIR", str(ROOT / "data"))).resolve()
        # Render va boshqa hostinglar portni PORT o'zgaruvchisi orqali beradi
        port = int(os.getenv("TERMCHAT_PORT") or os.getenv("PORT") or 8000)
        s = cls(
            host=_env("HOST", "0.0.0.0"),
            port=port,
            data_dir=data_dir,
            tz_offset=_env("TZ_OFFSET", 5),
            max_message_length=_env("MAX_MESSAGE_LENGTH", 1000),
            history_limit=_env("HISTORY_LIMIT", 100),
            max_avatars=_env("MAX_AVATARS", 3),
            max_avatar_bytes=_env("MAX_AVATAR_BYTES", 2 * 1024 * 1024),
            max_media_bytes=_env("MAX_MEDIA_BYTES", 50 * 1024 * 1024),
            msg_rate_count=_env("MSG_RATE_COUNT", 5),
            msg_rate_window=_env("MSG_RATE_WINDOW", 5),
            login_attempts=_env("LOGIN_ATTEMPTS", 8),
            login_window=_env("LOGIN_WINDOW", 300),
            register_attempts=_env("REGISTER_ATTEMPTS", 10),
            register_window=_env("REGISTER_WINDOW", 3600),
            default_mute_minutes=_env("DEFAULT_MUTE_MINUTES", 10),
            admin_password=_env("ADMIN_PASSWORD", ""),
            trust_proxy=_env("TRUST_PROXY", True),
            activity_days=_env("ACTIVITY_DAYS", 90),
            master_key=_env("MASTER_KEY", ""),
            require_tunnel=_env("REQUIRE_TUNNEL", True),
            require_e2ee=_env("REQUIRE_E2EE", True),
            e2e_max_envelope=_env("E2E_MAX_ENVELOPE", 16384),
        )
        s.avatars_dir.mkdir(parents=True, exist_ok=True)
        s.uploads_dir.mkdir(parents=True, exist_ok=True)
        s.media_dir.mkdir(parents=True, exist_ok=True)
        return s


settings = Settings.load()
