import os

import numpy as np
import piexif
import pytest
import tifffile
from PIL import Image

from contact_sheet import exif_write, model


def _roll(tmp_path, names):
    for n in names:
        p = tmp_path / n
        if p.suffix.lower() in (".tif", ".tiff"):
            tifffile.imwrite(p, np.full((40, 60, 3), 30000, dtype=np.uint16), photometric="rgb")
        else:
            Image.new("RGB", (60, 40), (200, 100, 50)).save(p, quality=90)
    r = model.load_roll(tmp_path)
    r.film, r.box_iso, r.rated_iso = "Kodak Portra 400", 400, 800
    r.camera, r.lens, r.scanner = "Nikon FM2", "50mm f/1.8", "Noritsu HS-1800"
    return r


def _find_exiftool():
    # Set EXIFTOOL to point at a specific binary; otherwise use PATH / app dir.
    return os.environ.get("EXIFTOOL") or exif_write.find_exiftool()


def test_tags_for_frame():
    r = model.Roll(film="Kodak Gold 200", box_iso=200, lens="50mm", scanner="Frontier")
    fr = model.Frame("a.jpg", aperture=8.0, shutter="1/125", lens="28mm", note="tram")
    t = exif_write.tags_for(r, fr)
    assert t.fnumber == 8.0 and t.exposure_time == pytest.approx(1 / 125)
    assert t.lens == "28mm" and t.iso == 200
    assert t.description == "Kodak Gold 200, ISO 200. tram. Scanned on Frontier"
    assert exif_write.tags_for(r, model.Frame("b.jpg", shutter="A")).auto_exposure


def test_exposure_rational():
    assert exif_write._exposure_rational(1 / 125) == (1, 125)
    assert exif_write._exposure_rational(2.0) == (2, 1)
    assert exif_write._exposure_rational(0.3) == (3, 10)


def test_jpeg_copy_mode_is_lossless_and_leaves_original(tmp_path):
    r = _roll(tmp_path, ["s-1.jpg", "s-2.jpg"])
    r.frames[0].aperture, r.frames[0].shutter = 5.6, "1/250"
    original = (tmp_path / "s-1.jpg").read_bytes()

    rep = exif_write.write_roll_exif(r, tmp_path, mode="copy")
    assert rep.written == ["s-1.jpg", "s-2.jpg"] and not rep.failed
    assert (tmp_path / "s-1.jpg").read_bytes() == original

    out = tmp_path / exif_write.COPY_DIR / "s-1.jpg"
    ex = piexif.load(str(out))
    assert ex["Exif"][piexif.ExifIFD.FNumber] == (28, 5)
    assert ex["Exif"][piexif.ExifIFD.ExposureTime] == (1, 250)
    assert ex["Exif"][piexif.ExifIFD.ISOSpeedRatings] == 800
    assert ex["Exif"][piexif.ExifIFD.LensModel] == b"50mm f/1.8"
    assert ex["0th"][piexif.ImageIFD.Model] == b"Nikon FM2"
    # pixels untouched
    assert np.array_equal(np.asarray(Image.open(out)), np.asarray(Image.open(tmp_path / "s-1.jpg")))


def test_jpeg_unknown_values_not_written(tmp_path):
    r = _roll(tmp_path, ["s-1.jpg"])
    exif_write.write_roll_exif(r, tmp_path, mode="inplace")
    ex = piexif.load(str(tmp_path / "s-1.jpg"))
    assert piexif.ExifIFD.FNumber not in ex["Exif"]
    assert piexif.ExifIFD.ExposureTime not in ex["Exif"]
    assert ex["Exif"][piexif.ExifIFD.ISOSpeedRatings] == 800


def test_jpeg_inplace_preserves_existing_exif(tmp_path):
    p = tmp_path / "s-1.jpg"
    exif = piexif.dump({"0th": {piexif.ImageIFD.Make: b"NORITSU KOKI"}, "Exif": {}})
    Image.new("RGB", (60, 40)).save(p, exif=exif)
    r = model.load_roll(tmp_path)
    r.frames[0].aperture = 8.0
    rep = exif_write.write_roll_exif(r, tmp_path, mode="inplace")
    assert rep.written == ["s-1.jpg"]
    ex = piexif.load(str(p))
    assert ex["0th"][piexif.ImageIFD.Make] == b"NORITSU KOKI"
    assert ex["Exif"][piexif.ExifIFD.FNumber] == (8, 1)
    assert not list(tmp_path.glob(".exif-*"))


def test_tiff_skipped_without_exiftool(tmp_path):
    r = _roll(tmp_path, ["s-1.tif", "s-2.jpg"])
    rep = exif_write.write_roll_exif(r, tmp_path, mode="copy", exiftool=None)
    assert rep.written == ["s-2.jpg"]
    assert rep.skipped == [("s-1.tif", "needs ExifTool")]
    assert "needs ExifTool" in rep.summary()


def test_bad_jpeg_reported_not_raised(tmp_path):
    r = _roll(tmp_path, ["s-1.jpg"])
    (tmp_path / "s-1.jpg").write_bytes(b"garbage")
    rep = exif_write.write_roll_exif(r, tmp_path, mode="copy")
    assert rep.failed and not rep.written


@pytest.mark.parametrize("mode", ["copy", "inplace"])
def test_tiff_with_exiftool(tmp_path, mode):
    tool = _find_exiftool()
    if not tool:
        pytest.skip("ExifTool not installed")
    r = _roll(tmp_path, ["s-1.tif"])
    r.frames[0].aperture, r.frames[0].shutter, r.frames[0].note = 2.8, "1/60", "Praça do Comércio"
    rep = exif_write.write_roll_exif(r, tmp_path, mode=mode, exiftool=tool)
    assert rep.written == ["s-1.tif"], rep.summary()
    out = tmp_path / ("s-1.tif" if mode == "inplace" else f"{exif_write.COPY_DIR}/s-1.tif")
    with tifffile.TiffFile(out) as tf:
        page = tf.pages[0]
        exif = page.tags["ExifTag"].value
        assert exif["FNumber"] == (28, 10) or exif["FNumber"] == (14, 5)
        assert exif["ExposureTime"] == (1, 60)
        assert page.tags["Model"].value == "Nikon FM2"
        assert "Praça" in page.tags["ImageDescription"].value
        assert page.asarray().dtype == np.uint16
