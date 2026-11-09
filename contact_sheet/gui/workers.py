"""Background jobs: thumbnail/preview loading and sheet rendering."""

from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

from ..imaging import ImageLoadError, load_image
from ..model import Roll
from ..render import SheetOptions, render_sheet, save_sheet

THUMB_SIDE = 480


def cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    d = Path(base) / "film_contact_sheets" / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pil_to_qimage(img: Image.Image) -> QImage:
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    q = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
    return q.copy()  # detach from the Python bytes buffer


def _cached_thumb(path: Path) -> Image.Image:
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_mtime_ns}|{st.st_size}|{THUMB_SIDE}".encode()).hexdigest()
    cached = cache_dir() / f"{key}.jpg"
    if cached.exists():
        try:
            with Image.open(cached) as im:
                return im.convert("RGB")
        except OSError:
            pass
    img = load_image(path, max_side=THUMB_SIDE)
    try:
        img.save(cached, "JPEG", quality=88)
    except OSError:
        pass
    return img


class ImageSignals(QObject):
    loaded = Signal(int, str, str, QImage)    # generation, filename, kind, image
    failed = Signal(int, str, str, str)       # generation, filename, kind, message


class ImageJob(QRunnable):
    def __init__(self, generation: int, path: Path, max_side: int | None, signals: ImageSignals):
        super().__init__()
        self.generation, self.path, self.max_side, self.signals = generation, path, max_side, signals
        self.setAutoDelete(True)

    @property
    def kind(self) -> str:
        return "thumb" if self.max_side is None else "preview"

    def run(self) -> None:
        try:
            if self.max_side is None:
                img = _cached_thumb(self.path)
            else:
                img = load_image(self.path, max_side=self.max_side)
            result = ("loaded", pil_to_qimage(img))
        except (ImageLoadError, OSError) as exc:
            result = ("failed", str(exc))
        except Exception as exc:  # never let a worker thread die silently
            result = ("failed", f"{type(exc).__name__}: {exc}")
        try:
            getattr(self.signals, result[0]).emit(self.generation, self.path.name, self.kind,
                                                  result[1])
        except RuntimeError:
            pass  # window closed while this job was running


class ExifSignals(QObject):
    progress = Signal(int, int)
    done = Signal(object)      # exif_write.Report
    failed = Signal(str)


class ExifJob(QRunnable):
    def __init__(self, roll: Roll, folder: Path, mode: str, exiftool: str | None,
                 signals: ExifSignals):
        super().__init__()
        self.roll = copy.deepcopy(roll)
        self.folder, self.mode, self.exiftool, self.signals = folder, mode, exiftool, signals
        self.setAutoDelete(True)

    def run(self) -> None:
        from ..exif_write import write_roll_exif
        try:
            report = write_roll_exif(self.roll, self.folder, self.mode, self.exiftool,
                                     progress=lambda i, t: self.signals.progress.emit(i, t))
            self.signals.done.emit(report)
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


class RenderSignals(QObject):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)


class RenderJob(QRunnable):
    def __init__(self, roll: Roll, folder: Path, opts: SheetOptions, out_path: Path,
                 signals: RenderSignals):
        super().__init__()
        self.roll = copy.deepcopy(roll)  # the user may keep editing while we render
        self.folder, self.opts, self.out_path, self.signals = folder, opts, out_path, signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            img = render_sheet(self.roll, self.folder, self.opts,
                               progress=lambda i, t: self.signals.progress.emit(i, t))
            save_sheet(img, self.out_path)
            self.signals.done.emit(str(self.out_path))
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
