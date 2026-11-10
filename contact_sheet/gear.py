"""Saved cameras and lenses, with the exposure limits of each.

Stored in %APPDATA%\\film_contact_sheets\\gear.json. Edit it from the app
(Gear > Cameras & lenses…) or by hand; the file is created with a Pentax MX
kit on first run.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .stops import (FULL_APERTURES, FULL_SHUTTERS, ParseError, format_aperture, format_shutter,
                    parse_aperture, parse_shutter, shutter_seconds)


@dataclass
class Camera:
    name: str
    fastest: str = "1/1000"      # canonical shutter strings, see stops.parse_shutter
    slowest: str = "1s"
    bulb: bool = True
    notes: str = ""

    def validate(self) -> None:
        if not self.name.strip():
            raise ParseError("Camera needs a name")
        fast, slow = _seconds(self.fastest, "fastest"), _seconds(self.slowest, "slowest")
        if fast > slow:
            raise ParseError(f"{self.name}: fastest speed is slower than slowest")


@dataclass
class Lens:
    name: str
    widest: float = 2.0          # maximum aperture, the smallest f-number
    smallest: float = 22.0       # minimum aperture, the largest f-number
    notes: str = ""

    def validate(self) -> None:
        if not self.name.strip():
            raise ParseError("Lens needs a name")
        if not (0.5 <= self.widest <= self.smallest <= 128):
            raise ParseError(f"{self.name}: widest aperture must be below smallest (e.g. 1.7 and 22)")


def _seconds(shutter: str, what: str) -> float:
    s = shutter_seconds(parse_shutter(shutter))
    if s is None:
        raise ParseError(f"{what} shutter speed must be a time, e.g. 1/1000 or 1s")
    return s


# Pentax MX: mechanical cloth focal-plane shutter, 1 s to 1/1000 plus B, X-sync 1/60.
# Lens ranges are the usual SMC Pentax-M specs; edit them if your copy differs.
DEFAULT_CAMERAS = [
    Camera("Pentax MX", fastest="1/1000", slowest="1s", bulb=True,
           notes="Mechanical shutter. Flash sync 1/60."),
]
DEFAULT_LENSES = [
    Lens("SMC Pentax-M 50mm f/1.7", widest=1.7, smallest=22.0),
    Lens("SMC Pentax-M 50mm f/1.4", widest=1.4, smallest=22.0),
    Lens("SMC Pentax-M 28mm f/2.8", widest=2.8, smallest=22.0),
]


def default_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "film_contact_sheets" / "gear.json"


@dataclass
class Gear:
    cameras: list[Camera] = field(default_factory=list)
    lenses: list[Lens] = field(default_factory=list)
    path: Path | None = None
    load_error: str = ""

    # ------------------------------------------------------------------ persistence

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Gear":
        """Load gear.json, creating it with the defaults if it does not exist yet."""
        p = Path(path) if path else default_path()
        if not p.exists():
            gear = cls.defaults(p)
            try:
                gear.save()
            except OSError:
                pass
            return gear
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Unreadable file: use defaults for this session but don't overwrite the user's file.
            gear = cls.defaults(p)
            gear.load_error = f"Couldn't read {p}; using the built-in list for now."
            return gear
        cam_keys = {f.name for f in fields(Camera)}
        lens_keys = {f.name for f in fields(Lens)}
        cams = [Camera(**{k: v for k, v in c.items() if k in cam_keys})
                for c in data.get("cameras", []) if isinstance(c, dict) and c.get("name")]
        lenses = [Lens(**{k: v for k, v in l.items() if k in lens_keys})
                  for l in data.get("lenses", []) if isinstance(l, dict) and l.get("name")]
        for l in lenses:
            l.widest, l.smallest = float(l.widest), float(l.smallest)
        return cls(cams, lenses, p)

    @classmethod
    def defaults(cls, path: Path | None = None) -> "Gear":
        return cls([Camera(**asdict(c)) for c in DEFAULT_CAMERAS],
                   [Lens(**asdict(l)) for l in DEFAULT_LENSES], path)

    def save(self) -> None:
        for item in self.cameras + self.lenses:
            item.validate()
        p = self.path or default_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "_help": "Cameras: shutter speeds like 1/1000 or 1s. Lenses: f-numbers like 1.7 and 22.",
            "cameras": [asdict(c) for c in self.cameras],
            "lenses": [asdict(l) for l in self.lenses],
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)

    # ------------------------------------------------------------------ lookups

    def camera(self, name: str) -> Camera | None:
        key = (name or "").strip().lower()
        return next((c for c in self.cameras if c.name.strip().lower() == key), None) if key else None

    def lens(self, name: str) -> Lens | None:
        key = (name or "").strip().lower()
        return next((l for l in self.lenses if l.name.strip().lower() == key), None) if key else None

    def camera_names(self) -> list[str]:
        return [c.name for c in self.cameras]

    def lens_names(self) -> list[str]:
        return [l.name for l in self.lenses]


# --------------------------------------------------------------------------- limits

def shutter_choices(camera: Camera | None) -> list[float]:
    """Full-stop dial speeds the camera can actually set, in seconds."""
    if camera is None:
        return [s for s in FULL_SHUTTERS if 1 / 4000 <= s <= 1]
    fast, slow = _seconds(camera.fastest, "fastest"), _seconds(camera.slowest, "slowest")
    return [s for s in FULL_SHUTTERS if fast * 0.97 <= s <= slow * 1.03]


def aperture_choices(lens: Lens | None) -> list[float]:
    """Full stops the lens can set, plus its own maximum aperture (e.g. f/1.7)."""
    if lens is None:
        return [a for a in FULL_APERTURES if 1.4 <= a <= 22]
    stops = [a for a in FULL_APERTURES if lens.widest - 1e-6 <= a <= lens.smallest + 1e-6]
    if not any(abs(a - lens.widest) < 1e-6 for a in stops):
        stops.insert(0, lens.widest)
    return sorted(stops)


def check_exposure(camera: Camera | None, lens: Lens | None,
                   aperture: float | None, shutter: str | None) -> str:
    """A warning if the values can't be set on this gear, else ''."""
    problems = []
    if lens is not None and aperture is not None:
        if aperture < lens.widest - 0.05:
            problems.append(f"{format_aperture(aperture)} is wider than {lens.name} opens "
                            f"({format_aperture(lens.widest)})")
        elif aperture > lens.smallest + 0.05:
            problems.append(f"{format_aperture(aperture)} is past {lens.name}'s smallest stop "
                            f"({format_aperture(lens.smallest)})")
    if camera is not None and shutter is not None:
        if shutter == "B" and not camera.bulb:
            problems.append(f"{camera.name} has no Bulb setting")
        secs = shutter_seconds(shutter) if shutter not in ("B", "T", "A") else None
        if secs is not None:
            fast, slow = _seconds(camera.fastest, "fastest"), _seconds(camera.slowest, "slowest")
            if secs < fast * 0.97:
                problems.append(f"{format_shutter(shutter)} is faster than {camera.name}'s "
                                f"{format_shutter(camera.fastest)}")
            elif secs > slow * 1.03 and not camera.bulb:
                problems.append(f"{format_shutter(shutter)} is slower than {camera.name}'s "
                                f"{format_shutter(camera.slowest)}")
    return "; ".join(problems)
