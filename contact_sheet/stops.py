"""Parsing, formatting and estimating apertures and shutter speeds.

Typing conventions (meant to be fast on a keyboard):

Aperture
    "8", "f8", "f/8"  -> 8.0
    "28", "56", "35"  -> 2.8, 5.6, 3.5 (a decimal is inserted when the
                         number as typed is not a real f-number)
    "", "?"           -> None (unknown)

Shutter
    "125", "1/125"    -> "1/125"   (bare numbers follow the camera dial:
                                    "2" means 1/2, "1" means 1 second)
    "2s", '2"', "2''" -> "2s"      (seconds)
    "0.5s"            -> "1/2"
    "B", "T", "A"     -> bulb, time, auto (aperture priority / program)
    "", "?"           -> None (unknown)
"""

from __future__ import annotations

import math
import re

FULL_APERTURES = [1.0, 1.4, 2.0, 2.8, 4.0, 5.6, 8.0, 11.0, 16.0, 22.0, 32.0, 45.0, 64.0]
THIRD_APERTURES = [
    1.0, 1.1, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.5, 2.8, 3.2, 3.5, 4.0, 4.5, 5.0,
    5.6, 6.3, 7.1, 8.0, 9.0, 10.0, 11.0, 13.0, 14.0, 16.0, 18.0, 20.0, 22.0,
    25.0, 29.0, 32.0, 36.0, 40.0, 45.0, 64.0,
]
HALF_APERTURES = [1.2, 1.7, 2.4, 3.3, 4.8, 6.7, 9.5, 13.0, 19.0, 27.0]
# Common odd maximum apertures on real lenses.
ODD_APERTURES = [0.95, 1.5, 1.7, 1.9, 2.4, 3.3, 3.8, 4.8, 6.7]
KNOWN_APERTURES = sorted(set(THIRD_APERTURES + HALF_APERTURES + ODD_APERTURES))

# Full-stop shutter speeds as they appear on 35mm camera dials, in seconds.
FULL_SHUTTERS = [
    1 / 8000, 1 / 4000, 1 / 2000, 1 / 1000, 1 / 500, 1 / 250, 1 / 125, 1 / 60,
    1 / 30, 1 / 15, 1 / 8, 1 / 4, 1 / 2, 1, 2, 4, 8, 15, 30,
]

SPECIAL_SHUTTERS = {"B": "B", "BULB": "B", "T": "T", "A": "A", "AUTO": "A", "P": "A"}

UNKNOWN_TOKENS = {"", "?", "-", "--", "x", "none", "unknown"}


class ParseError(ValueError):
    """Raised when typed text cannot be read as an aperture or shutter speed."""


# --------------------------------------------------------------------------- aperture

def parse_aperture(text: str | None) -> float | None:
    if text is None:
        return None
    s = text.strip().lower().replace(" ", "")
    if s in UNKNOWN_TOKENS:
        return None
    s = re.sub(r"^f/?", "", s)
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        raise ParseError(f"Not an aperture: {text!r}")
    value = float(s)
    if "." not in s and len(s) >= 2 and not _is_known_aperture(value):
        shifted = float(s[0] + "." + s[1:])
        if _is_known_aperture(shifted):
            value = shifted
    if not 0.5 <= value <= 128:
        raise ParseError(f"Aperture out of range: {text!r}")
    return value


def _is_known_aperture(value: float) -> bool:
    return any(abs(value - a) < 1e-6 for a in KNOWN_APERTURES)


def format_aperture(value: float | None) -> str:
    if value is None:
        return ""
    if abs(value - round(value)) < 1e-6 and value >= 10:
        return f"f/{int(round(value))}"
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"f/{text}"


# --------------------------------------------------------------------------- shutter

def parse_shutter(text: str | None) -> str | None:
    """Return a canonical shutter string ("1/125", "2s", "B", "T", "A") or None."""
    if text is None:
        return None
    s = text.strip().lower().replace(" ", "")
    if s in UNKNOWN_TOKENS:
        return None
    if s.upper() in SPECIAL_SHUTTERS:
        return SPECIAL_SHUTTERS[s.upper()]

    m = re.fullmatch(r"(\d+(?:\.\d+)?)(s|sec|\"|''|”|″)", s)
    if m:
        return seconds_to_shutter(float(m.group(1)))

    m = re.fullmatch(r"1/(\d+(?:\.\d+)?)", s)
    if m:
        denom = float(m.group(1))
        if denom <= 0:
            raise ParseError(f"Not a shutter speed: {text!r}")
        return seconds_to_shutter(1 / denom)

    m = re.fullmatch(r"\d+", s)
    if m:
        n = int(s)
        if n == 0:
            raise ParseError(f"Not a shutter speed: {text!r}")
        return seconds_to_shutter(1 / n)

    m = re.fullmatch(r"\d*\.\d+", s)
    if m:
        return seconds_to_shutter(float(s))

    raise ParseError(f"Not a shutter speed: {text!r}")


