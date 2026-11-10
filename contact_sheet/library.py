"""Remembered film stocks, scanners, places and labs across rolls.

Cameras and lenses are not remembered here: only what's saved in Gear shows in
those dropdowns, so a one-off typed into the roll never becomes a choice.

Stored in %APPDATA%\\film_contact_sheets\\library.json (or ~/.config elsewhere).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .model import Roll

KINDS = ("film", "scanner", "location", "lab")   # older files' "camera"/"lens" are dropped
MAX_ITEMS = 60
COMMON_ISOS = {25, 32, 50, 64, 80, 100, 125, 160, 200, 250, 320, 400, 500, 640, 800,
               1000, 1250, 1600, 3200, 6400}

STARTER_FILMS = [
    "Kodak Portra 160", "Kodak Portra 400", "Kodak Portra 800", "Kodak Ektar 100",
    "Kodak Gold 200", "Kodak UltraMax 400", "Kodak ColorPlus 200", "Kodak Ektachrome E100",
    "Kodak Tri-X 400", "Kodak T-Max 100", "Kodak T-Max 400",
    "Fujifilm 200", "Fujifilm 400", "Fujifilm Velvia 50", "Fujifilm Provia 100F",
    "Ilford HP5 Plus 400", "Ilford FP4 Plus 125", "Ilford Delta 100", "Ilford Delta 400",
    "Ilford Delta 3200", "Ilford XP2 Super 400", "Ilford Pan F Plus 50",
    "CineStill 800T", "CineStill 400D", "CineStill 50D", "Lomography Color 400",
]


def default_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "film_contact_sheets" / "library.json"


def iso_from_film_name(name: str) -> int | None:
    """'Kodak Portra 400' -> 400, 'Fujifilm Velvia 50' -> 50, 'CineStill 800T' -> 800."""
    for m in reversed(list(re.finditer(r"(?<!\d)(\d{2,4})(?!\d)", name or ""))):
        value = int(m.group(1))
        if value in COMMON_ISOS:
            return value
    return None


class Library:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_path()
        self.items: dict[str, list[str]] = {k: [] for k in KINDS}
        self.film_iso: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for k in KINDS:
            vals = data.get(k, [])
            if isinstance(vals, list):
                self.items[k] = [str(v) for v in vals if str(v).strip()][:MAX_ITEMS]
        if isinstance(data.get("film_iso"), dict):
            self.film_iso = {str(k): int(v) for k, v in data["film_iso"].items()
                             if str(v).isdigit()}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({**self.items, "film_iso": self.film_iso}, indent=2,
                                  ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def values(self, kind: str) -> list[str]:
        vals = list(self.items.get(kind, []))
        if kind == "film":
            vals += [f for f in STARTER_FILMS if f not in vals]
        return vals

    def remember(self, kind: str, value: str) -> None:
        value = (value or "").strip()
        if not value:
            return
        lst = [v for v in self.items[kind] if v.lower() != value.lower()]
        self.items[kind] = [value] + lst[: MAX_ITEMS - 1]

    def remember_roll(self, roll: Roll) -> None:
        """Call with a finished roll (on export, switching folder, closing), not on every
        keystroke autosave, or half-typed words end up in the dropdowns."""
        for kind in KINDS:
            self.remember(kind, getattr(roll, kind))
        if roll.film.strip() and roll.box_iso:
            self.film_iso[roll.film.strip()] = int(roll.box_iso)

    def box_iso_for(self, film: str) -> int | None:
        film = (film or "").strip()
        return self.film_iso.get(film) or iso_from_film_name(film)
