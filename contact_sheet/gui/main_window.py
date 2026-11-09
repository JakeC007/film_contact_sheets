"""Main application window."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QSettings, QSize, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import (QAction, QBrush, QColor, QDesktopServices, QIcon, QImage, QIntValidator,
                           QKeySequence, QPainter, QPixmap, QTransform)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileDialog, QFormLayout,
                               QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog,
                               QScrollArea, QSplitter, QVBoxLayout, QWidget)

from .. import __version__
from ..editing import apply_entry, frame_summary, move_frame, next_index, set_exposure
from ..frames import label_sort_key
from ..library import Library
from ..model import Roll, load_roll, save_roll
from ..stops import ParseError
from .export_dialog import ExportDialog, load_options, store_options
from .frame_editor import FrameEditor
from .workers import ImageJob, ImageSignals, RenderJob, RenderSignals

APP_NAME = "Film Contact Sheets"
ICON_SIZE = QSize(210, 140)
PREVIEW_SIDE = 1600
DIM = QColor(140, 140, 140)


# =========================================================================== roll panel

class RollPanel(QWidget):
    """Left panel: things that are the same for the whole roll."""

    def __init__(self, on_change, library: Library, parent=None):
        super().__init__(parent)
        self.on_change = on_change
        self.library = library
        self.roll: Roll | None = None
        self._loading = False

        outer = QVBoxLayout(self)
        form = QFormLayout()
        outer.addLayout(form)
        outer.addStretch(1)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.title = QLineEdit(placeholderText="Optional, e.g. Lisbon, roll 3")
        self.film = self._combo("film")
        self.box_iso = QLineEdit(placeholderText="e.g. 400")
        self.rated_iso = QLineEdit(placeholderText="same as box")
        for w in (self.box_iso, self.rated_iso):
            w.setValidator(QIntValidator(1, 102400))
        self.camera = self._combo("camera")
        self.lens = self._combo("lens")
        self.scanner = self._combo("scanner")
        self.date = QLineEdit(placeholderText="e.g. Oct 2026")
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Roll notes (printed in the header)")
        self.notes.setMaximumHeight(110)

        heading = QLabel("<b>Roll</b>")
        form.addRow(heading)
        form.addRow("Title", self.title)
        form.addRow("Film", self.film)
        form.addRow("Box ISO", self.box_iso)
        form.addRow("Shot at ISO", self.rated_iso)
        form.addRow("Camera", self.camera)
        form.addRow("Lens", self.lens)
        form.addRow("Scanner", self.scanner)
        form.addRow("Date", self.date)
        form.addRow("Notes", self.notes)
        self.push_label = QLabel()
        self.push_label.setStyleSheet("color:#888;")
        form.addRow("", self.push_label)

        for w in (self.title, self.box_iso, self.rated_iso, self.date):
            w.textChanged.connect(self._changed)
        for c in (self.film, self.camera, self.lens, self.scanner):
            c.currentTextChanged.connect(self._changed)
        self.notes.textChanged.connect(self._changed)
        self.film.lineEdit().editingFinished.connect(self._film_finished)
        self.film.activated.connect(lambda _: self._film_finished())
        self.setEnabled(False)

    def _combo(self, kind: str) -> QComboBox:
        c = QComboBox(editable=True)
        c.setInsertPolicy(QComboBox.NoInsert)
        c.setProperty("kind", kind)
        c.addItems([""] + self.library.values(kind))
        c.completer().setCaseSensitivity(Qt.CaseInsensitive)
        c.completer().setFilterMode(Qt.MatchContains)
        return c

    def refresh_choices(self) -> None:
        for c in (self.film, self.camera, self.lens, self.scanner):
            text = c.currentText()
            c.blockSignals(True)
            c.clear()
            c.addItems([""] + self.library.values(c.property("kind")))
            c.setEditText(text)
            c.blockSignals(False)

    def set_roll(self, roll: Roll | None) -> None:
        self.roll = roll
        self._loading = True
        r = roll or Roll()
        self.title.setText(r.title)
        self.film.setEditText(r.film)
        self.box_iso.setText(str(r.box_iso or ""))
        self.rated_iso.setText(str(r.rated_iso or ""))
        self.camera.setEditText(r.camera)
        self.lens.setEditText(r.lens)
        self.scanner.setEditText(r.scanner)
        self.date.setText(r.date)
        self.notes.setPlainText(r.notes)
        self._loading = False
        self.setEnabled(roll is not None)
        self._update_push()

    def _changed(self, *_):
        if self._loading or not self.roll:
            return
        r = self.roll
        r.title = self.title.text().strip()
        r.film = self.film.currentText().strip()
        r.box_iso = _int_or_none(self.box_iso.text())
        r.rated_iso = _int_or_none(self.rated_iso.text())
        r.camera = self.camera.currentText().strip()
        r.lens = self.lens.currentText().strip()
        r.scanner = self.scanner.currentText().strip()
        r.date = self.date.text().strip()
        r.notes = self.notes.toPlainText().strip()
        self._update_push()
        self.on_change()

    def _film_finished(self) -> None:
        if self.roll and not self.box_iso.text().strip():
            iso = self.library.box_iso_for(self.film.currentText())
            if iso:
                self.box_iso.setText(str(iso))

    def _update_push(self) -> None:
        line = self.roll.film_line() if self.roll else ""
        self.push_label.setText(line)


def _int_or_none(text: str) -> int | None:
    text = text.strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


# =========================================================================== main window

class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None, library: Library | None = None):
        super().__init__()
        self.settings = settings or QSettings("film_contact_sheets", "film_contact_sheets")
        self.library = library or Library()
        self.pool = QThreadPool.globalInstance()
        self.folder: Path | None = None
        self.roll: Roll | None = None
        self.thumbs: dict[str, QImage] = {}
        self.thumb_errors: dict[str, str] = {}
        self.preview_cache: dict[str, QImage] = {}
        self._preview_pending: set[str] = set()
        self.generation = 0
        self._render_signals: RenderSignals | None = None

        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1560, 940)

        # widgets
        self.roll_panel = RollPanel(self._roll_changed, self.library)
        roll_scroll = QScrollArea()
        roll_scroll.setWidgetResizable(True)
        roll_scroll.setWidget(self.roll_panel)
        roll_scroll.setMinimumWidth(300)

        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(ICON_SIZE)
        self.grid.setGridSize(QSize(ICON_SIZE.width() + 16, ICON_SIZE.height() + 44))
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setWordWrap(True)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.itemSelectionChanged.connect(self._selection_changed)

        self.editor = FrameEditor()
        self.editor.commit_requested.connect(self.commit)
        self.editor.pair_chosen.connect(self.apply_pair)
        self.editor.hidden_toggled.connect(self.set_hidden)
        self.editor.rotate_requested.connect(self.rotate_selected)

        split = QSplitter()
        split.addWidget(roll_scroll)
        split.addWidget(self.grid)
        split.addWidget(self.editor)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 2)
        split.setSizes([320, 760, 480])
        self.setCentralWidget(split)

        self.empty_hint = QLabel("Open a folder of scans (Ctrl+O) or drop one here.", self.grid)
        self.empty_hint.setStyleSheet("color:#888; font-size:15px; padding:30px;")
        self.empty_hint.adjustSize()

        self.image_signals = ImageSignals()
        self.image_signals.loaded.connect(self._image_loaded)
        self.image_signals.failed.connect(self._image_failed)

        self.save_timer = QTimer(self, singleShot=True, interval=600)
        self.save_timer.timeout.connect(self.save)

        self._build_actions()
        self.statusBar().showMessage("Ready")

    # ------------------------------------------------------------------ actions

    def _build_actions(self) -> None:
        def act(menu, text, slot, shortcut=None):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
                a.setShortcutContext(Qt.WindowShortcut)
            a.triggered.connect(slot)
            menu.addAction(a)
            self.addAction(a)
            return a

        m = self.menuBar().addMenu("&File")
        act(m, "&Open folder…", self.choose_folder, "Ctrl+O")
        self.reload_action = act(m, "&Reload folder", self.reload_folder, "F5")
        act(m, "&Save", self.save, "Ctrl+S")
        m.addSeparator()
        self.export_action = act(m, "&Export contact sheet…", self.export, "Ctrl+E")
        m.addSeparator()
        act(m, "E&xit", self.close, "Alt+F4")

        m = self.menuBar().addMenu("&Frame")
        act(m, "Next frame (no save)", lambda: self.step(1), "PgDown")
        act(m, "Previous frame (no save)", lambda: self.step(-1), "PgUp")
        act(m, "Select all frames", self.grid.selectAll, "Ctrl+Shift+A")
        m.addSeparator()
        act(m, "Rotate 90°", self.rotate_selected, "Ctrl+R")
        act(m, "Move earlier", lambda: self.move_selected(-1), "Alt+Left")
        act(m, "Move later", lambda: self.move_selected(1), "Alt+Right")
        act(m, "Sort by frame number", self.sort_by_label)
        m.addSeparator()
        act(m, "Clear exposure on selected", self.clear_selected)
        act(m, "Copy previous frame to selected", self.copy_previous, "Ctrl+D")
        for n in range(1, 7):
            act(m, f"Use recent pair {n}", lambda _=False, k=n: self.use_recent(k), f"Alt+{n}")

        m = self.menuBar().addMenu("&Help")
        act(m, "&About", self.about)

    # ------------------------------------------------------------------ folder

    def choose_folder(self) -> None:
        start = self.settings.value("last_folder", str(Path.home()))
        path = QFileDialog.getExistingDirectory(self, "Folder of scans", start)
        if path:
            self.open_folder(Path(path))

    def reload_folder(self) -> None:
        if self.folder:
            self.save()
            self.open_folder(self.folder)

    def open_folder(self, folder: Path) -> None:
        if self.roll and self.folder:
            self.save()
        try:
            roll = load_roll(folder)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Couldn't read {folder}:\n{exc}")
            return
        self.folder, self.roll = folder, roll
        self.settings.setValue("last_folder", str(folder))
        self.generation += 1
        self.thumbs.clear()
        self.thumb_errors.clear()
        self.preview_cache.clear()
        self._preview_pending.clear()
        self.setWindowTitle(f"{folder.name} - {APP_NAME}")

        self.roll_panel.set_roll(roll)
        self.editor.set_roll(roll, self._lens_choices())
        self._rebuild_grid()
        self.empty_hint.setVisible(not roll.frames)
        if not roll.frames:
            self.empty_hint.setText("No JPEG, TIFF or PNG scans in this folder.")
            self.empty_hint.adjustSize()
        for fr in roll.frames:
            self.pool.start(ImageJob(self.generation, folder / fr.filename, None, self.image_signals))
        if roll.frames:
            first = next((i for i, f in enumerate(roll.frames) if not f.has_exposure() and not f.hidden), 0)
            self.select(first)
        self.statusBar().showMessage(f"{len(roll.frames)} scans in {folder}")

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file():
                p = p.parent
            if p.is_dir():
                self.open_folder(p)
                return

    # ------------------------------------------------------------------ grid

    def _rebuild_grid(self) -> None:
        self.grid.blockSignals(True)
        self.grid.clear()
        if self.roll:
            for _ in self.roll.frames:
                self.grid.addItem(QListWidgetItem())
            for i in range(len(self.roll.frames)):
                self._refresh_item(i)
        self.grid.blockSignals(False)

    def _refresh_item(self, i: int) -> None:
        fr = self.roll.frames[i]
        item = self.grid.item(i)
        text = f"{fr.label or '?'}   {frame_summary(fr, self.roll.lens)}"
        if fr.hidden:
            text = f"{fr.label or '?'}   (hidden)"
        item.setText(text)
        item.setToolTip(f"{fr.filename}\n{fr.note}" if fr.note else fr.filename)
        unknown = fr.hidden or not fr.has_exposure()
        item.setForeground(QBrush(DIM) if unknown else QBrush())
        item.setIcon(self._icon_for(fr))

    def _icon_for(self, fr) -> QIcon:
        img = self.thumbs.get(fr.filename)
        pm = QPixmap(ICON_SIZE)
        pm.fill(QColor(30, 30, 30))
        if img is not None:
            src = QPixmap.fromImage(img)
            if fr.rotation % 360:
                src = src.transformed(QTransform().rotate(fr.rotation))
            src = src.scaled(ICON_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p = QPainter(pm)
            if fr.hidden:
                p.setOpacity(0.3)
            p.drawPixmap((ICON_SIZE.width() - src.width()) // 2,
                         (ICON_SIZE.height() - src.height()) // 2, src)
            p.end()
        else:
            p = QPainter(pm)
            p.setPen(QColor(200, 80, 80) if fr.filename in self.thumb_errors else QColor(120, 120, 120))
            p.drawText(pm.rect(), Qt.AlignCenter,
                       "Can't open" if fr.filename in self.thumb_errors else "Loading…")
            p.end()
        return QIcon(pm)

    def _index_of(self, filename: str) -> int | None:
        if not self.roll:
            return None
        for i, f in enumerate(self.roll.frames):
            if f.filename == filename:
                return i
        return None

    def _image_loaded(self, generation: int, filename: str, kind: str, image: QImage) -> None:
        if generation != self.generation:
            return
        if kind == "preview":
            self._preview_pending.discard(filename)
            self.preview_cache[filename] = image
            if len(self.preview_cache) > 12:
                self.preview_cache.pop(next(iter(self.preview_cache)))
            self._update_preview()
            return
        self.thumbs[filename] = image
        i = self._index_of(filename)
        if i is not None:
            self._refresh_item(i)
            if self.selected() == [i] and filename not in self.preview_cache:
                self.editor.set_preview(image, self.roll.frames[i].rotation)

    def _image_failed(self, generation: int, filename: str, kind: str, message: str) -> None:
        if generation != self.generation:
            return
        self._preview_pending.discard(filename)
        self.thumb_errors[filename] = message
        i = self._index_of(filename)
        if i is not None:
            self._refresh_item(i)
            if self.selected() == [i]:
                self._update_preview()

    # ------------------------------------------------------------------ selection

    def selected(self) -> list[int]:
        return sorted(self.grid.row(it) for it in self.grid.selectedItems())

    def select(self, i: int) -> None:
        if not self.roll or not (0 <= i < len(self.roll.frames)):
            return
        self.grid.setCurrentRow(i, QItemSelectionModel.ClearAndSelect)
        self.grid.scrollToItem(self.grid.item(i))

    def _selection_changed(self) -> None:
        idx = self.selected()
        self.editor.show_frames(idx)
        self._update_preview()

    def _update_preview(self) -> None:
        idx = self.selected()
        if len(idx) != 1 or not self.roll:
            self.editor.set_preview(None, 0, f"{len(idx)} frames selected" if idx else "")
            return
        fr = self.roll.frames[idx[0]]
        if fr.filename in self.thumb_errors:
            self.editor.set_preview(None, 0, "Can't open this file:\n" + self.thumb_errors[fr.filename])
            return
        img = self.preview_cache.get(fr.filename)
        if img is None:
            img = self.thumbs.get(fr.filename)
            if fr.filename in self._preview_pending:
                self.editor.set_preview(img, fr.rotation, "Loading…")
                return
            self._preview_pending.add(fr.filename)
            self.pool.start(ImageJob(self.generation, self.folder / fr.filename, PREVIEW_SIDE,
                                     self.image_signals))
        self.editor.set_preview(img, fr.rotation, "Loading…")

    def step(self, direction: int) -> None:
        idx = self.selected()
        if not self.roll or not self.roll.frames:
            return
        if not idx:
            self.select(0)
            return
        anchor = idx[-1] if direction > 0 else idx[0]
        self.select(next_index(self.roll, anchor, direction))

    # ------------------------------------------------------------------ editing

    def commit(self, direction: int) -> None:
        idx = self.selected()
        if not self.roll or not idx:
            return
        try:
            apply_entry(self.roll, idx, self.editor.entry())
        except ParseError as exc:
            self.editor.show_error(str(exc))
            return
        first = self.roll.frames[idx[0]]
        self.editor.record_history((first.aperture, first.shutter))
        self._after_edit(idx)
        self._advance(idx, direction)

    def apply_pair(self, aperture, shutter) -> None:
        idx = self.selected()
        if not self.roll or not idx:
            return
        set_exposure(self.roll, idx, aperture, shutter)
        self.editor.record_history((aperture, shutter))
        self._after_edit(idx)
        self._advance(idx, 1)

    def use_recent(self, n: int) -> None:
        pairs = self.editor.recent()
        if 0 < n <= len(pairs):
            self.apply_pair(*pairs[n - 1])

    def copy_previous(self) -> None:
        idx = self.selected()
        if not self.roll or not idx or idx[0] == 0:
            return
        src = self.roll.frames[idx[0] - 1]
        for i in idx:
            fr = self.roll.frames[i]
            fr.aperture, fr.shutter, fr.lens = src.aperture, src.shutter, src.lens
        self._after_edit(idx)
        self.editor.reload()

    def clear_selected(self) -> None:
        idx = self.selected()
        if not self.roll or not idx:
            return
        set_exposure(self.roll, idx, None, None)
        self._after_edit(idx)
        self.editor.reload()

    def set_hidden(self, hidden: bool) -> None:
        idx = self.selected()
        for i in idx:
            self.roll.frames[i].hidden = hidden
        self._after_edit(idx)

    def rotate_selected(self) -> None:
        idx = self.selected()
        if not self.roll or not idx:
            return
        for i in idx:
            fr = self.roll.frames[i]
            fr.rotation = (fr.rotation + 90) % 360
        self._after_edit(idx)
        self._update_preview()

    def move_selected(self, delta: int) -> None:
        idx = self.selected()
        if not self.roll or len(idx) != 1:
            return
        new = move_frame(self.roll, idx[0], delta)
        if new != idx[0]:
            self._rebuild_grid()
            self.select(new)
            self._schedule_save()

    def sort_by_label(self) -> None:
        if not self.roll:
            return
        current = self.selected()
        names = [self.roll.frames[i].filename for i in current]
        self.roll.frames.sort(key=lambda f: label_sort_key(f.label))
        self._rebuild_grid()
        if names:
            i = self._index_of(names[0])
            if i is not None:
                self.select(i)
        self._schedule_save()

    def _after_edit(self, idx: list[int]) -> None:
        for i in idx:
            self._refresh_item(i)
        self._schedule_save()

    def _advance(self, idx: list[int], direction: int) -> None:
        if direction == 0:
            self.editor.reload()
            return
        anchor = idx[-1] if direction > 0 else idx[0]
        target = next_index(self.roll, anchor, direction)
        if target == anchor and len(idx) == 1:
            self.statusBar().showMessage("Last frame" if direction > 0 else "First frame", 3000)
            self.editor.reload()
            return
        self.select(target)

    def _roll_changed(self) -> None:
        if not self.roll:
            return
        for i in range(len(self.roll.frames)):
            self._refresh_item(i)  # roll lens affects captions
        self.editor.refresh_hints()
        self._schedule_save()

    def _lens_choices(self) -> list[str]:
        return self.library.values("lens")

    # ------------------------------------------------------------------ save / export

    def _schedule_save(self) -> None:
        self.save_timer.start()

    def save(self) -> None:
        self.save_timer.stop()
        if not self.roll or not self.folder:
            return
        try:
            save_roll(self.roll, self.folder)
            self.library.remember_roll(self.roll)
            self.library.save()
            self.statusBar().showMessage("Saved", 1500)
        except OSError as exc:
            self.statusBar().showMessage(f"Save failed: {exc}")

    def export(self) -> None:
        if not self.roll or not self.folder:
            return
        missing = [f.label for f in self.roll.visible_frames() if not f.has_exposure()]
        opts, fmt = load_options(self.settings)
        dlg = ExportDialog(self.folder, opts, fmt, self.roll.title, self)
        if missing:
            dlg.setToolTip(f"{len(missing)} frames have no exposure yet")
        if dlg.exec() != ExportDialog.Accepted:
            return
        opts = dlg.options()
        store_options(self.settings, opts, dlg.format())
        if opts.title != self.roll.title:
            self.roll.title = opts.title
            self.roll_panel.set_roll(self.roll)
        self.save()
        out = dlg.output_path()

        progress = QProgressDialog("Rendering contact sheet…", None, 0,
                                   max(1, len(self.roll.visible_frames())), self)
        progress.setWindowTitle(APP_NAME)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        signals = RenderSignals()
        self._render_signals = signals  # keep alive
        signals.progress.connect(lambda i, t: progress.setValue(i))
        signals.done.connect(lambda p: self._export_done(progress, Path(p)))
        signals.failed.connect(lambda m: self._export_failed(progress, m))
        self.pool.start(RenderJob(self.roll, self.folder, opts, out, signals))

    def _export_done(self, progress: QProgressDialog, path: Path) -> None:
        progress.close()
        self.statusBar().showMessage(f"Saved {path}")
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(f"Contact sheet saved:\n{path}")
        open_btn = box.addButton("Open", QMessageBox.AcceptRole)
        folder_btn = box.addButton("Show folder", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        elif box.clickedButton() is folder_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _export_failed(self, progress: QProgressDialog, message: str) -> None:
        progress.close()
        QMessageBox.warning(self, APP_NAME, f"Export failed:\n{message}")

    # ------------------------------------------------------------------ misc

    def about(self) -> None:
        QMessageBox.about(self, APP_NAME, f"{APP_NAME} {__version__}\n\n"
                          "Builds contact sheets from film scans with exposure details.")

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.empty_hint.move(10, 10)

    def closeEvent(self, e) -> None:
        self.save()
        self.pool.waitForDone(3000)
        super().closeEvent(e)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName("film_contact_sheets")
    app = QApplication.instance() or QApplication(argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    if len(argv) > 1 and Path(argv[1]).is_dir():
        win.open_folder(Path(argv[1]))
    return app.exec()
