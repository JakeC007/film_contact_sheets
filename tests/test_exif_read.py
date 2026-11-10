from datetime import datetime

import numpy as np
import piexif
import pytest
import tifffile
from PIL import Image

from contact_sheet import exif_read, model


def _jpeg(path, *, make="Canon", model_name="Canon EOS 100D", fnumber=(14, 10),
          exposure=(1, 13), iso=6400, lens="24mm F1.4 DG HSM | Art 015",
          taken="2026:11:08 04:43:18", software=None):
    zeroth = {}
    if make:
        zeroth[piexif.ImageIFD.Make] = make.encode()
    if model_name:
        zeroth[piexif.ImageIFD.Model] = model_name.encode()
    if software:
        zeroth[piexif.ImageIFD.Software] = software.encode()
    ex = {}
    if fnumber:
        ex[piexif.ExifIFD.FNumber] = fnumber
    if exposure:
        ex[piexif.ExifIFD.ExposureTime] = exposure
    if iso:
        ex[piexif.ExifIFD.ISOSpeedRatings] = iso
    if lens:
        ex[piexif.ExifIFD.LensModel] = lens.encode()
    if taken:
        ex[piexif.ExifIFD.DateTimeOriginal] = taken.encode()
    Image.new("RGB", (60, 40)).save(path, exif=piexif.dump({"0th": zeroth, "Exif": ex}))


def test_reads_digital_camera_exif(tmp_path):
    p = tmp_path / "IMG_7826.JPG"
    _jpeg(p)
    ex = exif_read.read_file_exif(p)
    assert ex.device == "Canon EOS 100D"
    assert ex.fnumber == pytest.approx(1.4) and ex.exposure == pytest.approx(1 / 13)
    assert ex.iso == 6400 and ex.lens.startswith("24mm F1.4")
    assert ex.taken == datetime(2026, 11, 8, 4, 43, 18)
    assert not ex.is_scanner


def test_lab_scan_without_exif_is_empty(tmp_path):
    p = tmp_path / "scan-1.jpg"
    Image.new("RGB", (60, 40)).save(p)
    assert exif_read.read_file_exif(p).empty


@pytest.mark.parametrize("make, model_name, expected", [
    ("Canon", "Canon EOS 100D", "Canon EOS 100D"),
    ("NIKON CORPORATION", "NIKON D750", "NIKON D750"),
    ("FUJIFILM", "X-T3", "FUJIFILM X-T3"),
    ("", "Pentax MX", "Pentax MX"),
])
def test_device_name(make, model_name, expected):
    assert exif_read.FileExif(make=make, model=model_name).device == expected


def test_camera_exif_is_not_used_until_the_user_decides(tmp_path):
    _jpeg(tmp_path / "IMG_0001.JPG")
    roll = model.load_roll(tmp_path)
    found = exif_read.survey(roll, tmp_path)
    assert exif_read.needs_decision(roll, found)
    assert exif_read.camera_summary(found) == "Canon EOS 100D"
    exif_read.fill_from_exif(roll, tmp_path, found=found)
    fr = roll.frames[0]
    assert roll.camera == "" and fr.aperture is None and fr.shutter is None
    assert fr.exif_read is False          # so the question comes up again next time


def test_film_scanned_with_a_camera(tmp_path):
    # e.g. negatives shot on a copy stand with a DSLR: its exposure is the scan, not the photo
    _jpeg(tmp_path / "scan-1.jpg", make="SONY", model_name="ILCE-7M3", fnumber=(8, 1),
          exposure=(1, 125), lens="FE 90mm F2.8 Macro G OSS")
    roll = model.load_roll(tmp_path)
    roll.exif_source = "scan"
    exif_read.fill_from_exif(roll, tmp_path)
    assert roll.scanner == "SONY ILCE-7M3"
    assert roll.camera == "" and roll.lens == "" and roll.medium == model.FILM
    assert roll.frames[0].aperture is None and roll.frames[0].exif_read


def test_ignore_leaves_everything(tmp_path):
    _jpeg(tmp_path / "IMG_0001.JPG")
    roll = model.load_roll(tmp_path)
    roll.exif_source = "ignore"
    exif_read.fill_from_exif(roll, tmp_path)
    assert roll.camera == "" and roll.scanner == "" and roll.frames[0].aperture is None
    assert not exif_read.needs_decision(roll, exif_read.survey(roll, tmp_path, roll.frames))