def seconds_to_shutter(seconds: float) -> str:
    if seconds <= 0:
        raise ParseError("Shutter time must be positive")
    if seconds >= 1:
        if abs(seconds - round(seconds)) < 1e-6:
            return f"{int(round(seconds))}s"
        return f"{seconds:.1f}".rstrip("0").rstrip(".") + "s"
    denom = 1 / seconds
    if abs(denom - round(denom)) < 0.05:
        return f"1/{int(round(denom))}"
    # e.g. 0.3s -> keep as decimal seconds
    return f"{seconds:.2f}".rstrip("0").rstrip(".") + "s"


def shutter_seconds(shutter: str | None) -> float | None:
    """Exposure time in seconds, or None for unknown / B / T / A."""
    if shutter is None or shutter in ("B", "T", "A"):
        return None
    if shutter.endswith("s"):
        return float(shutter[:-1])
    if shutter.startswith("1/"):
        return 1 / float(shutter[2:])
    raise ParseError(f"Not a canonical shutter value: {shutter!r}")


def format_shutter(shutter: str | None) -> str:
    if shutter is None:
        return ""
    return {"B": "Bulb", "T": "Time", "A": "Auto"}.get(shutter, shutter)


# --------------------------------------------------------------------------- ISO

def push_pull_label(box_iso: int | None, rated_iso: int | None) -> str:
    """'+1', '-2/3', '' etc. for a film rated away from box speed."""
    if not box_iso or not rated_iso or box_iso == rated_iso:
        return ""
    stops = math.log2(rated_iso / box_iso)
    thirds = round(stops * 3)
    if thirds == 0:
        return ""
    sign = "+" if thirds > 0 else "-"
    whole, rem = divmod(abs(thirds), 3)
    if rem == 0:
        body = f"{whole}"
    elif whole == 0:
        body = f"{rem}/3"
    else:
        body = f"{whole} {rem}/3"
    return f"{sign}{body}"


# --------------------------------------------------------------------------- estimates

# Light conditions as EV at ISO 100, from the standard exposure-value tables.
# "Sun" is the sunny 16 rule: f/16 at 1/ISO.
CONDITIONS: list[tuple[str, float]] = [
    ("Snow / sand in sun", 16),
    ("Sun, hard shadows (sunny 16)", 15),
    ("Hazy sun, soft shadows", 14),
    ("Cloudy bright, no shadows", 13),
    ("Heavy overcast / open shade", 12),
    ("Sunset, lit by low sun", 12),
    ("Just after sunset", 10),
    ("Bright interior / office", 8),
    ("Bright city street at night", 7),
    ("Home interior", 6),
]

DEFAULT_HINT_APERTURES = FULL_APERTURES[1:10]                     # f/1.4 to f/22
DEFAULT_HINT_SHUTTERS = [s for s in FULL_SHUTTERS if 1 / 4000 <= s <= 1]


def ev_at_iso(ev100: float, iso: int) -> float:
    if not iso or iso <= 0:
        raise ValueError("ISO required for exposure estimates")
    return ev100 + math.log2(iso / 100)


def exposure_pairs(ev100: float, iso: int, apertures: list[float] | None = None,
                   shutters: list[float] | None = None) -> list[tuple[float, str]]:
    """Aperture / shutter pairs, restricted to the given settings, that give ev100 at this ISO.

    A pair is kept when the nearest available shutter speed is within half a stop of
    the exact time, so every suggestion is something the camera can be set to.
    """
    ev = ev_at_iso(ev100, iso)
    shutters = sorted(shutters or DEFAULT_HINT_SHUTTERS)
    pairs = []
    for n in apertures or DEFAULT_HINT_APERTURES:
        t = n * n / (2 ** ev)
        nearest = min(shutters, key=lambda s: abs(math.log2(s / t)))
        if abs(math.log2(nearest / t)) <= 0.5 + 1e-9:
            pairs.append((n, seconds_to_shutter(nearest)))
    return pairs


def out_of_range_note(ev100: float, iso: int, apertures: list[float] | None = None,
                      shutters: list[float] | None = None) -> str:
    """Why exposure_pairs came back empty: too bright or too dark for this gear."""
    ev = ev_at_iso(ev100, iso)
    apertures = apertures or DEFAULT_HINT_APERTURES
    shutters = sorted(shutters or DEFAULT_HINT_SHUTTERS)
    smallest, widest = max(apertures), min(apertures)
    fastest, slowest = shutters[0], shutters[-1]
    t_small = smallest ** 2 / 2 ** ev
    if t_small < fastest:
        over = math.log2(fastest / t_small)
        return (f"Too bright: even {format_aperture(smallest)} at {seconds_to_shutter(fastest)} "
                f"is about {over:.0f} stop{'s' if round(over) != 1 else ''} over.")
    t_wide = widest ** 2 / 2 ** ev
    if t_wide > slowest:
        needed = seconds_to_shutter(round(t_wide) if t_wide >= 2 else t_wide)
        return f"Too dark for the dial: {format_aperture(widest)} needs about {needed} (use B)."
    return ""
