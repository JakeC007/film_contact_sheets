"""Read whatever EXIF a scan or digital file already has, and fill in blanks with it.

Lab scans usually carry nothing, but digital files, scans from some scanners,
and files tagged by other tools do. Only empty fields are ever filled: anything
typed in the app wins over the file.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image

from .model import Frame, Roll
from .stops import format_aperture, format_shutter, seconds_to_shutter

# Make / Model / Software text that means "this came off a film scanner", so it
# belongs in the Scanner field rather than Camera.
SCANNER_HINTS = (
    "noritsu", "frontier", "fujifilm sp-", "coolscan", "epson", "perfection", "plustek",
    "opticfilm", "pakon", "imacon", "flextight", "hasselblad x", "silverfast", "vuescan",
    "canoscan", "pacific image", "reflecta", "kodak pakon", "ls-50", "ls-5000", "ls-9000",
    "hs-1800", "ls-600", "ls-1100", "ezcontroller", "ez controller",
)

_EXIF_IFD = 0x8769
TAG_MAKE, TAG_MODEL, TAG_SOFTWARE = 0x010F, 0x0110, 0x0131
TAG_FNUMBER, TAG_EXPOSURE, TAG_ISO = 0x829D, 0x829A, 0x8827
TAG_DATETIME_ORIGINAL = 0x9003   # when it was shot; IFD0 DateTime is often the scan date
TAG_LENS_MAKE, TAG_LENS_MODEL = 0xA433, 0xA434


@dataclass
class FileExif:
    make: str = ""
    model: str = ""
    software: str = ""
    fnumber: float | None = None
    exposure: float | None = None     # seconds
    iso: int | None = None
    lens: str = ""
    taken: datetime | None = None

    @property
    def is_scanner(self) -> bool:
        text = f"{self.make} {self.model} {self.software}".lower()
        return any(h in text for h in SCANNER_HINTS)

    @property
    def device(self) -> str:
        """'Canon EOS 100D' from Make 'Canon' + Model 'Canon EOS 100D'; avoids 'Canon Canon'."""
        make = self.make.replace("CORPORATION", "").replace("Corporation", "").strip(" ,.")
        model = self.model.strip()
        if not model:
            return make
        first = make.split()[0].lower() if make else ""
        if not make or model.lower().startswith(first):
            return model
        return f"{make} {model}"

    @property
    def empty(self) -> bool:
        return not (self.device or self.fnumber or self.exposure or self.iso or self.lens
                    or self.taken)


# --------------------------------------------------------------------------- reading

def _num(v) -> float | None:
    try:
        if isinstance(v, tuple) and len(v) == 2:
            return v[0] / v[1] if v[1] else None
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _text(v) -> str:
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    return str(v or "").replace("\x00", "").strip()


def _date(v) -> datetime | None:
    try:
        return datetime.strptime(_text(v)[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def read_file_exif(path: str | Path) -> FileExif:
    """Header-only read; never decodes pixels. Returns an empty FileExif if nothing's there."""
    path = Path(path)
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            sub = ex.get_ifd(_EXIF_IFD)
            return _from_tags(ex, sub)
    except Exception:
        pass
    if path.suffix.lower() in (".tif", ".tiff"):
        try:  # high-bit-depth TIFFs Pillow won't open
            import tifffile
            with tifffile.TiffFile(str(path)) as tf:
                tags = tf.pages[0].tags
                base = {code: tags[name].value for code, name in
                        ((TAG_MAKE, "Make"), (TAG_MODEL, "Model"), (TAG_SOFTWARE, "Software"))
                        if name in tags}
                exif = tags["ExifTag"].value if "ExifTag" in tags else {}
                names = {"FNumber": TAG_FNUMBER, "ExposureTime": TAG_EXPOSURE,
                         "ISOSpeedRatings": TAG_ISO, "DateTimeOriginal": TAG_DATETIME_ORIGINAL,
                         "LensMake": TAG_LENS_MAKE, "LensModel": TAG_LENS_MODEL}
                sub = {names[k]: v for k, v in exif.items() if k in names}
                return _from_tags(base, sub)
        except Exception:
            pass
    return FileExif()


def _from_tags(base, sub) -> FileExif:
    iso = sub.get(TAG_ISO)
    if isinstance(iso, (tuple, list)):
        iso = iso[0] if iso else None
    lens = _text(sub.get(TAG_LENS_MODEL))
    lens_make = _text(sub.get(TAG_LENS_MAKE))
    if lens and lens_make and not lens.lower().startswith(lens_make.lower()):
        lens = f"{lens_make} {lens}"
    return FileExif(
        make=_text(base.get(TAG_MAKE)), model=_text(base.get(TAG_MODEL)),
        software=_text(base.get(TAG_SOFTWARE)),
        fnumber=_num(sub.get(TAG_FNUMBER)), exposure=_num(sub.get(TAG_EXPOSURE)),
        iso=int(_num(iso)) if _num(iso) else None, lens=lens,
        taken=_date(sub.get(TAG_DATETIME_ORIGINAL)) or None,
    )


