"""SQLite ulanishi va sxema."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  nickname TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'user',            -- user | admin | owner
  banned INTEGER NOT NULL DEFAULT 0,
  ban_reason TEXT,
  muted_until REAL NOT NULL DEFAULT 0,
  mute_reason TEXT,
  active_avatar_id INTEGER,
  bio TEXT NOT NULL DEFAULT '',
  color TEXT,                                   -- admin/ega tanlagan profil rangi (#rrggbb)
  created_at REAL NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0,           -- 1 = akkaunt o'chirilgan ("Deleted account"), xabarlari qoladi
  deleted_at REAL
);
CREATE TABLE IF NOT EXISTS avatars(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  created_at REAL NOT NULL,
  edited_at REAL,
  deleted INTEGER NOT NULL DEFAULT 0,
  recipient_id INTEGER REFERENCES users(id) ON DELETE CASCADE,   -- NULL = umumiy chat, aks holda shaxsiy xabar
  read INTEGER NOT NULL DEFAULT 0,                               -- faqat shaxsiy xabarlar uchun
  image TEXT,                                                    -- yuklangan rasm fayl nomi
  reply_to INTEGER,                                              -- javob berilgan xabar id
  img_w INTEGER,                                                 -- rasm eni (piksel)
  img_h INTEGER                                                  -- rasm bo'yi (piksel)
);
CREATE TABLE IF NOT EXISTS logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,          -- edit | delete | mute | unmute | ban | unban | role
  message_id INTEGER,
  user_id INTEGER,             -- xabar egasi / nishon
  actor_id INTEGER,            -- amalni bajargan
  old_content TEXT,
  new_content TEXT,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS activity(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at REAL NOT NULL,
  ip TEXT,
  user_id INTEGER,
  username TEXT,               -- harakat vaqtidagi username (noma'lum foydalanuvchi urinishlari uchun ham)
  action TEXT NOT NULL,
  detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_ip ON activity(ip, id);
CREATE INDEX IF NOT EXISTS idx_activity_user ON activity(user_id, id);
CREATE INDEX IF NOT EXISTS idx_activity_time ON activity(created_at);
CREATE TABLE IF NOT EXISTS ip_blocks(
  ip TEXT PRIMARY KEY,
  reason TEXT,
  blocked_by INTEGER,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_settings(          -- moderatsiya sozlamalari (sekin rejim, qulf, taqiqlangan so'zlar)
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports(                -- foydalanuvchi shikoyatlari (umumiy chat xabarlari)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER NOT NULL,
  reporter_id INTEGER NOT NULL,
  target_id INTEGER NOT NULL,
  reason TEXT,                 -- shifrlangan
  snapshot TEXT,               -- shikoyat vaqtidagi xabar matni (shifrlangan)
  created_at REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',            -- open | closed
  handled_by INTEGER,
  handled_at REAL,
  action TEXT,
  UNIQUE(message_id, reporter_id)
);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, id);
CREATE TABLE IF NOT EXISTS room_epochs(            -- umumiy chat guruh kalitining avlodlari (E2EE); kalitning o'zi serverda YO'Q
  epoch INTEGER PRIMARY KEY,
  created_by INTEGER,
  created_at REAL NOT NULL,
  check_blob TEXT NOT NULL,    -- kalit to'g'riligini tekshirish uchun (kalit bilan shifrlangan); server uni ocha olmaydi
  reason TEXT
);
CREATE TABLE IF NOT EXISTS room_keys(              -- har bir a'zo uchun, uning OMMAVIY kaliti bilan o'ralgan guruh kaliti
  epoch INTEGER NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  wrapped TEXT NOT NULL,
  wrapper_id INTEGER,
  created_at REAL NOT NULL,
  PRIMARY KEY(epoch, user_id)
);
CREATE TABLE IF NOT EXISTS e2e_blobs(              -- E2EE fayllar: server faqat shifrlangan baytlarni saqlaydi
  name TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  size INTEGER NOT NULL,
  created_at REAL NOT NULL
);
"""


class Database:
    """Yupqa o'ramchi: bitta ulanish, lock bilan himoyalangan."""

    def __init__(self, path: Path):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        """Eski bazalarni yangi sxemaga o'tkazadi (ustun qo'shish) va indekslarni yaratadi."""
        def columns(table: str) -> set[str]:
            return {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}

        ucols = columns("users")
        if "bio" not in ucols:
            self._conn.execute("ALTER TABLE users ADD COLUMN bio TEXT NOT NULL DEFAULT ''")
        if "color" not in ucols:
            self._conn.execute("ALTER TABLE users ADD COLUMN color TEXT")
        if "deleted" not in ucols:
            self._conn.execute("ALTER TABLE users ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
        if "deleted_at" not in ucols:
            self._conn.execute("ALTER TABLE users ADD COLUMN deleted_at REAL")
        if "badge" not in ucols:
            self._conn.execute("ALTER TABLE users ADD COLUMN badge TEXT")          # emoji nishon (galochka o'rniga)
        if "badge_anim" not in ucols:
            self._conn.execute("ALTER TABLE users ADD COLUMN badge_anim TEXT")     # nishon animatsiyasi
        for col, ddl in (("ecdh_pub", "TEXT"), ("sign_pub", "TEXT"), ("key_blob", "TEXT"), ("kdf_iter", "INTEGER"),
                         ("auth_v", "INTEGER NOT NULL DEFAULT 0")):       # E2EE: ommaviy kalitlar, parol bilan o'ralgan maxfiy kalitlar
            if col not in ucols:
                self._conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
        if "warns" not in ucols:
            self._conn.execute("ALTER TABLE users ADD COLUMN warns INTEGER NOT NULL DEFAULT 0")
        mcols = columns("messages")
        if "recipient_id" not in mcols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN recipient_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
        if "read" not in mcols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN read INTEGER NOT NULL DEFAULT 0")
        if "image" not in mcols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN image TEXT")
        if "reply_to" not in mcols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN reply_to INTEGER")
        if "img_w" not in mcols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN img_w INTEGER")
        if "img_h" not in mcols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN img_h INTEGER")
        if "file" not in mcols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN file TEXT")        # rasm bo'lmagan fayl (shifrlangan nusxa nomi)
        if "file_name" not in mcols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN file_name TEXT")   # asl fayl nomi (shifrlangan)
        if "file_mime" not in mcols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN file_mime TEXT")
        if "file_size" not in mcols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN file_size INTEGER")  # rasm va fayllar uchun (bayt)
        if "e2e" not in mcols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN e2e INTEGER NOT NULL DEFAULT 0")   # 1 = content E2EE konvert (server ocha olmaydi)
        rcols = columns("reports")
        if "envelope" not in rcols:
            self._conn.execute("ALTER TABLE reports ADD COLUMN envelope TEXT")                    # shikoyat vaqtidagi shifrlangan xabar
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_group ON messages(recipient_id, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_dm ON messages(user_id, recipient_id, id)")

    def all(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def one(self, sql: str, args=()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def run(self, sql: str, args=()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur.lastrowid


db = Database(settings.db_path)
