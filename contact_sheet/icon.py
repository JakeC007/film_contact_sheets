"""The app icon, drawn in code so the repo needs no binary image files.

Used at runtime for the window / taskbar icon, and by contact_sheet.spec to
write the .ico embedded in the .exe.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

_TILE = (32, 32, 36, 255)
_BASE = (214, 122, 48, 255)      # orange C-41 film base
_FRAME = (245, 236, 214, 255)
_ACCENT = (240, 208, 60, 255)    # same yellow as the compact sheet captions


def icon_image(size: int = 256) -> Image.Image:
    """Square RGBA icon. Drawn at 4x and scaled down for clean edges."""
    k = 4
    S = 256 * k
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return [round(x0 * k), round(y0 * k), round(x1 * k), round(y1 * k)]

    d.rounded_rectangle(box(8, 8, 248, 248), radius=44 * k, fill=_TILE)
    # film strip
    d.rectangle(box(8, 70, 248, 186), fill=_BASE)
    # sprocket holes along both edges
    for i in range(8):
        x = 20 + i * 29
        d.rounded_rectangle(box(x, 78, x + 15, 92), radius=3 * k, fill=_TILE)
        d.rounded_rectangle(box(x, 164, x + 15, 178), radius=3 * k, fill=_TILE)
    # three frames, the middle one picked out
    for n, x in enumerate((22, 98, 174)):
        d.rectangle(box(x, 100, x + 62, 156), fill=_ACCENT if n == 1 else _FRAME)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def write_ico(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    icon_image(256).save(path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    return path


def app_qicon():
    """QIcon with every size, so Windows picks a sharp one for the taskbar."""
    from PySide6.QtGui import QIcon, QImage, QPixmap

    icon = QIcon()
    for s in ICO_SIZES:
        im = icon_image(s)
        q = QImage(im.tobytes("raw", "RGBA"), s, s, s * 4, QImage.Format_RGBA8888).copy()
        icon.addPixmap(QPixmap.fromImage(q))
    return icon
