"""Write roll and frame details into the scans' EXIF.

JPEG: piexif, which inserts an EXIF block without re-encoding (no quality loss).
TIFF / PNG: ExifTool (https://exiftool.org), if it can be found.

Two modes:
  "copy"    write to <folder>/with_exif/<name> and leave the originals alone (default)
  "inplace" replace the originals (written to a temp file first, then swapped in)
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Callable

import piexif

from . import __version__
from .model import Frame, Roll
from .stops import shutter_seconds

COPY_DIR = "with_exif"
SOFTWARE = f"film_contact_sheets {__version__}"
PIEXIF_TYPES = {".jpg", ".jpeg"}
EXIFTOOL_TYPES = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}


@dataclass
class Tags:
    """Values to write for one frame. None means leave that tag alone."""
    fnumber: float | None = None
    exposure_time: float | None = None
    auto_exposure: bool = False
    iso: int | None = None
    camera: str = ""
    lens: str = ""
    description: str = ""


def tags_for(roll: Roll, fr: Frame) -> Tags:
    parts = [roll.film_line()]
    if roll.location.strip():
        parts.append(roll.location.strip())
    if fr.note:
        parts.append(fr.note)
    if roll.scanner:
        parts.append(f"Scanned on {roll.scanner}")
    return Tags(
        fnumber=fr.aperture,
        exposure_time=shutter_seconds(fr.shutter),
        auto_exposure=fr.shutter == "A",
        iso=roll.effective_iso,
        camera=roll.camera.strip(),
        lens=(fr.lens or roll.lens).strip(),
        description=". ".join(p for p in parts if p),
    )


@dataclass
class Report:
    written: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    out_dir: Path | None = None

    def summary(self) -> str:
        lines = [f"Wrote EXIF to {len(self.written)} file(s)"
                 + (f" in {self.out_dir}" if self.out_dir else ".")]
        if self.skipped:
            lines.append(f"Skipped {len(self.skipped)}: " +
                         "; ".join(f"{n} ({why})" for n, why in self.skipped[:5]))
        if self.failed:
            lines.append(f"Failed {len(self.failed)}: " +
                         "; ".join(f"{n} ({why})" for n, why in self.failed[:5]))
        return "\n".join(lines)


# --------------------------------------------------------------------------- exiftool lookup

def find_exiftool(configured: str | None = None) -> str | None:
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    base = Path(getattr(sys, "_MEIPASS", Path(sys.argv[0]).resolve().parent))
    exe_dir = Path(sys.executable).resolve().parent
    for d in (base, base / "exiftool", exe_dir, exe_dir / "exiftool"):
        candidates += [d / "exiftool.exe", d / "exiftool(-k).exe", d / "exiftool"]
    for c in candidates:
        if c.is_file():
            return str(c)
    return shutil.which("exiftool")


# --------------------------------------------------------------------------- piexif (JPEG)

def _rational(value: float, max_den: int = 100000) -> tuple[int, int]:
    f = Fraction(value).limit_denominator(max_den)
    return (f.numerator, f.denominator)


def _exposure_rational(seconds: float) -> tuple[int, int]:
    if seconds < 1:
        den = round(1 / seconds)
        if den > 0 and abs(1 / den - seconds) < 1e-6:
            return (1, den)
    return _rational(seconds, 1000)


def build_piexif(tags: Tags, existing: bytes | None = None) -> bytes:
    """EXIF block for tags, merged over whatever EXIF `existing` (JPEG bytes) already has."""
    try:
        data = piexif.load(existing) if existing else None
    except Exception:
        data = None
    data = data or {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    zeroth, exif = data.setdefault("0th", {}), data.setdefault("Exif", {})

    zeroth[piexif.ImageIFD.Software] = SOFTWARE.encode()
    if tags.camera:
        zeroth[piexif.ImageIFD.Model] = tags.camera.encode("utf-8")
    if tags.description:
        zeroth[piexif.ImageIFD.ImageDescription] = tags.description.encode("utf-8")
    if tags.fnumber is not None:
        exif[piexif.ExifIFD.FNumber] = _rational(tags.fnumber, 100)
    if tags.exposure_time is not None:
        exif[piexif.ExifIFD.ExposureTime] = _exposure_rational(tags.exposure_time)
    if tags.auto_exposure:
        exif[piexif.ExifIFD.ExposureProgram] = 3  # aperture priority
    if tags.iso:
        exif[piexif.ExifIFD.ISOSpeedRatings] = int(tags.iso)
    if tags.lens:
        exif[piexif.ExifIFD.LensModel] = tags.lens.encode("utf-8")
    # A stale embedded thumbnail can break some readers; drop it.
    data["thumbnail"] = None
    data["1st"] = {}
    try:
        return piexif.dump(data)
    except Exception:
        if existing is None:
            raise
        return build_piexif(tags, None)  # existing EXIF is malformed; start clean


def _write_jpeg(src: Path, dst: Path, tags: Tags) -> None:
    raw = src.read_bytes()
    # piexif.load() treats any bytes that aren't JPEG/TIFF/"Exif" data as a *filename*
    # and opens it (hMatoba/Piexif#124, unfixed). Only ever hand it real JPEG bytes.
    if raw[:3] != b"\xff\xd8\xff":
        raise ValueError("not a JPEG file")
    out = io.BytesIO()
    piexif.insert(build_piexif(tags, raw), raw, out)
    _atomic_write(dst, out.getvalue())


def _atomic_write(dst: Path, data: bytes) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".exif-", suffix=dst.suffix, dir=str(dst.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dst)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# --------------------------------------------------------------------------- exiftool (TIFF, PNG)

def exiftool_args(tags: Tags) -> list[str]:
    args = [f"-Software={SOFTWARE}"]
    if tags.camera:
        args.append(f"-Model={tags.camera}")
    if tags.description:
        args.append(f"-ImageDescription={tags.description}")
    if tags.fnumber is not None:
        args.append(f"-FNumber={tags.fnumber:g}")
    if tags.exposure_time is not None:
        num, den = _exposure_rational(tags.exposure_time)
        args.append(f"-ExposureTime={num}/{den}" if num == 1 and den != 1 else f"-ExposureTime={tags.exposure_time:g}")
    if tags.auto_exposure:
        args.append("-ExposureProgram=3")
    if tags.iso:
        args.append(f"-ISO={int(tags.iso)}")
    if tags.lens:
        args.append(f"-LensModel={tags.lens}")
    return args


def _write_exiftool(exiftool: str, src: Path, dst: Path, tags: Tags) -> None:
    # Arguments go through a UTF-8 arg file so accents and spaces survive on Windows.
    lines = ["-charset", "filename=utf8", "-charset", "exif=utf8", "-m", "-q"]
    lines += exiftool_args(tags)
    tmp_out = None
    if src == dst:
        lines.append("-overwrite_original")
        lines.append(str(src))
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp_out = dst.with_name(f".exif-{os.getpid()}-{dst.name}")
        if tmp_out.exists():
            tmp_out.unlink()
        lines += ["-o", str(tmp_out), str(src)]

    fd, argfile = tempfile.mkstemp(prefix="exiftool-", suffix=".args")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # stdin=DEVNULL matters: the stock "exiftool(-k).exe" waits for Enter before exiting,
        # which would block forever with no console to press it in.
        proc = subprocess.run([exiftool, "-@", argfile], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL,
                              encoding="utf-8", errors="replace", timeout=120, creationflags=flags)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout).strip() or f"exit code {proc.returncode}")
        if tmp_out is not None:
            os.replace(tmp_out, dst)
    finally:
        os.remove(argfile)
        if tmp_out is not None and tmp_out.exists():
            tmp_out.unlink()


# --------------------------------------------------------------------------- driver

def write_roll_exif(roll: Roll, folder: str | Path, mode: str = "copy",
                    exiftool: str | None = None,
                    progress: Callable[[int, int], None] | None = None) -> Report:
    if mode not in ("copy", "inplace"):
        raise ValueError(f"Unknown mode {mode!r}")
    folder = Path(folder)
    report = Report(out_dir=folder / COPY_DIR if mode == "copy" else None)
    total = len(roll.frames)

    for n, fr in enumerate(roll.frames, start=1):
        src = folder / fr.filename
        dst = src if mode == "inplace" else folder / COPY_DIR / fr.filename
        ext = src.suffix.lower()
        try:
            tags = tags_for(roll, fr)
            if not src.exists():
                report.skipped.append((fr.filename, "file missing"))
            elif ext in PIEXIF_TYPES:
                _write_jpeg(src, dst, tags)
                report.written.append(fr.filename)
            elif ext in EXIFTOOL_TYPES:
                if not exiftool:
                    report.skipped.append((fr.filename, "needs ExifTool"))
                else:
                    _write_exiftool(exiftool, src, dst, tags)
                    report.written.append(fr.filename)
            else:
                report.skipped.append((fr.filename, "unsupported type"))
        except Exception as exc:
            report.failed.append((fr.filename, str(exc)))
        if progress:
            progress(n, total)
    return report
