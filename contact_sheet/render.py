"""Compose a contact sheet image from a Roll."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from .imaging import ImageLoadError, load_image
from .model import Frame, Roll

FRAME_ASPECT = 3 / 2  # 35mm

THEMES = {
    "dark": dict(bg=(0, 0, 0), cell=(18, 18, 18), text=(235, 235, 235),
                 dim=(150, 150, 150), accent=(245, 210, 60), error=(200, 70, 70)),
    "light": dict(bg=(244, 242, 238), cell=(225, 223, 219), text=(25, 25, 25),
                  dim=(110, 110, 110), accent=(170, 90, 0), error=(180, 40, 40)),
}


@dataclass
class SheetOptions:
    columns: int = 6
    cell_width: int = 640            # px width of each frame image
    gap: int = 14                    # px between cells
    margin: int = 48                 # px around the whole sheet
    theme: str = "dark"
    vertical: str = "rotate"         # "rotate" verticals to landscape, or "fit" upright
    show_filename: bool = False
    show_notes: bool = True
    title: str = ""                  # optional, shown above the film line


ProgressFn = Callable[[int, int], None]


# --------------------------------------------------------------------------- fonts

_FONT_CANDIDATES = {
    "regular": ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
    "bold": ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "mono": ["consola.ttf", "cour.ttf", "DejaVuSansMono.ttf", "LiberationMono-Regular.ttf"],
}
_FONT_DIRS = [
    Path("C:/Windows/Fonts"),
    Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/liberation"),
    Path("/usr/share/fonts/truetype/liberation2"),
]
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(kind: str, size: int) -> ImageFont.ImageFont:
    key = (kind, size)
    if key in _font_cache:
        return _font_cache[key]
    for name in _FONT_CANDIDATES[kind]:
        for d in _FONT_DIRS:
            p = d / name
            if p.exists():
                f = ImageFont.truetype(str(p), size)
                _font_cache[key] = f
                return f
        try:  # let FreeType search its own paths
            f = ImageFont.truetype(name, size)
            _font_cache[key] = f
            return f
        except OSError:
            continue
    f = ImageFont.load_default(size)
    _font_cache[key] = f
    return f


def _text_w(draw: ImageDraw.ImageDraw, text: str, f) -> int:
    return int(math.ceil(draw.textlength(text, font=f)))


def _ellipsize(draw, text: str, f, max_w: int) -> str:
    if _text_w(draw, text, f) <= max_w:
        return text
    while text and _text_w(draw, text + "…", f) > max_w:
        text = text[:-1]
    return text + "…" if text else ""


def _wrap(draw, text: str, f, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.splitlines():
        words, line = para.split(), ""
        for w in words:
            trial = f"{line} {w}".strip()
            if _text_w(draw, trial, f) <= max_w or not line:
                line = trial
            else:
                lines.append(line)
                line = w
        lines.append(line)
    return lines


# --------------------------------------------------------------------------- layout

def fit_frame(img: Image.Image, box_w: int, box_h: int, vertical: str, rotation: int) -> Image.Image:
    """Rotate as requested and scale to fit inside the box without cropping."""
    if rotation % 360:
        img = img.rotate(-(rotation % 360), expand=True)
    if vertical == "rotate" and img.height > img.width:
        img = img.rotate(90, expand=True)
    scale = min(box_w / img.width, box_h / img.height)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(size, Image.LANCZOS)


def render_sheet(roll: Roll, folder: str | Path, opts: SheetOptions | None = None,
                 progress: ProgressFn | None = None) -> Image.Image:
    opts = opts or SheetOptions()
    theme = THEMES.get(opts.theme, THEMES["dark"])
    folder = Path(folder)
    frames = roll.visible_frames()

    cw = opts.cell_width
    ch = round(cw / FRAME_ASPECT)
    s = cw / 640  # scale type with cell size
    cap_font = font("bold", max(12, round(22 * s)))
    cap_small = font("regular", max(11, round(19 * s)))
    cap_h = round(cap_font.size * 1.7)

    cols = max(1, opts.columns)
    rows = max(1, math.ceil(len(frames) / cols))
    grid_w = cols * cw + (cols - 1) * opts.gap
    width = grid_w + 2 * opts.margin

    # Header is measured on a scratch canvas first so its height is known.
    scratch = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    header_lines = _header_lines(roll, opts, scratch, grid_w, s)
    header_h = sum(h for *_, h in header_lines)
    header_h += round(28 * s) if header_lines else 0

    cell_total_h = cap_h + ch
    height = opts.margin * 2 + header_h + rows * cell_total_h + (rows - 1) * opts.gap

    sheet = Image.new("RGB", (width, height), theme["bg"])
    draw = ImageDraw.Draw(sheet)

    # Header
    y = opts.margin
    for kind, text, f, color, h in header_lines:
        x = opts.margin
        if kind == "pairs":
            for label, value in text:
                draw.text((x, y), label, font=f[0], fill=theme["dim"])
                x += _text_w(draw, label, f[0]) + round(8 * s)
                draw.text((x, y), value, font=f[1], fill=theme["text"])
                x += _text_w(draw, value, f[1]) + round(36 * s)
        else:
            draw.text((x, y), text, font=f, fill=theme[color])
        y += h

    # Frames
    top = opts.margin + header_h
    total = len(frames)
    for i, fr in enumerate(frames):
        r, c = divmod(i, cols)
        x0 = opts.margin + c * (cw + opts.gap)
        y0 = top + r * (cell_total_h + opts.gap)
        _draw_caption(draw, fr, roll, opts, theme, x0, y0, cw, cap_h, cap_font, cap_small, s)
        img_y = y0 + cap_h
        draw.rectangle([x0, img_y, x0 + cw - 1, img_y + ch - 1], fill=theme["cell"])
        try:
            img = load_image(folder / fr.filename, max_side=cw * 2)
            img = fit_frame(img, cw, ch, opts.vertical, fr.rotation)
            sheet.paste(img, (x0 + (cw - img.width) // 2, img_y + (ch - img.height) // 2))
        except (ImageLoadError, FileNotFoundError):
            cy = img_y + ch // 2 - cap_small.size
            for j, msg in enumerate(("Can't open file", fr.filename)):
                msg = _ellipsize(draw, msg, cap_small, cw - 20)
                draw.text((x0 + 10, cy + j * round(cap_small.size * 1.3)), msg,
                          font=cap_small, fill=theme["error"])
        if progress:
            progress(i + 1, total)

    return sheet


def _header_lines(roll: Roll, opts: SheetOptions, draw, max_w: int, s: float):
    """List of (kind, content, font, color, line_height)."""
    lines = []
    title_f = font("bold", round(40 * s))
    film_f = font("bold", round(34 * s))
    label_f = font("regular", round(22 * s))
    value_f = font("bold", round(22 * s))
    note_f = font("regular", round(21 * s))

    if opts.title.strip():
        lines.append(("text", _ellipsize(draw, opts.title.strip(), title_f, max_w),
                      title_f, "text", round(title_f.size * 1.35)))
    film_line = roll.film_line()
    if film_line:
        color = "accent" if opts.title.strip() else "text"
        f = film_f if opts.title.strip() else title_f
        lines.append(("text", _ellipsize(draw, film_line, f, max_w), f, color, round(f.size * 1.35)))

    pairs = [(k, v.strip()) for k, v in (
        ("Camera", roll.camera), ("Lens", roll.lens),
        ("Scanner", roll.scanner), ("Date", roll.date),
    ) if v and v.strip()]
    if pairs:
        # Split onto extra lines if they would overflow.
        row, row_w = [], 0
        gap = round(36 * s)
        for label, value in pairs:
            w = _text_w(draw, label, label_f) + round(8 * s) + _text_w(draw, value, value_f) + gap
            if row and row_w + w > max_w:
                lines.append(("pairs", row, (label_f, value_f), "text", round(value_f.size * 1.6)))
                row, row_w = [], 0
            row.append((label, _ellipsize(draw, value, value_f, max_w // 2)))
            row_w += w
        lines.append(("pairs", row, (label_f, value_f), "text", round(value_f.size * 1.6)))

    if opts.show_notes and roll.notes.strip():
        for ln in _wrap(draw, roll.notes.strip(), note_f, max_w):
            lines.append(("text", ln, note_f, "dim", round(note_f.size * 1.4)))
    return lines


def _draw_caption(draw, fr: Frame, roll: Roll, opts: SheetOptions, theme, x0, y0, cw, cap_h,
                  cap_font, cap_small, s):
    pad = round(4 * s)
    ty = y0 + (cap_h - cap_font.size) // 2 - round(2 * s)
    label = fr.label or "?"
    draw.text((x0 + pad, ty), label, font=cap_font, fill=theme["accent"])
    x = x0 + pad + max(_text_w(draw, label, cap_font), _text_w(draw, "00A", cap_font)) + round(14 * s)

    caption = fr.caption(roll.lens)
    remaining = x0 + cw - pad - x
    if caption:
        caption = _ellipsize(draw, caption, cap_font, remaining)
        draw.text((x, ty), caption, font=cap_font, fill=theme["text"])
        x += _text_w(draw, caption, cap_font) + round(16 * s)
        remaining = x0 + cw - pad - x

    extra = []
    if opts.show_notes and fr.note.strip():
        extra.append(fr.note.strip())
    if opts.show_filename:
        extra.append(fr.filename)
    if extra and remaining > 40 * s:
        text = _ellipsize(draw, "  ".join(extra), cap_small, remaining)
        sy = ty + (cap_font.size - cap_small.size)
        draw.text((x, sy), text, font=cap_small, fill=theme["dim"])


# --------------------------------------------------------------------------- output

def default_output_path(folder: str | Path, fmt: str = "jpg") -> Path:
    folder = Path(folder)
    return folder / f"{folder.name}_contact_sheet.{fmt}"


def save_sheet(img: Image.Image, path: str | Path) -> Path:
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        img.save(path, "JPEG", quality=92, subsampling=0, optimize=True)
    elif ext == ".png":
        img.save(path, "PNG", optimize=True)
    elif ext == ".pdf":
        img.save(path, "PDF", resolution=150)
    else:
        raise ValueError(f"Unsupported output format: {ext}")
    return path
