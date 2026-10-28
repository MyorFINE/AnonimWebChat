"""Subresource Integrity (SRI): index.html dagi `data-sri` belgili <script>/<link> teglariga
`integrity="sha384-…"` va versiya (?v=) avtomatik qo'shiladi. Fayl o'zgarsa, hash ham o'zgaradi."""
from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

_TAG = re.compile(r"<(?:script|link)\b[^>]*\bdata-sri\b[^>]*>", re.I)
_URL = re.compile(r'\b(src|href)="(/static/[^"?#]+)"')
_cache: dict[Path, tuple[float, str]] = {}


def digest(path: Path) -> str:
    mtime = path.stat().st_mtime
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    raw = path.read_bytes()
    value = "sha384-" + base64.b64encode(hashlib.sha384(raw).digest()).decode()
    _cache[path] = (mtime, value)
    return value


def render_index(static_dir: Path) -> str:
    html = (static_dir / "index.html").read_text(encoding="utf-8")

    def fix(m: re.Match) -> str:
        tag = m.group(0)
        u = _URL.search(tag)
        if not u:
            return tag
        f = static_dir / u.group(2)[len("/static/"):]
        if not f.is_file():
            return tag
        sri = digest(f)
        ver = hashlib.sha1(sri.encode()).hexdigest()[:8]
        tag = tag.replace(u.group(0), f'{u.group(1)}="{u.group(2)}?v={ver}"')
        return re.sub(r"\bdata-sri\b", f'integrity="{sri}" crossorigin="anonymous"', tag, count=1)

    return _TAG.sub(fix, html)
