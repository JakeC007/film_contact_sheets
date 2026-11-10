"""Dialog for contact sheet layout and output options."""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QWidget)

from ..exif_write import COPY_DIR
from ..render import SheetOptions, default_output_path

FORMATS = [("JPEG", "jpg"), ("PNG", "png"), ("PDF", "pdf")]


def load_options(settings: QSettings) -> tuple[SheetOptions, str]:
    opts = SheetOptions()
    fmt = "jpg"
    raw = settings.value("sheet_options", "")
    if raw:
        try:
            data = json.loads(raw)
            names = {f.name for f in fields(SheetOptions)} - {"title"}
            opts = SheetOptions(**{k: v for k, v in data.items() if k in names})
            fmt = data.get("_format", "jpg")
        except (ValueError, TypeError):
            pass
    return opts, fmt


def store_options(settings: QSettings, opts: SheetOptions, fmt: str) -> None:
    data = asdict(opts)
    data.pop("title", None)  # title is per roll
    data["_format"] = fmt
    settings.setValue("sheet_options", json.dumps(data))


class ExportDialog(QDialog):
    def __init__(self, folder: Path, opts: SheetOptions, fmt: str, title: str,
                 parent: QWidget | None = None, *, write_exif: bool = False,
                 exif_mode: str = "copy", exiftool: str | None = None,
                 allow_exif: bool = True, digital: bool = False,
                 empty_parts: dict[str, str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Export contact sheet")
        self.folder = folder
        form = QFormLayout(self)

        self.title = QLineEdit(title)
        self.title.setPlaceholderText("Optional, e.g. Lisbon, roll 3")
        form.addRow("Title", self.title)

        self.layout_style = QComboBox()
        self.layout_style.addItem("Standard (header block, spaced frames)", "standard")
        self.layout_style.addItem("Compact (tight grid, yellow caption strips)", "compact")
        self.layout_style.addItem("Roll overview (roll details only, no per-frame info)", "overview")
        self.layout_style.setCurrentIndex(max(0, self.layout_style.findData(opts.style)))
        form.addRow("Layout", self.layout_style)

        self.columns = QSpinBox(minimum=1, maximum=12, value=opts.columns)
        form.addRow("Columns", self.columns)

        self.cell_width = QSpinBox(minimum=200, maximum=2000, singleStep=40, value=opts.cell_width)
        self.cell_width.setSuffix(" px per frame")
        form.addRow("Frame size", self.cell_width)

        self.theme = QComboBox()
        self.theme.addItem("Dark (Compact: black with yellow captions)", "dark")
        self.theme.addItem("Light (paper white)", "light")
        self.theme.setCurrentIndex(max(0, self.theme.findData(opts.theme)))
        form.addRow("Background", self.theme)

        self.vertical = QComboBox()
        self.vertical.addItem("Turn sideways to fill the cell", "rotate")
        self.vertical.addItem("Keep upright (smaller)", "fit")
        self.vertical.setCurrentIndex(max(0, self.vertical.findData(opts.vertical)))
        form.addRow("Vertical frames", self.vertical)

        default_fill = opts.style in ("compact", "overview")
        self.fill = QCheckBox("Crop frames to fill cells (trims edges slightly)",
                              checked=default_fill if opts.fill is None else opts.fill)
        form.addRow("", self.fill)
        self.layout_style.currentIndexChanged.connect(self._style_changed)

        # What goes under each frame. Unticking only changes the exported sheet.
        self.show_exposure = QCheckBox("Aperture && shutter", checked=opts.show_exposure)
        self.show_iso = QCheckBox("ISO", checked=opts.show_iso)
        self.show_focal = QCheckBox("Focal length", checked=opts.show_focal)
        self.show_lens = QCheckBox("Lens", checked=opts.show_lens)
        self.show_camera = QCheckBox("Camera", checked=opts.show_camera)
        self.show_notes = QCheckBox("Notes", checked=opts.show_notes)
        self.show_filename = QCheckBox("File names", checked=opts.show_filename)
        self.show_lens.setToolTip("Only printed when a frame's lens differs from the roll lens")
        self.show_camera.setToolTip("Digital sets: only printed for frames from a second body")
        self.show_notes.setToolTip("Frame notes, and the roll notes in the header")
        self.show_filename.setToolTip("On digital sets the file name replaces the frame number")
        # Grey out parts that wouldn't print anything on this roll (same lens / body
        # throughout, film frames with no ISO...). Their ticks are kept for next time.
        if empty_parts is None:
            empty_parts = {} if digital else {
                k: "Digital sets only: film frames share the roll's ISO and camera"
                for k in ("camera", "iso", "focal")}
        boxes = {"lens": self.show_lens, "camera": self.show_camera,
                 "iso": self.show_iso, "focal": self.show_focal}
        self._unusable = {boxes[k] for k in empty_parts if k in boxes}
        for key, reason in empty_parts.items():
            if key in boxes:
                boxes[key].setToolTip(f"{reason}, so there's nothing to show.")
        self.caption_boxes = (self.show_exposure, self.show_iso, self.show_focal,
                              self.show_lens, self.show_camera, self.show_notes,
                              self.show_filename)
        grid = QGridLayout()
        for n, box in enumerate(self.caption_boxes):
            grid.addWidget(box, n // 3, n % 3)
        form.addRow("Under each frame", grid)
        self._set_caption_boxes_enabled(opts.style != "overview")

        self.fmt = QComboBox()
        for name, ext in FORMATS:
            self.fmt.addItem(name, ext)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(fmt)))
        form.addRow("Format", self.fmt)

        row = QHBoxLayout()
        self.out_path = QLineEdit(str(default_output_path(folder, fmt)))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.out_path, 1)
        row.addWidget(browse)
        form.addRow("Save to", row)
        self.fmt.currentIndexChanged.connect(self._format_changed)

        self.write_exif = QCheckBox("Also write exposure details into the scans' EXIF",
                                    checked=write_exif)
        form.addRow("EXIF", self.write_exif)
        self.exif_mode = QComboBox()
        self.exif_mode.addItem(f"Write copies to the '{COPY_DIR}' subfolder", "copy")
        self.exif_mode.addItem("Overwrite the original scans", "inplace")
        self.exif_mode.setCurrentIndex(max(0, self.exif_mode.findData(exif_mode)))
        form.addRow("", self.exif_mode)
        status = ("ExifTool found: JPEG, TIFF and PNG will be tagged." if exiftool else
                  "ExifTool not found: JPEGs will be tagged, TIFF/PNG skipped. "
                  "Install it from exiftool.org or set its location in the File menu.")
        self.exif_status = QLabel(status)
        self.exif_status.setWordWrap(True)
        self.exif_status.setStyleSheet("color:#888;")
        form.addRow("", self.exif_status)
        self.write_exif.toggled.connect(self._exif_toggled)
        self._exif_toggled(write_exif)
        if not allow_exif:   # digital files already carry the camera's own EXIF
            self.write_exif.setChecked(False)
            self.write_exif.setEnabled(False)
            self.exif_status.setText("Digital set: the files already have the camera's EXIF.")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(560, self.sizeHint().height())

    def _style_changed(self) -> None:
        style = self.layout_style.currentData()
        self.fill.setChecked(style in ("compact", "overview"))
        self._set_caption_boxes_enabled(style != "overview")

    def _set_caption_boxes_enabled(self, on: bool) -> None:
        """Roll overview prints no per-frame text, so the boxes don't apply (notes still do)."""
        for box in self.caption_boxes:
            if box is self.show_notes:
                continue
            box.setEnabled(on and box not in self._unusable)

    def _exif_toggled(self, on: bool) -> None:
        self.exif_mode.setEnabled(on)
        self.exif_status.setEnabled(on)

    def exif_choice(self) -> tuple[bool, str]:
        return self.write_exif.isChecked(), self.exif_mode.currentData()

    def _format_changed(self) -> None:
        p = Path(self.out_path.text() or default_output_path(self.folder))
        self.out_path.setText(str(p.with_suffix("." + self.fmt.currentData())))

    def _browse(self) -> None:
        ext = self.fmt.currentData()
        path, _ = QFileDialog.getSaveFileName(self, "Save contact sheet", self.out_path.text(),
                                              f"{ext.upper()} (*.{ext})")
        if path:
            self.out_path.setText(path)

    def options(self) -> SheetOptions:
        return SheetOptions(
            columns=self.columns.value(), cell_width=self.cell_width.value(),
            theme=self.theme.currentData(), vertical=self.vertical.currentData(),
            show_notes=self.show_notes.isChecked(), show_filename=self.show_filename.isChecked(),
            show_exposure=self.show_exposure.isChecked(), show_iso=self.show_iso.isChecked(),
            show_focal=self.show_focal.isChecked(), show_lens=self.show_lens.isChecked(),
            show_camera=self.show_camera.isChecked(),
            title=self.title.text().strip(),
            style=self.layout_style.currentData(), fill=self.fill.isChecked(),
        )

    def format(self) -> str:
        return self.fmt.currentData()

    def output_path(self) -> Path:
        p = Path(self.out_path.text().strip() or default_output_path(self.folder, self.format()))
        if p.suffix.lower().lstrip(".") not in {e for _, e in FORMATS} | {"jpeg"}:
            p = p.with_suffix("." + self.format())
        return p