def test_fill_digital_roll(tmp_path):
    _jpeg(tmp_path / "IMG_0002.JPG", fnumber=(28, 10), exposure=(1, 250), iso=3200,
          taken="2026:11:09 21:10:00")
    _jpeg(tmp_path / "IMG_0010.JPG", taken="2026:11:08 04:43:18")
    roll = model.load_roll(tmp_path)
    roll.exif_source = model.DIGITAL
    rep = exif_read.fill_from_exif(roll, tmp_path)
    exif_read.arrange_as_digital(roll)
    assert roll.medium == model.DIGITAL
    assert roll.camera == "Canon EOS 100D"
    assert roll.lens == "24mm F1.4 DG HSM | Art 015"
    assert roll.date == "8-9 Nov 2026"
    assert roll.box_iso is None                      # ISO is per frame on digital
    assert rep.files_with_exif == 2
    # ordered by capture time, labelled by file number
    assert [f.label for f in roll.frames] == ["10", "2"]
    assert [(f.aperture, f.shutter, f.iso) for f in roll.frames] == [
        (1.4, "1/13", 6400), (2.8, "1/250", 3200)]
    assert roll.frames[0].taken == "2026-11-08T04:43:18"
    assert roll.iso_range() == "3200-6400"
    assert roll.film_line() == "Digital, ISO 3200-6400"
    assert roll.frames[0].caption(roll.lens) == "f/1.4  1/13  ISO 6400"


def test_typed_values_win_and_cleared_values_stay_cleared(tmp_path):
    _jpeg(tmp_path / "IMG_0001.JPG")
    roll = model.load_roll(tmp_path)
    roll.exif_source = model.DIGITAL
    roll.camera = "My typed camera"
    roll.frames[0].aperture = 8.0
    exif_read.fill_from_exif(roll, tmp_path)
    assert roll.camera == "My typed camera"
    assert roll.frames[0].aperture == 8.0 and roll.frames[0].shutter == "1/13"

    # You clear the shutter on purpose; reopening the folder must not bring it back.
    roll.frames[0].shutter = None
    model.save_roll(roll, tmp_path)
    again = model.load_roll(tmp_path)
    assert again.exif_source == model.DIGITAL     # the decision is saved with the roll
    exif_read.fill_from_exif(again, tmp_path)
    assert again.frames[0].shutter is None
    # ...unless you ask for it explicitly.
    exif_read.fill_from_exif(again, tmp_path, frames=again.frames)
    assert again.frames[0].shutter == "1/13"


def test_scanner_exif_fills_scanner_without_asking(tmp_path):
    _jpeg(tmp_path / "s-1.jpg", make="NORITSU KOKI", model_name="EZ Controller", fnumber=None,
          exposure=None, iso=None, lens=None, taken=None)
    roll = model.load_roll(tmp_path)
    found = exif_read.survey(roll, tmp_path)
    assert not exif_read.needs_decision(roll, found)
    exif_read.fill_from_exif(roll, tmp_path, found=found)
    assert roll.scanner == "NORITSU KOKI EZ Controller" and roll.camera == ""


def test_own_exif_refills_film_data_without_asking(tmp_path):
    # Scans this app tagged earlier ("Overwrite originals"), opened after the roll file was lost.
    _jpeg(tmp_path / "x-R1-01-1.jpg", make=None, model_name="Pentax MX", fnumber=(8, 1),
          exposure=(1, 250), iso=400, lens="SMC Pentax 50mm f/1.4", taken=None,
          software="film_contact_sheets 0.1.0")
    roll = model.load_roll(tmp_path)
    found = exif_read.survey(roll, tmp_path)
    assert not exif_read.needs_decision(roll, found)
    exif_read.fill_from_exif(roll, tmp_path, found=found)
    assert roll.medium == model.FILM and roll.camera == "Pentax MX"
    assert (roll.frames[0].aperture, roll.frames[0].shutter) == (8.0, "1/250")
    assert roll.frames[0].iso is None and roll.frames[0].label == "1"


def test_mixed_lenses_get_overrides(tmp_path):
    _jpeg(tmp_path / "a-1.jpg", lens="50mm")
    _jpeg(tmp_path / "a-2.jpg", lens="50mm")
    _jpeg(tmp_path / "a-3.jpg", lens="28mm", )
    roll = model.load_roll(tmp_path)
    roll.exif_source = model.DIGITAL
    exif_read.fill_from_exif(roll, tmp_path)
    assert roll.lens == "50mm"
    assert [f.lens for f in roll.frames] == ["", "", "28mm"]


