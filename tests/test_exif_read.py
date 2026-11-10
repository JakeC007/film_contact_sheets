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


def test_fill_digital_roll(tmp_path):
    _jpeg(tmp_path / "IMG_0001.JPG", taken="2026:11:08 04:43:18")
    _jpeg(tmp_path / "IMG_0002.JPG", fnumber=(28, 10), exposure=(1, 250), iso=3200,
          taken="2026:11:09 21:10:00")
    roll = model.load_roll(tmp_path)
    rep = exif_read.fill_from_exif(roll, tmp_path)
    assert rep.files_with_exif == 2
    assert roll.camera == "Canon EOS 100D"
    assert roll.lens == "24mm F1.4 DG HSM | Art 015"
    assert roll.date == "8-9 Nov 2026"
    assert roll.box_iso is None and "ISO varies (3200-6400)" in rep.summary()
    assert [(f.aperture, f.shutter) for f in roll.frames] == [(1.4, "1/13"), (2.8, "1/250")]
    assert all(f.exif_read for f in roll.frames)
    assert all(f.lens == "" for f in roll.frames)   # same as roll lens, no override


def test_typed_values_win_and_cleared_values_stay_cleared(tmp_path):
    _jpeg(tmp_path / "IMG_0001.JPG")
    roll = model.load_roll(tmp_path)
    roll.camera = "My typed camera"
    roll.frames[0].aperture = 8.0
    exif_read.fill_from_exif(roll, tmp_path)
    assert roll.camera == "My typed camera"
    assert roll.frames[0].aperture == 8.0 and roll.frames[0].shutter == "1/13"

    # You clear the shutter on purpose; reopening the folder must not bring it back.
    roll.frames[0].shutter = None
    model.save_roll(roll, tmp_path)
    again = model.load_roll(tmp_path)
    exif_read.fill_from_exif(again, tmp_path)
    assert again.frames[0].shutter is None
    # ...unless you ask for it explicitly.
    exif_read.fill_from_exif(again, tmp_path, frames=again.frames)
    assert again.frames[0].shutter == "1/13"


def test_uniform_iso_and_scanner_detection(tmp_path):
    _jpeg(tmp_path / "a-1.jpg", iso=400)
    _jpeg(tmp_path / "a-2.jpg", iso=400)
    _jpeg(tmp_path / "s-3.jpg", make="NORITSU KOKI", model_name="EZ Controller", fnumber=None,
          exposure=None, iso=None, lens=None, taken=None)
    roll = model.load_roll(tmp_path)
    exif_read.fill_from_exif(roll, tmp_path)
    assert roll.box_iso == 400
    assert roll.scanner == "NORITSU KOKI EZ Controller"
    assert roll.camera == "Canon EOS 100D"


def test_mixed_lenses_get_overrides(tmp_path):
    _jpeg(tmp_path / "a-1.jpg", lens="50mm")
    _jpeg(tmp_path / "a-2.jpg", lens="50mm")
    _jpeg(tmp_path / "a-3.jpg", lens="28mm")
    roll = model.load_roll(tmp_path)
    exif_read.fill_from_exif(roll, tmp_path)
    assert roll.lens == "50mm"
    assert [f.lens for f in roll.frames] == ["", "", "28mm"]


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
