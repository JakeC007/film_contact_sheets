"""Read whatever EXIF a scan or digital file already has, and fill in blanks with it.

Film first: camera EXIF in a folder is ambiguous. It may be the camera that took
the photos (a digital set) or a camera used to scan film. So nothing from camera
EXIF is used until the user has said which, once per roll (Roll.exif_source).

Used without asking:
  * EXIF this app wrote itself (Software "film_contact_sheets"): it is the user's own
    film data, so it refills blanks if the roll file was lost.
  * Film-scanner EXIF (Noritsu, Frontier, Coolscan...): fills the Scanner field.

Only empty fields are ever filled; anything typed in the app wins over the file.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image

from .frames import file_number_label
from .model import DIGITAL, Frame, Roll
from .stops import format_aperture, format_shutter, seconds_to_shutter

OWN_SOFTWARE = "film_contact_sheets"

# Make / Model / Software text that means "this came off a film scanner".
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
TAG_FOCAL = 0x920A
TAG_LENS_MAKE, TAG_LENS_MODEL = 0xA433, 0xA434


@dataclass
class FileExif:
    make: str = ""
    model: str = ""
    software: str = ""
    fnumber: float | None = None
    exposure: float | None = None     # seconds
    iso: int | None = None
    focal: float | None = None        # mm
    lens: str = ""
    taken: datetime | None = None

    @property
    def is_own(self) -> bool:
        return self.software.lower().startswith(OWN_SOFTWARE)

    @property
    def is_scanner(self) -> bool:
        text = f"{self.make} {self.model} {self.software}".lower()
        return not self.is_own and any(h in text for h in SCANNER_HINTS)

    @property
    def is_camera(self) -> bool:
        """Camera EXIF from somewhere else: needs the user's decision before use."""
        return bool(self.device) and not self.is_own and not self.is_scanner

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
                    or self.taken or self.software)


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
            return _from_tags(ex, ex.get_ifd(_EXIF_IFD))
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
                         "FocalLength": TAG_FOCAL, "LensMake": TAG_LENS_MAKE,
                         "LensModel": TAG_LENS_MODEL}
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
        iso=int(_num(iso)) if _num(iso) else None, focal=_num(sub.get(TAG_FOCAL)),
        lens=lens, taken=_date(sub.get(TAG_DATETIME_ORIGINAL)),
    )


# --------------------------------------------------------------------------- survey

def survey(roll: Roll, folder: str | Path, frames: list[Frame] | None = None
           ) -> dict[str, FileExif]:
    """EXIF for the given frames (default: ones not checked yet), keyed by filename."""
    folder = Path(folder)
    todo = [f for f in roll.frames if not f.exif_read] if frames is None else frames
    out = {}
    for fr in todo:
        ex = read_file_exif(folder / fr.filename)
        if not ex.empty:
            out[fr.filename] = ex
    return out


def needs_decision(roll: Roll, found: dict[str, FileExif]) -> bool:
    return roll.exif_source == "" and any(ex.is_camera for ex in found.values())


def camera_summary(found: dict[str, FileExif]) -> str:
    """'Canon EOS 100D' or 'Canon EOS 100D, Sony ILCE-7M3', most common first."""
    counts = Counter(ex.device for ex in found.values() if ex.is_camera)
    return ", ".join(name for name, _ in counts.most_common(3))


# --------------------------------------------------------------------------- filling

@dataclass
class FillReport:
    files_with_exif: int = 0
    frames_filled: list[str] = field(default_factory=list)
    roll_fields: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not (self.frames_filled or self.roll_fields or self.notes):
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


def _unanimous(values):
    values = [v for v in values if v]
    return values[0] if values and all(v == values[0] for v in values) else None


def fill_from_exif(roll: Roll, folder: str | Path, frames: list[Frame] | None = None,
                   found: dict[str, FileExif] | None = None, exif_gear: bool = False
                   ) -> FillReport:
    """Fill empty fields from the files' EXIF, following roll.exif_source.

    `frames` defaults to frames not checked before (Frame.exif_read), so reopening a
    folder never brings back a value you deliberately cleared. `exif_gear=True` (used
    when a roll becomes digital) lets the files' camera and lens replace the roll's. Frames whose camera
    EXIF still awaits a decision are left unchecked so they're offered again.
    """
    todo = [f for f in roll.frames if not f.exif_read] if frames is None else frames
    if found is None:
        found = survey(roll, folder, todo)
    report = FillReport(files_with_exif=len(found))
    source = roll.exif_source

    by_kind: dict[str, list[tuple[Frame, FileExif]]] = {"own": [], "scanner": [], "camera": []}
    for fr in todo:
        ex = found.get(fr.filename)
        if ex is None:
            fr.exif_read = True
            continue
        kind = "own" if ex.is_own else "scanner" if ex.is_scanner else "camera"
        by_kind[kind].append((fr, ex))
        if kind != "camera" or source:
            fr.exif_read = True

    # Film scanners and camera-scan rigs both go in Scanner, never Camera.
    scan_devices = [ex.device or ex.software for _, ex in by_kind["scanner"]]
    if source == "scan":
        scan_devices += [ex.device for _, ex in by_kind["camera"]]
    if scan_devices and not roll.scanner.strip() and not roll.is_digital:
        sc = _unanimous(scan_devices)
        if sc:
            roll.scanner = sc
            report.roll_fields.append(f"scanner ({sc})")

    # This app's own tags are film data the user typed: refill blanks as film.
    _fill_frames(roll, by_kind["own"], report, digital=False)
    if by_kind["own"] and not roll.camera.strip():
        cam = _unanimous([ex.device for _, ex in by_kind["own"]])
        if cam:
            roll.camera = cam
            report.roll_fields.append(f"camera ({cam})")

    if source == DIGITAL:
        _fill_digital(roll, by_kind["camera"], report, replace_gear=exif_gear)
    return report


