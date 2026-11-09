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
