import numpy as np
import pytest
import tifffile
from PIL import Image

from contact_sheet import imaging, model, render


def _gradient(w=300, h=200):
    x = np.linspace(0, 255, w, dtype=np.uint8)
    rgb = np.stack([np.tile(x, (h, 1))] * 3, axis=-1)
    rgb[..., 1] = 128
    return rgb


# ------------------------------------------------------------------ loading

def test_load_jpeg_downsamples(tmp_path):
    p = tmp_path / "a-1.jpg"
    Image.fromarray(_gradient(3000, 2000)).save(p)
    img = imaging.load_image(p, max_side=600)
    assert img.mode == "RGB" and max(img.size) == 600


def test_load_jpeg_applies_exif_orientation(tmp_path):
    p = tmp_path / "a-1.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW to display
    Image.fromarray(_gradient(300, 200)).save(p, exif=exif)
    assert imaging.load_image(p).size == (200, 300)


def test_load_16bit_rgb_tiff(tmp_path):
    p = tmp_path / "a-1.tif"
    tifffile.imwrite(p, _gradient().astype(np.uint16) * 257, photometric="rgb")
    img = imaging.load_image(p)
    assert img.mode == "RGB" and img.size == (300, 200)
    assert abs(img.getpixel((299, 0))[0] - 255) <= 1
    assert abs(img.getpixel((0, 0))[1] - 128) <= 1


def test_load_16bit_planar_tiff(tmp_path):
    p = tmp_path / "a-1.tif"
    planar = np.moveaxis(_gradient().astype(np.uint16) * 257, -1, 0)
    tifffile.imwrite(p, planar, photometric="rgb", planarconfig="separate")
    assert imaging.load_image(p).size == (300, 200)


def test_load_16bit_gray_tiff(tmp_path):
    p = tmp_path / "a-1.tif"
    tifffile.imwrite(p, np.full((200, 300), 65535, dtype=np.uint16))
    img = imaging.load_image(p)
    assert img.mode == "RGB" and img.getpixel((5, 5)) == (255, 255, 255)


def test_load_8bit_tiff_via_pillow(tmp_path):
    p = tmp_path / "a-1.tif"
    Image.fromarray(_gradient()).save(p)
    assert imaging.load_image(p).size == (300, 200)


def test_corrupt_file_raises(tmp_path):
    p = tmp_path / "a-1.jpg"
    p.write_bytes(b"nope")
    with pytest.raises(imaging.ImageLoadError):
        imaging.load_image(p)


# ------------------------------------------------------------------ layout

def test_fit_frame_rotates_verticals():
    tall = Image.new("RGB", (200, 300))
    assert render.fit_frame(tall, 300, 200, "rotate", 0).size == (300, 200)
    upright = render.fit_frame(tall, 300, 200, "fit", 0)
    assert upright.height == 200 and upright.width < 200


def test_fit_frame_manual_rotation():
    wide = Image.new("RGB", (300, 200))
    # 90 deg manual makes it vertical, then "rotate" mode turns it back
    assert render.fit_frame(wide, 300, 200, "fit", 90).size[1] == 200


# ------------------------------------------------------------------ sheet

def _make_roll(tmp_path, n=8):
    for i in range(1, n + 1):
        Image.fromarray(_gradient()).save(tmp_path / f"x-R1-0{i}-{i}.jpg")
    roll = model.load_roll(tmp_path)
    roll.film, roll.box_iso = "Kodak Gold 200", 200
    roll.frames[0].aperture, roll.frames[0].shutter = 8.0, "1/125"
    return roll


def test_render_dimensions(tmp_path):
    roll = _make_roll(tmp_path, n=8)
    opts = render.SheetOptions(columns=6, cell_width=320, gap=10, margin=20)
    calls = []
    img = render.render_sheet(roll, tmp_path, opts, progress=lambda i, t: calls.append((i, t)))
    assert img.width == 6 * 320 + 5 * 10 + 2 * 20
    assert calls[-1] == (8, 8)


def test_render_skips_hidden_and_survives_bad_file(tmp_path):
    roll = _make_roll(tmp_path, n=3)
    roll.frames[1].hidden = True
    (tmp_path / roll.frames[2].filename).write_bytes(b"broken")
    calls = []
    render.render_sheet(roll, tmp_path, render.SheetOptions(cell_width=200),
                        progress=lambda i, t: calls.append(t))
    assert calls == [2, 2]