# --------------------------------------------------------------------------- filling

@dataclass
class FillReport:
    files_with_exif: int = 0
    frames_filled: list[str] = field(default_factory=list)
    roll_fields: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.files_with_exif:
            return ""
        parts = [f"Read EXIF from {self.files_with_exif} file(s)"]
        if self.frames_filled:
            parts.append(f"filled exposure on {len(self.frames_filled)} frame(s)")
        if self.roll_fields:
            parts.append("set " + ", ".join(self.roll_fields))
        text = "; ".join(parts) + "."
        if self.notes:
            text += " " + " ".join(self.notes)
        return text


def format_date_range(dates: list[datetime]) -> str:
    """'8 Nov 2026', '3-12 Oct 2026', '28 Oct - 3 Nov 2026', 'Dec 2025 - Jan 2026'."""
    lo, hi = min(dates), max(dates)
    if lo.date() == hi.date():
        return f"{lo.day} {lo:%b %Y}"
    if (lo.year, lo.month) == (hi.year, hi.month):
        return f"{lo.day}-{hi.day} {hi:%b %Y}"
    if lo.year == hi.year:
        return f"{lo.day} {lo:%b} - {hi.day} {hi:%b %Y}"
    return f"{lo:%b %Y} - {hi:%b %Y}"


def fill_from_exif(roll: Roll, folder: str | Path, frames: list[Frame] | None = None) -> FillReport:
    """Fill empty frame and roll fields from the files' own EXIF.

    `frames` defaults to frames not checked before (Frame.exif_read is False), so
    re-opening a folder never brings back a value you deliberately cleared.
    """
    folder = Path(folder)
    todo = [f for f in roll.frames if not f.exif_read] if frames is None else frames
    report = FillReport()
    found: dict[str, FileExif] = {}
    for fr in todo:
        fr.exif_read = True
        ex = read_file_exif(folder / fr.filename)
        if not ex.empty:
            found[fr.filename] = ex
    report.files_with_exif = len(found)
    if not found:
        return report

    cams = [ex for ex in found.values() if not ex.is_scanner]
    scanners = [ex for ex in found.values() if ex.is_scanner]

    # Roll fields, only when empty and the files agree.
    def unanimous(values):
        values = [v for v in values if v]
        return values[0] if values and all(v == values[0] for v in values) else None

    if not roll.camera.strip():
        cam = unanimous([ex.device for ex in cams])
        if cam:
            roll.camera = cam
            report.roll_fields.append(f"camera ({cam})")
    if not roll.scanner.strip():
        sc = unanimous([ex.device or ex.software for ex in scanners])
        if sc:
            roll.scanner = sc
            report.roll_fields.append(f"scanner ({sc})")

    lenses = Counter(ex.lens for ex in cams if ex.lens)
    if not roll.lens.strip() and lenses:
        roll.lens = lenses.most_common(1)[0][0]
        report.roll_fields.append(f"lens ({roll.lens})")

    isos = [ex.iso for ex in cams if ex.iso]
    if isos and not roll.box_iso and not roll.rated_iso:
        if len(set(isos)) == 1:
            roll.box_iso = isos[0]
            report.roll_fields.append(f"ISO ({isos[0]})")
        else:
            report.notes.append(f"ISO varies ({min(isos)}-{max(isos)}), so it was left blank.")

    dates = [ex.taken for ex in cams if ex.taken]
    if dates and not roll.date.strip():
        roll.date = format_date_range(dates)
        report.roll_fields.append(f"date ({roll.date})")

    # Frame fields, only when empty.
    for fr in todo:
        ex = found.get(fr.filename)
        if ex is None or ex.is_scanner:
            continue
        changed = False
        if fr.aperture is None and ex.fnumber:
            fr.aperture = round(ex.fnumber, 1)
            changed = True
        if fr.shutter is None and ex.exposure:
            fr.shutter = seconds_to_shutter(ex.exposure)
            changed = True
        if not fr.lens and ex.lens and ex.lens != roll.lens:
            fr.lens = ex.lens
        if changed:
            report.frames_filled.append(
                f"{fr.label}: {format_aperture(fr.aperture)} {format_shutter(fr.shutter)}".strip())
    return report
