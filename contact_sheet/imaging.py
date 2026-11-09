"""Loading scans (JPEG, PNG, 8/16-bit TIFF) as display-ready RGB images."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps

log = logging.getLogger(__name__)

# Lab TIFFs can be 100+ megapixels; we only ever downsample.
Image.MAX_IMAGE_PIXELS = 500_000_000

_SRGB = ImageCms.createProfile("sRGB")


class ImageLoadError(RuntimeError):
    pass


def load_image(path: str | Path, max_side: int | None = None) -> Image.Image:
    """Open a scan as upright 8-bit sRGB, optionally downsampled so its long side <= max_side."""
    path = Path(path)
    try:
        if path.suffix.lower() in (".tif", ".tiff"):
            img = _load_tiff(path, max_side)
        else:
            img = _load_pillow(path, max_side)
    except ImageLoadError:
        raise
    except Exception as exc:  # corrupt file, unsupported codec, etc.
        raise ImageLoadError(f"Could not open {path.name}: {exc}") from exc

    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    return img


def _load_pillow(path: Path, max_side: int | None) -> Image.Image:
    img = Image.open(path)
    if max_side and img.format == "JPEG":
        # Decode at reduced scale; much faster for big scans.
        img.draft("RGB", (max_side, max_side))
    img = ImageOps.exif_transpose(img)
    return _to_srgb(img)


def _load_tiff(path: Path, max_side: int | None) -> Image.Image:
    # Pillow handles ordinary 8-bit TIFFs (and keeps the ICC profile).
    try:
        img = Image.open(path)
        if img.mode in ("RGB", "RGBA", "L", "CMYK", "P", "1"):
            img.load()
            img = ImageOps.exif_transpose(img)
            return _to_srgb(img)
    except Exception:
        pass

    # 16-bit and other high-bit-depth scans.
    import tifffile

    with tifffile.TiffFile(str(path)) as tf:
        page = tf.pages[0]
        arr = page.asarray()
        icc = page.tags.get("InterColorProfile")
        icc_bytes = bytes(icc.value) if icc is not None else None
        orientation_tag = page.tags.get("Orientation")
        orientation = int(orientation_tag.value) if orientation_tag is not None else 1

    img = array_to_image(arr)
    if icc_bytes:
        img.info["icc_profile"] = icc_bytes
    img = _apply_orientation(img, orientation)
    return _to_srgb(img)


def array_to_image(arr: np.ndarray) -> Image.Image:
    """Convert a tifffile array (any bit depth, HxW, HxWxC or CxHxW) to an 8-bit PIL image."""
    a = np.asarray(arr)
    if a.ndim == 3 and a.shape[0] in (1, 3, 4) and a.shape[-1] not in (1, 3, 4):
        a = np.moveaxis(a, 0, -1)  # planar -> interleaved
    if a.ndim == 3 and a.shape[-1] == 1:
        a = a[..., 0]
    if a.ndim == 3 and a.shape[-1] > 4:
        raise ImageLoadError(f"Unsupported TIFF layout {a.shape}")

    if a.dtype == np.uint8:
        out = a
    elif a.dtype == np.uint16:
        out = (a >> 8).astype(np.uint8)
    elif np.issubdtype(a.dtype, np.floating):
        out = (np.clip(a, 0.0, 1.0) * 255 + 0.5).astype(np.uint8)
    elif a.dtype == bool:
        out = a.astype(np.uint8) * 255
    else:
        info = np.iinfo(a.dtype)
        out = ((a.astype(np.float64) - info.min) / (info.max - info.min) * 255).astype(np.uint8)

    if out.ndim == 2:
        return Image.fromarray(out, "L")
    if out.shape[-1] == 4:
        return Image.fromarray(out, "RGBA")
    return Image.fromarray(out[..., :3], "RGB")


_ORIENT_OPS = {
    2: [Image.FLIP_LEFT_RIGHT],
    3: [Image.ROTATE_180],
    4: [Image.FLIP_TOP_BOTTOM],
    5: [Image.TRANSPOSE],
    6: [Image.ROTATE_270],
    7: [Image.TRANSVERSE],
    8: [Image.ROTATE_90],
}


def _apply_orientation(img: Image.Image, orientation: int) -> Image.Image:
    for op in _ORIENT_OPS.get(orientation, []):
        img = img.transpose(op)
    return img


def _to_srgb(img: Image.Image) -> Image.Image:
    icc = img.info.get("icc_profile")
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    elif img.mode == "CMYK" and not icc:
        img = img.convert("RGB")
    elif img.mode not in ("RGB", "L", "CMYK"):
        img = img.convert("RGB")

    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            out_mode = "RGB"
            img = ImageCms.profileToProfile(img, src, _SRGB, outputMode=out_mode)
        except Exception as exc:  # broken profile: show the pixels as-is
            log.debug("ICC conversion skipped: %s", exc)

    if img.mode != "RGB":
        img = img.convert("RGB")
    return img
