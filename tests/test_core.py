import json
from pathlib import Path

import pytest

from contact_sheet import frames, model, stops


# ------------------------------------------------------------------ aperture

@pytest.mark.parametrize("text, expected", [
    ("8", 8.0), ("f8", 8.0), ("f/8", 8.0), ("F 8", 8.0),
    ("5.6", 5.6), ("56", 5.6), ("28", 2.8), ("35", 3.5), ("18", 18.0),
    ("14", 14.0), ("1.4", 1.4), ("16", 16.0), ("22", 22.0), ("2", 2.0),
    ("", None), ("?", None), (None, None),
])
def test_parse_aperture(text, expected):
    assert stops.parse_aperture(text) == expected


@pytest.mark.parametrize("bad", ["abc", "f/", "1/125", "999"])
def test_parse_aperture_rejects(bad):
    with pytest.raises(stops.ParseError):
        stops.parse_aperture(bad)


@pytest.mark.parametrize("value, text", [
    (8.0, "f/8"), (5.6, "f/5.6"), (2.0, "f/2"), (16.0, "f/16"), (1.4, "f/1.4"), (None, ""),
])
def test_format_aperture(value, text):
    assert stops.format_aperture(value) == text


# ------------------------------------------------------------------ shutter

@pytest.mark.parametrize("text, expected", [
    ("125", "1/125"), ("1/125", "1/125"), ("2", "1/2"), ("1", "1s"),
    ("2s", "2s"), ('2"', "2s"), ("2''", "2s"), ("0.5s", "1/2"), ("1.5s", "1.5s"),
    ("b", "B"), ("bulb", "B"), ("T", "T"), ("A", "A"), ("auto", "A"),
    ("", None), ("?", None), ("1/4000", "1/4000"), ("30s", "30s"),
])
def test_parse_shutter(text, expected):
    assert stops.parse_shutter(text) == expected


@pytest.mark.parametrize("bad", ["abc", "0", "1/0", "f/8"])
def test_parse_shutter_rejects(bad):
    with pytest.raises(stops.ParseError):
        stops.parse_shutter(bad)


def test_shutter_seconds():
    assert stops.shutter_seconds("1/125") == pytest.approx(0.008)
    assert stops.shutter_seconds("2s") == 2
    assert stops.shutter_seconds("B") is None
    assert stops.shutter_seconds(None) is None


# ------------------------------------------------------------------ ISO / estimates

@pytest.mark.parametrize("box, rated, label", [
    (400, 800, "+1"), (400, 1600, "+2"), (400, 200, "-1"), (400, 400, ""),
    (100, 125, "+1/3"), (400, 640, "+2/3"), (None, 800, ""),
])
def test_push_pull(box, rated, label):
    assert stops.push_pull_label(box, rated) == label


def test_sunny_16():
    pairs = dict(stops.exposure_pairs(15, 400))
    assert pairs[16.0] == "1/500"      # sunny 16 at ISO 400 -> 1/400, nearest dial 1/500
    assert pairs[8.0] == "1/2000"
    pairs100 = dict(stops.exposure_pairs(15, 100))
    assert pairs100[16.0] == "1/125"


# ------------------------------------------------------------------ frames

@pytest.mark.parametrize("name, label", [
    ("jakechan106501-R1-072-34A.jpg", "34A"),
    ("jakechan106501-R1-072-00.jpg", "00"),
    ("jakechan106501-R1-072-0.jpg", "0"),
    ("roll_07.tif", "7"),
    ("IMG_0123.jpg", None),
    ("scan.jpg", None),
])
def test_frame_label(name, label):
    assert frames.frame_label_from_name(name) == label


def test_edge_number_sort():
    names = ["x-R1-001-2.jpg", "x-R1-002-10.jpg", "x-R1-003-1A.jpg",
             "x-R1-004-00.jpg", "x-R1-005-1.jpg", "x-R1-006-0.jpg"]
    ordered = [p.name for p in frames.sort_scans([Path(n) for n in names])]
    labels = [frames.frame_label_from_name(n) for n in ordered]
    assert labels == ["00", "0", "1", "1A", "2", "10"]


def test_list_scans_skips_own_output(tmp_path):
    for n in ["a-1.jpg", "a-2.tif", "a_contact_sheet.jpg", "notes.txt", model.ROLL_FILE]:
        (tmp_path / n).write_bytes(b"x")
    assert [p.name for p in frames.list_scans(tmp_path)] == ["a-1.jpg", "a-2.tif"]


# ------------------------------------------------------------------ model

def test_film_line():
    r = model.Roll(film="Kodak Portra 400", box_iso=400, rated_iso=800)
    assert r.film_line() == "Kodak Portra 400 @ ISO 800 (+1)"
    r.rated_iso = None
    assert r.film_line() == "Kodak Portra 400, ISO 400"


def test_caption_shows_lens_override_only():
    f = model.Frame("a.jpg", aperture=8.0, shutter="1/125", lens="50mm f/1.8")
    assert f.caption(roll_lens="50mm f/1.8") == "f/8  1/125"
    assert f.caption(roll_lens="35mm f/2") == "f/8  1/125  50mm f/1.8"
    assert model.Frame("b.jpg").caption() == ""


def test_roundtrip_and_reconcile(tmp_path):
    for n in ["s-R1-1-1.jpg", "s-R1-2-2.jpg", "s-R1-3-3.jpg"]:
        (tmp_path / n).write_bytes(b"x")
    roll = model.load_roll(tmp_path)
    assert [f.label for f in roll.frames] == ["1", "2", "3"]

    roll.film = "Kodak Gold 200"
    roll.box_iso = 200
    roll.frames[1].aperture = 8.0
    roll.frames[1].shutter = "1/250"
    model.save_roll(roll, tmp_path)

    # Remove one scan, add one.
    (tmp_path / "s-R1-1-1.jpg").unlink()
    (tmp_path / "s-R1-4-4.jpg").write_bytes(b"x")

    again = model.load_roll(tmp_path)
    assert again.film == "Kodak Gold 200"
    assert [f.label for f in again.frames] == ["2", "3", "4"]
    assert again.frames[0].aperture == 8.0
    assert again.frames[0].shutter == "1/250"

    saved = json.loads((tmp_path / model.ROLL_FILE).read_text())
    assert saved["schema"] == model.SCHEMA_VERSION


def test_unlabelled_files_get_sequential_labels(tmp_path):
    for n in ["IMG_0001.jpg", "IMG_0002.jpg"]:
        (tmp_path / n).write_bytes(b"x")
    roll = model.load_roll(tmp_path)
    assert [f.label for f in roll.frames] == ["1", "2"]


def test_from_dict_ignores_unknown_keys():
    r = model.Roll.from_dict({"film": "X", "future_field": 1,
                              "frames": [{"filename": "a.jpg", "later": True}]})
    assert r.film == "X" and r.frames[0].filename == "a.jpg"
