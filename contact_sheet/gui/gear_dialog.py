"""Gear > Cameras & lenses: edit the saved camera and lens list (gear.json)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..gear import DEFAULT_CAMERAS, DEFAULT_LENSES, Camera, Gear, Lens
from ..stops import ParseError, parse_aperture, parse_shutter

CAMERA_COLS = ["Name", "Fastest shutter", "Slowest shutter", "Bulb", "Notes"]
LENS_COLS = ["Name", "Widest aperture (f/)", "Smallest aperture (f/)", "Notes"]

HELP = ("Double-click a cell to edit. Shutter speeds like <b>1/1000</b> or <b>1s</b>; "
        "apertures like <b>1.7</b> and <b>22</b>. These limits keep the light estimates "
        "to settings your gear can actually make, and flag impossible entries.")


def _text_item(text: str) -> QTableWidgetItem:
    return QTableWidgetItem(text)


def _check_item(checked: bool) -> QTableWidgetItem:
    it = QTableWidgetItem()
    it.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
    it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
    return it


class GearDialog(QDialog):
    def __init__(self, gear: Gear, parent: QWidget | None = None):
        super().__init__(parent)
        self.gear = gear
        self.setWindowTitle("Cameras & lenses")
        self.resize(820, 460)
        v = QVBoxLayout(self)

        info = QLabel(HELP)
        info.setWordWrap(True)
        v.addWidget(info)

        self.tabs = QTabWidget()
        self.cameras = self._table(CAMERA_COLS)
        self.lenses = self._table(LENS_COLS)
        self.tabs.addTab(self._tab(self.cameras, "camera"), "Cameras")
        self.tabs.addTab(self._tab(self.lenses, "lens"), "Lenses")
        v.addWidget(self.tabs, 1)

        path_row = QHBoxLayout()
        self.path_label = QLabel(f"Saved in: {gear.path}")
        self.path_label.setStyleSheet("color:#888;")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        open_btn = QPushButton("Open file…")
        open_btn.setToolTip("Edit gear.json in your text editor, then click Reload")
        open_btn.clicked.connect(lambda *_: self._open_file())
        reload_btn = QPushButton("Reload from file")
        reload_btn.clicked.connect(lambda *_: self._reload())
        restore_btn = QPushButton("Add Pentax MX kit")
        restore_btn.setToolTip("Re-add the built-in Pentax MX and SMC Pentax-M lenses if missing")
        restore_btn.clicked.connect(lambda *_: self._restore_defaults())
        path_row.addWidget(self.path_label, 1)
        for b in (restore_btn, open_btn, reload_btn):
            path_row.addWidget(b)
        v.addLayout(path_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

        self._fill(gear)

    # ------------------------------------------------------------------ building

    def _table(self, cols: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.verticalHeader().setVisible(False)
        h = t.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(len(cols) - 1, QHeaderView.Stretch)
        return t

    def _tab(self, table: QTableWidget, kind: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(table)
        row = QHBoxLayout()
        add = QPushButton(f"Add {kind}")
        add.clicked.connect(lambda *_: self._add_row(kind))
        remove = QPushButton("Remove selected")
        remove.clicked.connect(lambda *_: self._remove_rows(table))
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def _fill(self, gear: Gear) -> None:
        self.cameras.setRowCount(0)
        self.lenses.setRowCount(0)
        for c in gear.cameras:
            self._append_camera(c)
        for l in gear.lenses:
            self._append_lens(l)

    def _append_camera(self, c: Camera) -> None:
        r = self.cameras.rowCount()
        self.cameras.insertRow(r)
        for col, item in enumerate([_text_item(c.name), _text_item(c.fastest),
                                    _text_item(c.slowest), _check_item(c.bulb),
                                    _text_item(c.notes)]):
            self.cameras.setItem(r, col, item)

    def _append_lens(self, l: Lens) -> None:
        r = self.lenses.rowCount()
        self.lenses.insertRow(r)
        for col, item in enumerate([_text_item(l.name), _text_item(f"{l.widest:g}"),
                                    _text_item(f"{l.smallest:g}"), _text_item(l.notes)]):
            self.lenses.setItem(r, col, item)

    def _add_row(self, kind: str) -> None:
        if kind == "camera":
            self._append_camera(Camera("New camera"))
            table = self.cameras
        else:
            self._append_lens(Lens("New lens"))
            table = self.lenses
        row = table.rowCount() - 1
        table.setCurrentCell(row, 0)
        table.editItem(table.item(row, 0))

    def _remove_rows(self, table: QTableWidget) -> None:
        for r in sorted({i.row() for i in table.selectedIndexes()}, reverse=True):
            table.removeRow(r)

    # ------------------------------------------------------------------ reading back

    def _cell(self, table: QTableWidget, r: int, c: int) -> str:
        it = table.item(r, c)
        return it.text().strip() if it else ""

    def collect(self) -> tuple[list[Camera], list[Lens]]:
        """Read the tables; raises ParseError naming the bad row."""
        cams, lenses = [], []
        for r in range(self.cameras.rowCount()):
            name = self._cell(self.cameras, r, 0)
            if not name:
                continue
            try:
                fastest = parse_shutter(self._cell(self.cameras, r, 1)) or "1/1000"
                slowest = parse_shutter(self._cell(self.cameras, r, 2)) or "1s"
            except ParseError as exc:
                raise ParseError(f"Camera '{name}': {exc}") from exc
            bulb_item = self.cameras.item(r, 3)
            cam = Camera(name, fastest, slowest,
                         bulb=bool(bulb_item and bulb_item.checkState() == Qt.Checked),
                         notes=self._cell(self.cameras, r, 4))
            cam.validate()
            cams.append(cam)
        for r in range(self.lenses.rowCount()):
            name = self._cell(self.lenses, r, 0)
            if not name:
                continue
            try:
                widest = parse_aperture(self._cell(self.lenses, r, 1))
                smallest = parse_aperture(self._cell(self.lenses, r, 2))
            except ParseError as exc:
                raise ParseError(f"Lens '{name}': {exc}") from exc
            if widest is None or smallest is None:
                raise ParseError(f"Lens '{name}': fill in both apertures, e.g. 1.7 and 22")
            lens = Lens(name, widest, smallest, notes=self._cell(self.lenses, r, 3))
            lens.validate()
            lenses.append(lens)
        return cams, lenses

    def _save(self) -> None:
        try:
            cams, lenses = self.collect()
        except ParseError as exc:
            QMessageBox.warning(self, "Cameras & lenses", str(exc))
            return
        self.gear.cameras, self.gear.lenses = cams, lenses
        try:
            self.gear.save()
        except OSError as exc:
            QMessageBox.warning(self, "Cameras & lenses", f"Couldn't save {self.gear.path}:\n{exc}")
            return
        self.accept()

    # ------------------------------------------------------------------ file actions

    def _open_file(self) -> None:
        if self.gear.path and not self.gear.path.exists():
            self.gear.save()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.gear.path)))

    def _reload(self) -> None:
        fresh = Gear.load(self.gear.path)
        if fresh.load_error:
            QMessageBox.warning(self, "Cameras & lenses", fresh.load_error +
                                "\nCheck the file for a missing comma or quote.")
            return
        self._fill(fresh)

    def _restore_defaults(self) -> None:
        cams, lenses = self.collect_lenient()
        have_c = {c.lower() for c in cams}
        have_l = {l.lower() for l in lenses}
        for c in DEFAULT_CAMERAS:
            if c.name.lower() not in have_c:
                self._append_camera(c)
        for l in DEFAULT_LENSES:
            if l.name.lower() not in have_l:
                self._append_lens(l)

    def collect_lenient(self) -> tuple[list[str], list[str]]:
        return ([self._cell(self.cameras, r, 0) for r in range(self.cameras.rowCount())],
                [self._cell(self.lenses, r, 0) for r in range(self.lenses.rowCount())])
