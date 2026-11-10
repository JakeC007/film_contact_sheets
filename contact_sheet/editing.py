"""Rules for entering exposures quickly, kept separate from the GUI so they can be tested.

Single frame:
  * A frame with no exposure yet is offered the values of the nearest earlier
    frame that has one (a "suggestion"). Leaving a field blank and pressing
    Enter accepts the suggestion; typing "?" records unknown.
  * A frame that already has values shows them; clearing a field makes it unknown.

Several frames selected:
  * Only fields you type in are applied; blank fields leave each frame as it was.
  * "?" sets unknown on all of them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Frame, Roll
from .stops import ParseError, parse_aperture, parse_shutter

UNKNOWN_MARK = "?"


@dataclass(frozen=True)
class Suggestion:
    aperture: float | None = None
    shutter: str | None = None
    lens: str = ""
    source_label: str = ""

    @property
    def empty(self) -> bool:
        return self.aperture is None and self.shutter is None


def suggestion_for(roll: Roll, index: int) -> Suggestion:
    """Values from the nearest earlier visible frame that has an exposure."""
    for f in reversed(roll.frames[:index]):
        if f.hidden or not f.has_exposure():
            continue
        return Suggestion(f.aperture, f.shutter, f.lens, f.label)
    return Suggestion()


@dataclass
class Entry:
    """Raw text from the editor fields. None means the field was not offered."""
    aperture: str = ""
    shutter: str = ""
    lens: str | None = None
    note: str | None = None
    label: str | None = None
    iso: str | None = None      # digital rolls only; None = field not shown


def parse_iso(text: str | None) -> int | None:
    t = (text or "").strip().lower().removeprefix("iso").strip()
    if t in ("", "?"):
        return None
    if not t.isdigit() or not 1 <= int(t) <= 409600:
        raise ParseError(f"Not an ISO: {text!r}")
    return int(t)


def apply_entry(roll: Roll, indices: list[int], entry: Entry) -> list[int]:
    """Validate then apply an entry. Raises ParseError before changing anything."""
    if not indices:
        return []
    multi = len(indices) > 1

    ap_text = entry.aperture.strip()
    sh_text = entry.shutter.strip()
    ap_value = parse_aperture(ap_text)   # validates; "?" and "" both give None
    sh_value = parse_shutter(sh_text)
    iso_text = (entry.iso or "").strip()
    iso_value = parse_iso(iso_text) if entry.iso is not None else None

    if entry.label is not None and not multi:
        label = entry.label.strip()
        clash = [f for i, f in enumerate(roll.frames) if i != indices[0] and f.label == label]
        if label and clash:
            raise ParseError(f"Frame {label} already exists")

    for i in indices:
        fr = roll.frames[i]
        was_empty = not fr.has_exposure()
        sug = suggestion_for(roll, i) if (was_empty and not multi) else Suggestion()

        if multi:
            if ap_text:
                fr.aperture = ap_value
            if sh_text:
                fr.shutter = sh_value
        else:
            fr.aperture = sug.aperture if (ap_text == "" and was_empty) else ap_value
            fr.shutter = sug.shutter if (sh_text == "" and was_empty) else sh_value

        if entry.lens is not None:
            lens = entry.lens.strip()
            if multi and not lens:
                pass
            elif not multi and not lens and was_empty:
                fr.lens = _normalise_lens(sug.lens, roll)
            else:
                fr.lens = _normalise_lens(lens, roll)

        if entry.iso is not None and (not multi or iso_text):
            fr.iso = iso_value

        if entry.note is not None and (not multi or entry.note.strip()):
            fr.note = entry.note.strip()

    if entry.label is not None and not multi and entry.label.strip():
        roll.frames[indices[0]].label = entry.label.strip()

    return list(indices)


def _normalise_lens(lens: str, roll: Roll) -> str:
    """Store an override only when it differs from the roll lens."""
    lens = (lens or "").strip()
    return "" if lens == roll.lens.strip() else lens


def set_exposure(roll: Roll, indices: list[int], aperture: float | None, shutter: str | None) -> None:
    """Apply an exact pair (used by the recent-combo buttons and hints)."""
    for i in indices:
        roll.frames[i].aperture = aperture
        roll.frames[i].shutter = shutter


def clear_exposure(roll: Roll, indices: list[int]) -> None:
    set_exposure(roll, indices, None, None)


def recent_pairs(roll: Roll, history: list[tuple[float | None, str | None]], limit: int = 6
                 ) -> list[tuple[float | None, str | None]]:
    """Most recently used distinct pairs: this session's history first, then the roll."""
    seen: list[tuple[float | None, str | None]] = []
    pool = list(reversed(history)) + [(f.aperture, f.shutter) for f in reversed(roll.frames)
                                      if f.has_exposure()]
    for pair in pool:
        if pair == (None, None) or pair in seen:
            continue
        seen.append(pair)
        if len(seen) >= limit:
            break
    return seen


def move_frame(roll: Roll, index: int, delta: int) -> int:
    """Move a frame earlier/later in the sheet order. Returns its new index."""
    new = max(0, min(len(roll.frames) - 1, index + delta))
    if new != index:
        fr = roll.frames.pop(index)
        roll.frames.insert(new, fr)
    return new


def next_index(roll: Roll, after: int, step: int = 1) -> int:
    """Next visible frame in the given direction, or the same index at the ends."""
    i = after + step
    while 0 <= i < len(roll.frames):
        if not roll.frames[i].hidden:
            return i
        i += step
    return after


def frame_summary(fr: Frame, roll_lens: str) -> str:
    return fr.caption(roll_lens) or "?"