def _fill_digital(roll: Roll, items: list[tuple[Frame, FileExif]], report: FillReport,
                  replace_gear: bool = False) -> None:
    if not items:
        return
    roll.medium = DIGITAL
    exs = [ex for _, ex in items]
    # Most-used body and lens become the roll's; frames on anything else get their own.
    cams = Counter(ex.device for ex in exs if ex.device)
    if cams and (replace_gear or not roll.camera.strip()):
        roll.camera = cams.most_common(1)[0][0]
        report.roll_fields.append(f"camera ({roll.camera})")
    lenses = Counter(ex.lens for ex in exs if ex.lens)
    if lenses and (replace_gear or not roll.lens.strip()):
        roll.lens = lenses.most_common(1)[0][0]
        report.roll_fields.append(f"lens ({roll.lens})")
    if replace_gear:
        for fr, ex in items:      # re-derive per-frame body / lens against the new roll values
            if ex.device:
                fr.camera = "" if ex.device == roll.camera else ex.device
            if ex.lens:
                fr.lens = "" if ex.lens == roll.lens else ex.lens
    if len(cams) > 1:
        report.notes.append(f"Shot on {len(cams)} bodies; frames not on {roll.camera} "
                            "show their camera in the caption.")
    dates = [ex.taken for ex in exs if ex.taken]
    if dates and not roll.date.strip():
        roll.date = format_date_range(dates)
        report.roll_fields.append(f"date ({roll.date})")
    _fill_frames(roll, items, report, digital=True)


def _fill_frames(roll: Roll, items, report: FillReport, digital: bool) -> None:
    for fr, ex in items:
        changed = False
        if fr.aperture is None and ex.fnumber:
            fr.aperture = round(ex.fnumber, 1)
            changed = True
        if fr.shutter is None and ex.exposure:
            fr.shutter = seconds_to_shutter(ex.exposure)
            changed = True
        if not fr.lens and ex.lens and ex.lens != roll.lens:
            fr.lens = ex.lens
        if digital:
            if not fr.camera and ex.device:
                fr.camera = ex.device if ex.device != roll.camera else ""
            if fr.iso is None and ex.iso:
                fr.iso = ex.iso
            if fr.focal is None and ex.focal:
                fr.focal = round(ex.focal, 1)
            if not fr.taken and ex.taken:
                fr.taken = ex.taken.isoformat(timespec="seconds")
        if changed:
            report.frames_filled.append(
                f"{fr.label}: {format_aperture(fr.aperture)} {format_shutter(fr.shutter)}".strip())


# --------------------------------------------------------------------------- digital layout

def arrange_as_digital(roll: Roll) -> None:
    """Label frames by file number (IMG_7826 -> 7826) and order them by capture time."""
    used: set[str] = set()
    for fr in roll.frames:
        label = file_number_label(fr.filename)
        base, n = label, 2
        while label in used:
            label, n = f"{base}-{n}", n + 1
        fr.label = label
        used.add(label)
    roll.frames.sort(key=lambda f: (f.taken or "9999", f.filename.lower()))


def arrange_as_film(roll: Roll) -> None:
    """Back to edge numbers from the filenames (or 1, 2, 3...) in negative order."""
    from .frames import frame_label_from_name, label_sort_key
    used: set[str] = set()
    labels = []
    for fr in roll.frames:
        label = frame_label_from_name(fr.filename)
        labels.append(label if label and label not in used else None)
        if label:
            used.add(label)
    n = 1
    for fr, label in zip(roll.frames, labels):
        if label is None:
            while str(n) in used:
                n += 1
            label = str(n)
            used.add(label)
        fr.label = label
    if all(frame_label_from_name(f.filename) for f in roll.frames):
        roll.frames.sort(key=lambda f: label_sort_key(f.label))
    else:
        roll.frames.sort(key=lambda f: f.filename.lower())
