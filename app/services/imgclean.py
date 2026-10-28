"""Rasmni xavfsiz qayta kodlash: metadata (EXIF/GPS, kamera, ICC, XMP, izohlar) olib tashlanadi.

Yuklangan fayl "shundayligicha" saqlanmaydi: Pillow bilan ochiladi, piksellar yangi faylga yoziladi.
Shunda yashirin ma'lumotlar (joylashuv, qurilma modeli, sana) va fayl ichiga yashirilgan begona
kodlar (polyglot) ham tozalanadi. Rasmning yo'nalishi (EXIF orientation) piksellarga qo'llanadi.
"""
from dataclasses import dataclass
from io import BytesIO

from app.errors import ChatError

try:                                            # Pillow bo'lmasa server ishga tushmaydi emas, rasm qabul qilinmaydi
    from PIL import Image, ImageOps, ImageSequence
except ImportError:                             # pragma: no cover
    Image = None

MAX_PIXELS = 40_000_000       # ~40 Mpx dan kattasi rad etiladi (decompression bomb himoyasi)
MAX_SIDE = 2560               # undan kattasi kichraytiriladi
MAX_FRAMES = 300              # GIF/WEBP animatsiya kadrlari
THUMB_SIDE = 28               # xira ko'rinish (blur) uchun mitti nusxa
_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}
BAD = "Rasm buzilgan yoki qo'llab-quvvatlanmaydi"

if Image is not None:
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS


@dataclass
class Clean:
    data: bytes
    ext: str
    width: int
    height: int
    thumb: bytes


def _flat(im, bg=(34, 44, 56)):
    """Shaffoflikni fonga qo'shib, RGB qaytaradi."""
    im = im.convert("RGBA")
    base = Image.new("RGB", im.size, bg)
    base.paste(im, mask=im.getchannel("A"))
    return base


def _thumb(im) -> bytes:
    t = _flat(im) if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
    t.thumbnail((THUMB_SIDE, THUMB_SIDE))
    out = BytesIO()
    t.save(out, "JPEG", quality=55)
    return out.getvalue()


def _fit(im):
    if max(im.size) > MAX_SIDE:
        im = im.copy()
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return im


def clean(raw: bytes) -> Clean:
    if Image is None:
        raise ChatError("Serverda rasmlarni qayta ishlash moduli (Pillow) o'rnatilmagan", 500)
    try:
        im = Image.open(BytesIO(raw))
        fmt = im.format
        if fmt not in _EXT:
            raise ChatError("Faqat PNG, JPG, WEBP yoki GIF rasmlar mumkin")
        ext = _EXT[fmt]
        if im.width < 1 or im.height < 1 or im.width * im.height > MAX_PIXELS:
            raise ChatError("Rasm o'lchami juda katta")
        out = BytesIO()
        if getattr(im, "is_animated", False) and ext in ("gif", "webp"):
            if getattr(im, "n_frames", 1) > MAX_FRAMES:
                raise ChatError("Animatsiya juda uzun")
            duration, loop = im.info.get("duration", 80), im.info.get("loop", 0)
            frames = [_fit(f.convert("RGBA")) for f in ImageSequence.Iterator(im)]
            first = frames[0]
            first.save(out, ext.upper(), save_all=True, append_images=frames[1:], duration=duration,
                       loop=loop, disposal=2) if ext == "gif" else \
                first.save(out, "WEBP", save_all=True, append_images=frames[1:], duration=duration,
                           loop=loop, quality=85)
            w, h = first.size
            thumb = _thumb(first)
        else:
            im.load()
            im = ImageOps.exif_transpose(im) or im          # yo'nalishni piksellarga qo'llash
            im = _fit(im)
            if ext == "jpg":
                im = im.convert("RGB") if im.mode != "RGB" else im
            elif im.mode not in ("RGB", "RGBA", "L", "LA"):
                im = im.convert("RGBA")
            im.info = {}                                    # ICC, EXIF, XMP, izohlar — hammasi tashlanadi
            if ext == "jpg":
                im.save(out, "JPEG", quality=88, optimize=True, progressive=True)
            elif ext == "png":
                im.save(out, "PNG", optimize=True)
            elif ext == "webp":
                im.save(out, "WEBP", quality=88)
            else:                                           # bitta kadrli GIF
                im.convert("RGBA").save(out, "GIF")
            w, h = im.size
            thumb = _thumb(im)
        return Clean(out.getvalue(), ext, w, h, thumb)
    except ChatError:
        raise
    except Exception:                                       # buzuq fayl, bomba, kutubxona xatosi
        raise ChatError(BAD)
