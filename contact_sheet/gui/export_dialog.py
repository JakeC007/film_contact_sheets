"""Dialog for contact sheet layout and output options."""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLineEdit, QPushButton, QSpinBox,
                               QWidget)

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
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Export contact sheet")
        self.folder = folder
        form = QFormLayout(self)

        self.title = QLineEdit(title)
        self.title.setPlaceholderText("Optional, e.g. Lisbon, roll 3")
        form.addRow("Title", self.title)

        self.columns = QSpinBox(minimum=1, maximum=12, value=opts.columns)
        form.addRow("Columns", self.columns)

        self.cell_width = QSpinBox(minimum=200, maximum=2000, singleStep=40, value=opts.cell_width)
        self.cell_width.setSuffix(" px per frame")
        form.addRow("Frame size", self.cell_width)

        self.theme = QComboBox()
        self.theme.addItem("Dark", "dark")
        self.theme.addItem("Light", "light")
        self.theme.setCurrentIndex(max(0, self.theme.findData(opts.theme)))
        form.addRow("Background", self.theme)

        self.vertical = QComboBox()
        self.vertical.addItem("Turn sideways to fill the cell", "rotate")
        self.vertical.addItem("Keep upright (smaller)", "fit")
        self.vertical.setCurrentIndex(max(0, self.vertical.findData(opts.vertical)))
        form.addRow("Vertical frames", self.vertical)

        self.show_notes = QCheckBox("Show notes", checked=opts.show_notes)
        self.show_filename = QCheckBox("Show filenames", checked=opts.show_filename)
        form.addRow("", self.show_notes)
        form.addRow("", self.show_filename)

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

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(560, self.sizeHint().height())

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
            title=self.title.text().strip(),
        )

    def format(self) -> str:
        return self.fmt.currentData()

    def output_path(self) -> Path:
        p = Path(self.out_path.text().strip() or default_output_path(self.folder, self.format()))
        if p.suffix.lower().lstrip(".") not in {e for _, e in FORMATS} | {"jpeg"}:
            p = p.with_suffix("." + self.format())
        return p
