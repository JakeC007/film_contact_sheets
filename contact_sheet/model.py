"""Roll and frame data, saved as JSON next to the scans so work can be resumed."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import frames as frames_mod
from .stops import format_aperture, format_shutter, push_pull_label

ROLL_FILE = "contact_sheet_roll.json"
SCHEMA_VERSION = 1


@dataclass
class Frame:
    filename: str
    label: str = ""                 # edge frame number shown on the sheet
    aperture: float | None = None   # None = unknown
    shutter: str | None = None      # canonical, see stops.parse_shutter
    lens: str = ""                  # per-frame override; blank = roll lens
    note: str = ""
    hidden: bool = False            # leave off the sheet (blank / misfire)
    rotation: int = 0               # extra clockwise rotation, multiple of 90
    exif_read: bool = False         # the file's own EXIF has been checked once already
    # Digital rolls only (film frames share the roll's ISO and have no capture time):
    iso: int | None = None
    focal: float | None = None      # focal length in mm, from EXIF
    taken: str = ""                 # capture time, ISO 8601, from EXIF
    camera: str = ""                # body that took this frame, from EXIF

    def caption(self, roll_lens: str = "", roll_camera: str = "") -> str:
        parts = [format_aperture(self.aperture), format_shutter(self.shutter)]
        if self.iso:
            parts.append(f"ISO {self.iso}")
        if self.focal:
            parts.append(f"{self.focal:g}mm")
        if self.camera and self.camera != roll_camera:   # second body in a digital set
            parts.append(self.camera)
        if self.lens and self.lens != roll_lens:
            parts.append(self.lens)
        return "  ".join(p for p in parts if p)

    def has_exposure(self) -> bool:
        return self.aperture is not None or self.shutter is not None


FILM, DIGITAL = "film", "digital"

# What camera EXIF in a folder means, decided once per roll by the user:
#   ""        not asked yet          "digital"  photos taken with that camera
#   "scan"    film scanned with it   "ignore"   leave the EXIF alone
EXIF_SOURCES = ("", "scan", "digital", "ignore")


@dataclass
class Roll:
    title: str = ""
    medium: str = FILM              # "film" or "digital"
    exif_source: str = ""
    film: str = ""
    box_iso: int | None = None
    rated_iso: int | None = None
    camera: str = ""
    lens: str = ""
    scanner: str = ""
    date: str = ""                  # free text, e.g. "3-12 Oct 2026"
    location: str = ""
    lab: str = ""                   # who developed / scanned it
    notes: str = ""
    frames: list[Frame] = field(default_factory=list)

    # ----------------------------------------------------------------- display

    @property
    def is_digital(self) -> bool:
        return self.medium == DIGITAL

    @property
    def effective_iso(self) -> int | None:
        return self.rated_iso or self.box_iso

    def iso_range(self) -> str:
        """Digital: '6400' or '3200-6400' from the visible frames' own ISO."""
        isos = sorted({f.iso for f in self.visible_frames() if f.iso})
        if not isos:
            return str(self.effective_iso or "")
        return str(isos[0]) if len(isos) == 1 else f"{isos[0]}-{isos[-1]}"

    def film_line(self) -> str:
        """e.g. 'Kodak Portra 400 @ ISO 800 (+1)', 'Kodak Gold 200, ISO 200', 'Digital, ISO 3200-6400'."""
        if self.is_digital:
            iso = self.iso_range()
            return f"Digital, ISO {iso}" if iso else "Digital"
        film = self.film.strip()
        box, rated = self.box_iso, self.rated_iso
        if rated and box and rated != box:
            push = push_pull_label(box, rated)
            iso = f"@ ISO {rated}" + (f" ({push})" if push else "")
            return f"{film} {iso}".strip()
        iso = box or rated
        if film and iso:
            return f"{film}, ISO {iso}"
        if iso:
            return f"ISO {iso}"
        return film

    def cameras_used(self) -> list[str]:
        """Roll camera plus any other bodies frames were shot on, in first-use order."""
        out: list[str] = []
        for cam in [self.camera] + [f.camera for f in self.frames if not f.hidden]:
            cam = (cam or "").strip()
            if cam and cam not in out:
                out.append(cam)
        return out

    def lenses_used(self) -> list[str]:
        """Roll lens plus any per-frame overrides, in first-use order."""
        out: list[str] = []
        for lens in [self.lens] + [f.lens for f in self.frames if not f.hidden]:
            lens = (lens or "").strip()
            if lens and lens not in out:
                out.append(lens)
        return out

    def visible_frames(self) -> list[Frame]:
        return [f for f in self.frames if not f.hidden]

    # ----------------------------------------------------------------- persistence

    def to_dict(self) -> dict:
        d = asdict(self)
        d["schema"] = SCHEMA_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Roll":
        frame_keys = {f.name for f in fields(Frame)}
        roll_keys = {f.name for f in fields(cls)} - {"frames"}
        frames = [Frame(**{k: v for k, v in fd.items() if k in frame_keys})
                  for fd in d.get("frames", [])]
        roll = cls(**{k: v for k, v in d.items() if k in roll_keys})
        roll.frames = frames
        return roll


def roll_path(folder: str | Path) -> Path:
    return Path(folder) / ROLL_FILE


def save_roll(roll: Roll, folder: str | Path) -> Path:
    """Write atomically so a crash mid-save cannot wipe out entered data."""
    path = roll_path(folder)
    data = json.dumps(roll.to_dict(), indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(prefix=".roll-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return path


def load_roll(folder: str | Path) -> Roll:
    """Load saved data for a folder and reconcile it with the scans on disk.

    Frames for files that still exist keep their data and order; new files are
    appended in edge-number order; frames whose file is gone are dropped.
    """
    folder = Path(folder)
    path = roll_path(folder)
    roll = Roll()
    if path.exists():
        roll = Roll.from_dict(json.loads(path.read_text(encoding="utf-8")))

    on_disk = frames_mod.list_scans(folder)
    disk_names = [p.name for p in on_disk]
    known = {f.filename: f for f in roll.frames}

    kept = [f for f in roll.frames if f.filename in set(disk_names)]
    new = [Frame(filename=n) for n in disk_names if n not in known]

    used = {f.label for f in kept if f.label}
    next_index = len(kept) + 1
    for fr in new:
        label = frames_mod.frame_label_from_name(fr.filename)
        if not label or label in used:
            while str(next_index) in used:
                next_index += 1
            label = str(next_index)
        fr.label = label
        used.add(label)
        next_index += 1

    roll.frames = kept + new
    return roll
