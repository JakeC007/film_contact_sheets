"""Finding scans in a folder and reading film frame numbers from filenames.

Lab scans usually end with the edge-print frame number, e.g.
``jakechan106501-R1-072-34A.jpg`` -> frame "34A". Edge numbers run
00, 0, 1, 1A, 2, 2A ... so plain filename sorting puts them in the wrong order.
"""

from __future__ import annotations

import re
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff", ".png"}
# Seen in camera folders but not readable here (yet); reported so they aren't silently missing.
RAW_EXTENSIONS = {".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".raf",
                  ".rw2", ".orf", ".dng", ".pef", ".srw", ".3fr", ".iiq", ".x3f"}
OTHER_UNSUPPORTED = {".heic", ".heif", ".webp", ".avif", ".bmp", ".gif"}

# Files we write ourselves; never treat them as scans.
OWN_OUTPUT_MARKER = "contact_sheet"

_FRAME_RE = re.compile(r"(?:^|[-_ .#])(00|\d{1,2})(A?)$", re.IGNORECASE)


def list_scans(folder: str | Path) -> list[Path]:
    folder = Path(folder)
    files = [
        p for p in folder.iterdir()
        if p.is_file()
        and p.suffix.lower() in IMAGE_EXTENSIONS
        and OWN_OUTPUT_MARKER not in p.stem.lower()
        and not p.name.startswith(".")
    ]
    return sort_scans(files)


def frame_label_from_name(name: str) -> str | None:
    """Edge frame number from a filename ("34A", "00", "7"), or None."""
    stem = Path(name).stem
    m = _FRAME_RE.search(stem)
    if not m:
        return None
    number, suffix = m.group(1), m.group(2).upper()
    if number != "00":
        number = str(int(number))
    return number + suffix


def label_sort_key(label: str | None) -> tuple[int, float]:
    """Sort key for edge labels: 00 < 0 < 1 < 1A < 2. Unlabelled sorts last."""
    if not label:
        return (1, 0.0)
    m = re.fullmatch(r"(00|\d+)(A?)", label.strip(), re.IGNORECASE)
    if not m:
        return (1, 0.0)
    base = -1.0 if m.group(1) == "00" else float(m.group(1))
    return (0, base + (0.5 if m.group(2) else 0.0))


def _natural_key(name: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def sort_scans(paths: list[Path]) -> list[Path]:
    """Order by edge frame number when every file has one, else natural filename order."""
    labels = [frame_label_from_name(p.name) for p in paths]
    if paths and all(labels):
        return [p for _, p in sorted(zip(labels, paths),
                                     key=lambda lp: (label_sort_key(lp[0]), _natural_key(lp[1].name)))]
    return sorted(paths, key=lambda p: _natural_key(p.name))


def unsupported_files(folder: str | Path) -> dict[str, list[Path]]:
    """RAW files with no JPEG/TIFF/PNG twin, plus other image types we can't open."""
    folder = Path(folder)
    files = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]
    stems = {p.stem.lower() for p in files if p.suffix.lower() in IMAGE_EXTENSIONS}
    raw = [p for p in files if p.suffix.lower() in RAW_EXTENSIONS and p.stem.lower() not in stems]
    other = [p for p in files if p.suffix.lower() in OTHER_UNSUPPORTED]
    return {"raw": sorted(raw), "other": sorted(other)}


def unsupported_note(found: dict[str, list[Path]]) -> str:
    def kinds(paths):
        return ", ".join(sorted({p.suffix.upper().lstrip(".") for p in paths}))
    parts = []
    if found.get("raw"):
        parts.append(f"{len(found['raw'])} RAW file(s) ({kinds(found['raw'])}) without a JPEG")
    if found.get("other"):
        parts.append(f"{len(found['other'])} {kinds(found['other'])} file(s)")
    if not parts:
        return ""
    return "Skipped " + " and ".join(parts) + ": only JPEG, TIFF and PNG can be opened."


def file_number_label(name: str) -> str:
    """Digital label: the number in the filename ('IMG_7826.JPG' -> '7826', 'DSC00012' -> '12')."""
    stem = Path(name).stem
    m = re.search(r"(\d+)(?!.*\d)", stem)
    return str(int(m.group(1))) if m else stem
