import json

import pytest

from contact_sheet import gear, stops
from contact_sheet.gear import Camera, Gear, Lens
from contact_sheet.stops import ParseError


# ------------------------------------------------------------------ file handling

def test_first_load_writes_pentax_mx_defaults(tmp_path):
    p = tmp_path / "gear.json"
    g = Gear.load(p)
    assert p.exists()
    assert g.camera_names() == ["Pentax MX"]
    assert g.lens_names() == ["SMC Pentax 50mm f/1.4", "Pentax 28mm f/2.8"]
    assert g.lens("SMC Pentax 50mm f/1.4").widest == 1.4
    assert g.lens("Pentax 28mm f/2.8").widest == 2.8
    data = json.loads(p.read_text())
    assert data["cameras"][0]["fastest"] == "1/1000"
    assert data["cameras"][0]["slowest"] == "1s"


def test_roundtrip_and_case_insensitive_lookup(tmp_path):
    p = tmp_path / "gear.json"
    g = Gear.load(p)
    g.cameras.append(Camera("Nikon FM2", fastest="1/4000", slowest="1s"))
    g.lenses.append(Lens("Nikkor 50mm f/1.8", widest=1.8, smallest=22))
    g.save()
    again = Gear.load(p)
    assert again.camera("nikon fm2").fastest == "1/4000"
    assert again.lens("NIKKOR 50MM F/1.8").widest == 1.8
    assert again.camera("") is None and again.lens("unknown") is None


def test_hand_edited_file_with_extra_keys_loads(tmp_path):
    p = tmp_path / "gear.json"
    p.write_text(json.dumps({"cameras": [{"name": "Olympus OM-1", "fastest": "1/1000",
                                          "slowest": "1s", "mount": "OM"}],
                             "lenses": [{"name": "Zuiko 50/1.8", "widest": "1.8", "smallest": 16}]}))
    g = Gear.load(p)
    assert g.camera("Olympus OM-1") is not None
    assert g.lens("Zuiko 50/1.8").widest == 1.8


def test_broken_file_is_not_overwritten(tmp_path):
    p = tmp_path / "gear.json"
    p.write_text("{ oops")
    g = Gear.load(p)
    assert g.load_error and g.camera_names() == ["Pentax MX"]
    assert p.read_text() == "{ oops"


def test_validation():
    with pytest.raises(ParseError):
        Camera("Bad", fastest="1s", slowest="1/1000").validate()
    with pytest.raises(ParseError):
        Lens("Bad", widest=22, smallest=2).validate()
    with pytest.raises(ParseError):
        Camera("", fastest="1/1000").validate()


# ------------------------------------------------------------------ limits

def test_pentax_mx_dial():
    mx = gear.DEFAULT_CAMERAS[0]
    speeds = [stops.seconds_to_shutter(s) for s in gear.shutter_choices(mx)]
    assert speeds == ["1/1000", "1/500", "1/250", "1/125", "1/60", "1/30", "1/15",
                      "1/8", "1/4", "1/2", "1s"]


def test_lens_stops_include_odd_maximum():
    assert gear.aperture_choices(Lens("50/1.7", 1.7, 22)) == [1.7, 2, 2.8, 4, 5.6, 8, 11, 16, 22]
    assert gear.aperture_choices(Lens("28/2.8", 2.8, 22))[0] == 2.8


def test_check_exposure_messages():
    mx, lens = gear.DEFAULT_CAMERAS[0], Lens("SMC Pentax-M 50mm f/1.7", 1.7, 22)
    assert gear.check_exposure(mx, lens, 8.0, "1/125") == ""
    assert "faster than Pentax MX" in gear.check_exposure(mx, lens, 8.0, "1/2000")
    assert "wider than" in gear.check_exposure(mx, lens, 1.4, "1/125")
    assert "smallest stop" in gear.check_exposure(mx, lens, 32.0, "1/125")
    assert gear.check_exposure(mx, lens, 8.0, "B") == ""
    assert gear.check_exposure(None, None, 1.0, "1/8000") == ""


# ------------------------------------------------------------------ estimates with limits

def test_sunny_16_reference_values():
    # Sunny 16: f/16 at 1/ISO, rounded to the nearest dial speed.
    assert dict(stops.exposure_pairs(15, 100))[16.0] == "1/125"
    assert dict(stops.exposure_pairs(15, 200))[16.0] == "1/250"
    assert dict(stops.exposure_pairs(15, 400))[16.0] == "1/500"
    assert dict(stops.exposure_pairs(15, 800))[16.0] == "1/1000"
    # Overcast (EV 13, the sunny-16 "f/8" row) at ISO 400: f/8 at 1/400, nearest dial 1/500
    assert dict(stops.exposure_pairs(13, 400))[8.0] == "1/500"
    # Open shade (EV 12) at ISO 100: f/4 at 1/250
    assert dict(stops.exposure_pairs(12, 100))[4.0] == "1/250"


def test_estimates_never_exceed_the_camera():
    mx = gear.DEFAULT_CAMERAS[0]
    lens = Lens("SMC Pentax-M 50mm f/1.7", 1.7, 22)
    pairs = stops.exposure_pairs(15, 800, gear.aperture_choices(lens), gear.shutter_choices(mx))
    assert pairs == [(16.0, "1/1000"), (22.0, "1/500")]
    # Without limits the same light offers 1/2000 and 1/4000.
    assert any(sh in ("1/2000", "1/4000") for _, sh in stops.exposure_pairs(15, 800))


def test_out_of_range_notes():
    mx = gear.DEFAULT_CAMERAS[0]
    lens = Lens("50/1.7", 1.7, 22)
    aps, shs = gear.aperture_choices(lens), gear.shutter_choices(mx)
    assert stops.exposure_pairs(15, 3200, aps, shs) == []
    assert stops.out_of_range_note(15, 3200, aps, shs).startswith("Too bright")
    assert "use B" in stops.out_of_range_note(0, 100, aps, shs)