def test_switching_back_to_film_restores_edge_numbers(tmp_path):
    for n in ("x-R1-001-2.jpg", "x-R1-002-1.jpg", "x-R1-003-00.jpg"):
        Image.new("RGB", (30, 20)).save(tmp_path / n)
    roll = model.load_roll(tmp_path)
    exif_read.arrange_as_digital(roll)
    assert [f.label for f in roll.frames] == ["2", "1", "0"]   # last number in each filename
    exif_read.arrange_as_film(roll)
    assert [f.label for f in roll.frames] == ["00", "1", "2"]


def test_16bit_tiff_exif_via_tifffile(tmp_path):
    p = tmp_path / "scan-1.tif"
    tifffile.imwrite(p, np.zeros((20, 30, 3), dtype=np.uint16), photometric="rgb",
                     extratags=[(271, "s", 0, "Nikon", True), (272, "s", 0, "LS-5000", True)])
    ex = exif_read.read_file_exif(p)
    assert ex.is_scanner and ex.device == "Nikon LS-5000"


@pytest.mark.parametrize("dates, text", [
    ([datetime(2026, 11, 8, 4)], "8 Nov 2026"),
    ([datetime(2026, 10, 3), datetime(2026, 10, 12)], "3-12 Oct 2026"),
    ([datetime(2026, 10, 28), datetime(2026, 11, 3)], "28 Oct - 3 Nov 2026"),
    ([datetime(2025, 12, 30), datetime(2026, 1, 2)], "Dec 2025 - Jan 2026"),
])
def test_date_range(dates, text):
    assert exif_read.format_date_range(dates) == text


def test_corrupt_file_is_just_empty(tmp_path):
    p = tmp_path / "x-1.jpg"
    p.write_bytes(b"not an image")
    assert exif_read.read_file_exif(p).empty


def test_unsupported_files_note(tmp_path):
    from contact_sheet import frames
    for n in ("IMG_1.CR3", "IMG_1.JPG", "IMG_2.CR3", "IMG_3.NEF", "phone.HEIC"):
        (tmp_path / n).write_bytes(b"x")
    found = frames.unsupported_files(tmp_path)
    assert [p.name for p in found["raw"]] == ["IMG_2.CR3", "IMG_3.NEF"]   # IMG_1 has a JPEG
    note = frames.unsupported_note(found)
    assert note.startswith("Skipped 2 RAW file(s) (CR3, NEF) without a JPEG and 1 HEIC file(s)")
    assert frames.unsupported_note({"raw": [], "other": []}) == ""


@pytest.mark.parametrize("name, label", [
    ("IMG_7826.JPG", "7826"), ("DSC00012.jpg", "12"), ("_MG_0001.jpg", "1"), ("scan.jpg", "scan"),
])
def test_file_number_label(name, label):
    from contact_sheet.frames import file_number_label
    assert file_number_label(name) == label


def test_iso_entry():
    from contact_sheet import editing
    from contact_sheet.stops import ParseError
    r = model.Roll(medium=model.DIGITAL)
    r.frames = [model.Frame("a.jpg", iso=6400), model.Frame("b.jpg", iso=3200)]
    editing.apply_entry(r, [0], editing.Entry("1.4", "13", iso="ISO 800"))
    assert r.frames[0].iso == 800
    editing.apply_entry(r, [0, 1], editing.Entry("", "", iso=""))      # blank: unchanged
    assert [f.iso for f in r.frames] == [800, 3200]
    with pytest.raises(ParseError):
        editing.apply_entry(r, [0], editing.Entry("1.4", "13", iso="lots"))


def test_digital_overview_fields():
    from contact_sheet import render
    r = model.Roll(medium=model.DIGITAL, camera="Canon EOS 100D", lens="24mm", date="8 Nov 2026",
                   film="should not show", lab="nor this")
    r.frames = [model.Frame("a.jpg", iso=3200), model.Frame("b.jpg", iso=6400)]
    f = dict(render.overview_fields(r))
    assert f == {"Camera": "Canon EOS 100D", "Lens": "24mm", "ISO": "3200-6400",
                 "Date": "8 Nov 2026", "Frames": "2"}