def test_render_empty_header(tmp_path):
    roll = _make_roll(tmp_path, n=1)
    roll.film, roll.box_iso = "", None
    render.render_sheet(roll, tmp_path, render.SheetOptions(cell_width=200))


@pytest.mark.parametrize("ext", ["jpg", "png", "pdf"])
def test_save_formats(tmp_path, ext):
    img = Image.new("RGB", (100, 80))
    out = render.save_sheet(img, render.default_output_path(tmp_path, ext))
    assert out.exists() and "contact_sheet" in out.name


def test_saved_sheet_not_picked_up_as_scan(tmp_path):
    roll = _make_roll(tmp_path, n=2)
    render.save_sheet(render.render_sheet(roll, tmp_path, render.SheetOptions(cell_width=200)),
                      render.default_output_path(tmp_path))
    assert len(model.load_roll(tmp_path).frames) == 2


# ------------------------------------------------------------------ compact style

def test_fit_frame_fill_crops_to_box():
    img = Image.new("RGB", (907, 624))   # lab scan proportions, a bit squarer than 3:2
    assert render.fit_frame(img, 300, 200, "rotate", 0, fill=True).size == (300, 200)
    assert render.fit_frame(img, 300, 200, "rotate", 0, fill=False).size == (291, 200)


def test_compact_layout_dimensions(tmp_path):
    roll = _make_roll(tmp_path, n=8)
    opts = render.SheetOptions(style="compact", columns=6, cell_width=260)
    img = render.render_sheet(roll, tmp_path, opts)
    # 6 cells of 260 with 1 px seams, no outer margin
    assert img.width == 6 * 260 + 5
    # header strip + seam + 2 rows of (18 strip + 173 image) + 1 seam
    assert img.height == 18 + 1 + 2 * (18 + 173) + 1


def test_compact_without_roll_info_has_no_header(tmp_path):
    roll = _make_roll(tmp_path, n=6)
    roll.film, roll.box_iso = "", None
    img = render.render_sheet(roll, tmp_path, render.SheetOptions(style="compact", cell_width=260))
    assert img.height == 18 + 173


def test_compact_text_helpers():
    r = model.Roll(film="Kodak Portra 400", box_iso=400, camera="Nikon FM2", lens="50mm",
                   scanner="Noritsu", date="Oct 2026")
    assert render.compact_header_text(r, "Lisbon") == (
        "Lisbon    Kodak Portra 400, ISO 400    Nikon FM2    50mm    Oct 2026    Scanner Noritsu")
    fr = model.Frame("x-R1-072-34A.jpg", label="34A", aperture=8.0, shutter="1/125")
    assert render.compact_caption(fr, r, False) == "34A  f/8  1/125"
    assert render.compact_caption(fr, r, True) == "34A  x-R1-072-34A  f/8  1/125"


# ------------------------------------------------------------------ overview style

def test_overview_fields_and_lens_summary():
    r = model.Roll(film="Kodak Portra 400", box_iso=400, rated_iso=800, camera="Nikon FM2",
                   lens="50mm f/1.8", location="Lisbon", date="3-12 Oct 2026", lab="The Darkroom")
    r.frames = [model.Frame("a.jpg"), model.Frame("b.jpg", lens="28mm f/2.8"),
                model.Frame("c.jpg", hidden=True, lens="135mm")]
    f = dict(render.overview_fields(r))
    assert f["ISO"] == "800  (box 400, +1)"
    assert f["Lens"] == "50mm f/1.8, 28mm f/2.8"
    assert f["Developed"] == "The Darkroom"
    assert f["Frames"] == "2"
    assert "Scanner" not in f


def test_overview_renders_without_captions(tmp_path, monkeypatch):
    roll = _make_roll(tmp_path, n=7)          # frame 1 has f/8 1/125
    roll.location, roll.date, roll.notes = "Lisbon", "Oct 2026", "Some notes"
    roll.frames[2].note = "frame note"
    drawn = []
    real_text = render.ImageDraw.ImageDraw.text
    monkeypatch.setattr(render.ImageDraw.ImageDraw, "text",
                        lambda self, xy, text, *a, **k: (drawn.append(text), real_text(self, xy, text, *a, **k)))
    img = render.render_sheet(roll, tmp_path, render.SheetOptions(style="overview", cell_width=200,
                                                                   columns=4))
    assert img.width > 4 * 200
    text = " | ".join(drawn)
    assert "Lisbon" in text and "Kodak Gold 200" in text and "Some notes" in text
    assert "f/8" not in text and "1/125" not in text and "frame note" not in text
    assert not any(t == roll.frames[0].label for t in drawn)
