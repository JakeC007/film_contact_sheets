import json

import pytest

from contact_sheet import editing, library, model
from contact_sheet.editing import Entry
from contact_sheet.stops import ParseError


def _roll(n=5, lens="50mm f/1.8"):
    r = model.Roll(lens=lens, box_iso=400)
    r.frames = [model.Frame(f"f-{i}.jpg", label=str(i)) for i in range(1, n + 1)]
    return r


def test_blank_on_new_frame_accepts_suggestion():
    r = _roll()
    editing.apply_entry(r, [0], Entry("8", "125", lens=""))
    editing.apply_entry(r, [1], Entry("", "", lens=""))
    assert (r.frames[1].aperture, r.frames[1].shutter) == (8.0, "1/125")


def test_partial_entry_takes_rest_from_suggestion():
    r = _roll()
    editing.apply_entry(r, [0], Entry("8", "125"))
    editing.apply_entry(r, [1], Entry("5.6", ""))
    assert (r.frames[1].aperture, r.frames[1].shutter) == (5.6, "1/125")


def test_question_mark_records_unknown_instead_of_suggestion():
    r = _roll()
    editing.apply_entry(r, [0], Entry("8", "125"))
    editing.apply_entry(r, [1], Entry("?", "250"))
    assert (r.frames[1].aperture, r.frames[1].shutter) == (None, "1/250")


def test_clearing_existing_frame_makes_unknown():
    r = _roll()
    editing.apply_entry(r, [0], Entry("8", "125"))
    editing.apply_entry(r, [1], Entry("4", "60"))
    editing.apply_entry(r, [1], Entry("", "60"))
    assert r.frames[1].aperture is None


def test_suggestion_skips_hidden_and_empty():
    r = _roll()
    editing.apply_entry(r, [0], Entry("8", "125"))
    editing.apply_entry(r, [1], Entry("2", "60"))
    r.frames[1].hidden = True
    s = editing.suggestion_for(r, 3)
    assert (s.aperture, s.shutter, s.source_label) == (8.0, "1/125", "1")


def test_multi_select_only_applies_typed_fields():
    r = _roll()
    editing.apply_entry(r, [0], Entry("8", "125"))
    editing.apply_entry(r, [1], Entry("4", "60"))
    editing.apply_entry(r, [0, 1, 2], Entry("11", "", lens="", note=""))
    assert [f.aperture for f in r.frames[:3]] == [11.0, 11.0, 11.0]
    assert [f.shutter for f in r.frames[:3]] == ["1/125", "1/60", None]


def test_multi_select_question_mark_clears():
    r = _roll()
    editing.apply_entry(r, [0, 1], Entry("8", "125"))
    editing.apply_entry(r, [0, 1], Entry("", "?"))
    assert [f.shutter for f in r.frames[:2]] == [None, None]
    assert [f.aperture for f in r.frames[:2]] == [8.0, 8.0]


def test_invalid_entry_changes_nothing():
    r = _roll()
    editing.apply_entry(r, [0], Entry("8", "125"))
    with pytest.raises(ParseError):
        editing.apply_entry(r, [0], Entry("4", "banana"))
    assert r.frames[0].aperture == 8.0


def test_lens_override_stored_only_when_different():
    r = _roll()
    editing.apply_entry(r, [0], Entry("8", "125", lens="50mm f/1.8"))
    assert r.frames[0].lens == ""
    editing.apply_entry(r, [1], Entry("8", "125", lens="28mm f/2.8"))
    assert r.frames[1].lens == "28mm f/2.8"
    # next new frame inherits the swapped lens
    editing.apply_entry(r, [2], Entry("", "", lens=""))
    assert r.frames[2].lens == "28mm f/2.8"


def test_duplicate_label_rejected():
    r = _roll()
    with pytest.raises(ParseError):
        editing.apply_entry(r, [0], Entry("8", "125", label="2"))
    editing.apply_entry(r, [0], Entry("8", "125", label="00"))
    assert r.frames[0].label == "00"


def test_recent_pairs_order_and_dedupe():
    r = _roll()
    editing.apply_entry(r, [0], Entry("8", "125"))
    hist = [(8.0, "1/125"), (16.0, "1/500"), (8.0, "1/125"), (2.8, "1/60")]
    assert editing.recent_pairs(r, hist) == [(2.8, "1/60"), (8.0, "1/125"), (16.0, "1/500")]


def test_next_index_skips_hidden():
    r = _roll()
    r.frames[2].hidden = True
    assert editing.next_index(r, 1, 1) == 3
    assert editing.next_index(r, 3, -1) == 1
    assert editing.next_index(r, 4, 1) == 4


def test_move_frame():
    r = _roll()
    assert editing.move_frame(r, 0, 1) == 1
    assert [f.label for f in r.frames[:2]] == ["2", "1"]
    assert editing.move_frame(r, 0, -1) == 0


# ------------------------------------------------------------------ library

@pytest.mark.parametrize("name, iso", [
    ("Kodak Portra 400", 400), ("Fujifilm Velvia 50", 50), ("CineStill 800T", 800),
    ("Ilford HP5 Plus 400", 400), ("Ilford Delta 3200", 3200), ("Lomo Purple", None),
])
def test_iso_from_name(name, iso):
    assert library.iso_from_film_name(name) == iso


def test_library_roundtrip_ignores_camera_and_lens(tmp_path):
    lib = library.Library(tmp_path / "lib.json")
    r = model.Roll(film="Kodak Gold 200", box_iso=200, camera="Nikon FM2", lens="50mm",
                   location="Scotland", scanner="Fujifilm")
    r.frames = [model.Frame("a.jpg", lens="28mm")]
    lib.remember_roll(r)
    lib.save()
    again = library.Library(tmp_path / "lib.json")
    assert again.values("film")[0] == "Kodak Gold 200"
    assert again.values("location") == ["Scotland"]
    assert again.box_iso_for("Kodak Gold 200") == 200
    saved = json.loads((tmp_path / "lib.json").read_text())
    assert "camera" not in saved and "lens" not in saved


def test_old_library_with_partial_camera_names_is_cleaned(tmp_path):
    # What an earlier version wrote: half-typed names saved by autosave.
    p = tmp_path / "lib.json"
    p.write_text(json.dumps({"film": ["Kodak Gold 200"], "camera": ["Pentax MX", "Pe", "P"],
                             "lens": ["50 mm"], "film_iso": {"Kodak Gold 200": 200}}))
    lib = library.Library(p)
    assert lib.values("camera") == [] and lib.values("lens") == []
    lib.save()
    saved = json.loads(p.read_text())
    assert "camera" not in saved and saved["film"] == ["Kodak Gold 200"]


def test_library_survives_corrupt_file(tmp_path):
    p = tmp_path / "lib.json"
    p.write_text("{not json")
    assert library.Library(p).values("location") == []
