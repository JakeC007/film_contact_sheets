"""Right-hand panel: preview plus keyboard-first exposure entry for the selected frame(s)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QImage, QPixmap, QTransform
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..editing import Entry, Suggestion, recent_pairs, suggestion_for
from ..gear import Gear, aperture_choices, shutter_choices
from ..model import Roll
from ..stops import (CONDITIONS, ev_at_iso, exposure_pairs, format_aperture, format_shutter,
                     out_of_range_note)

HELP = (
    "<b>Enter</b> save + next &nbsp; <b>Shift+Enter</b> save + previous &nbsp; "
    "<b>PgDn/PgUp</b> move without saving<br>"
    "Blank field on a new frame = use the grey suggestion. <b>?</b> = unknown.<br>"
    "Aperture: 8, 56, f/2.8 &nbsp; Shutter: 125, 1/60, 2s, B, A &nbsp; "
    "<b>Alt+1…6</b> recent pairs"
)


def _pair_text(ap, sh) -> str:
    return "  ".join(t for t in (format_aperture(ap), format_shutter(sh)) if t) or "?"


class PreviewLabel(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(320, 214)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background:#111; color:#888;")
        self._image: QImage | None = None
        self._rotation = 0

    def set_image(self, image: QImage | None, rotation: int = 0, message: str = "") -> None:
        self._image, self._rotation = image, rotation
        if image is None:
            self.setPixmap(QPixmap())
            self.setText(message)
        self._rescale()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._rescale()

    def _rescale(self) -> None:
        if self._image is None:
            return
        pm = QPixmap.fromImage(self._image)
        if self._rotation % 360:
            pm = pm.transformed(QTransform().rotate(self._rotation))
        self.setPixmap(pm.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


class _EnterFilter(QObject):
    """Turns Enter / Shift+Enter / Esc in any field into editor signals."""

    def __init__(self, editor: "FrameEditor"):
        super().__init__(editor)
        self.editor = editor

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                step = -1 if event.modifiers() & Qt.ShiftModifier else 1
                self.editor.commit_requested.emit(step)
                return True
            if key == Qt.Key_Escape:
                self.editor.reload()
                return True
        return False


class FrameEditor(QWidget):
    commit_requested = Signal(int)              # +1 next, -1 previous, 0 stay
    pair_chosen = Signal(object, object)        # aperture, shutter: apply + advance
    hidden_toggled = Signal(bool)
    rotate_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.roll: Roll | None = None
        self.indices: list[int] = []
        self.history: list[tuple] = []
        self.gear: Gear = Gear()

        layout = QVBoxLayout(self)
        self.preview = PreviewLabel()
        layout.addWidget(self.preview, 3)

        self.heading = QLabel()
        self.heading.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.heading)

        form = QFormLayout()
        self.label_edit = QLineEdit()
        self.label_edit.setMaximumWidth(90)
        self.aperture = QLineEdit()
        self.shutter = QLineEdit()
        for w in (self.aperture, self.shutter):
            f = w.font()
            f.setPointSize(f.pointSize() + 4)
            w.setFont(f)
            w.setMaximumWidth(220)
        self.lens = QComboBox(editable=True)
        self.lens.setInsertPolicy(QComboBox.NoInsert)
        self.note = QLineEdit()
        self.hidden = QCheckBox("&Hidden (leave off the sheet)")
        self.hidden.clicked.connect(lambda *_: self.hidden_toggled.emit(self.hidden.isChecked()))
        rotate = QPushButton("Rotate 90°  (Ctrl+R)")
        rotate.clicked.connect(lambda *_: self.rotate_requested.emit())

        form.addRow("Frame #", self.label_edit)
        form.addRow("&Aperture", self.aperture)
        form.addRow("&Shutter", self.shutter)
        form.addRow("&Lens", self.lens)
        form.addRow("&Note", self.note)
        row = QHBoxLayout()
        row.addWidget(self.hidden)
        row.addStretch(1)
        row.addWidget(rotate)
        form.addRow(row)
        layout.addLayout(form)

        self.error = QLabel()
        self.error.setStyleSheet("color:#d33; font-weight:bold;")
        layout.addWidget(self.error)

        save_row = QHBoxLayout()
        save_btn = QPushButton("Save + next  (Enter)")
        save_btn.clicked.connect(lambda *_: self.commit_requested.emit(1))
        save_row.addWidget(save_btn)
        save_row.addStretch(1)
        layout.addLayout(save_row)

        self.recent_box = QGroupBox("Recent pairs (click = save + next)")
        self.recent_layout = QGridLayout(self.recent_box)
        layout.addWidget(self.recent_box)

        hint_box = QGroupBox("Don't remember? Estimate from the light (fills the fields)")
        hv = QVBoxLayout(hint_box)
        self.condition = QComboBox()
        for name, ev in CONDITIONS:
            self.condition.addItem(name, ev)
        self.condition.setCurrentIndex(1)
        self.condition.currentIndexChanged.connect(lambda *_: self._rebuild_hints())
        hv.addWidget(self.condition)
        self.hint_info = QLabel()
        self.hint_info.setWordWrap(True)
        self.hint_info.setStyleSheet("color:#888;")
        hv.addWidget(self.hint_info)
        self.hint_grid = QGridLayout()
        hv.addLayout(self.hint_grid)
        self.lens.editTextChanged.connect(lambda *_: self._rebuild_hints())
        layout.addWidget(hint_box)

        help_label = QLabel(HELP)
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color:#777;")
        layout.addWidget(help_label)

        self._filter = _EnterFilter(self)
        for w in (self.label_edit, self.aperture, self.shutter, self.lens.lineEdit(), self.note):
            w.installEventFilter(self._filter)

        self.setEnabled(False)

    # ------------------------------------------------------------------ public

    def set_roll(self, roll: Roll | None, lens_choices: list[str]) -> None:
        self.roll = roll
        self.history = []
        self.set_lens_choices(lens_choices)
        self.show_frames([])

    def set_lens_choices(self, lenses: list[str]) -> None:
        text = self.lens.currentText()
        self.lens.blockSignals(True)
        self.lens.clear()
        self.lens.addItems([""] + [l for l in lenses if l])
        self.lens.setEditText(text)
        self.lens.blockSignals(False)

    def show_frames(self, indices: list[int]) -> None:
        self.indices = list(indices)
        self.error.clear()
        self.setEnabled(bool(self.roll and indices))
        self.reload()

    def reload(self) -> None:
        """Fill fields from the model for the current selection."""
        roll, idx = self.roll, self.indices
        self.error.clear()
        for w in (self.label_edit, self.aperture, self.shutter, self.note):
            w.clear()
            w.setPlaceholderText("")
        self.lens.setEditText("")
        self.lens.lineEdit().setPlaceholderText("")
        if not roll or not idx:
            self.heading.setText("Open a folder of scans to start.")
            self.preview.set_image(None, message="No frame selected")
            self._rebuild_recent()
            self._rebuild_hints()
            return

        roll_lens = roll.lens.strip()
        if len(idx) == 1:
            fr = roll.frames[idx[0]]
            self.heading.setText(f"<b>Frame {fr.label or '?'}</b> &nbsp; <span style='color:#888'>{fr.filename}</span>")
            self.label_edit.setEnabled(True)
            self.label_edit.setText(fr.label)
            self.note.setText(fr.note)
            self.hidden.setChecked(fr.hidden)
            if fr.has_exposure():
                self.aperture.setText(_strip_f(format_aperture(fr.aperture)))
                self.shutter.setText(fr.shutter or "")
                self.aperture.setPlaceholderText("unknown")
                self.shutter.setPlaceholderText("unknown")
                self.lens.setEditText(fr.lens)
                self.lens.lineEdit().setPlaceholderText(roll_lens or "roll lens")
            else:
                sug = suggestion_for(roll, idx[0])
                self._show_suggestion(sug, roll_lens)
        else:
            frames = [roll.frames[i] for i in idx]
            self.heading.setText(f"<b>{len(idx)} frames selected</b> &nbsp; "
                                 "<span style='color:#888'>only fields you type are applied</span>")
            self.label_edit.setEnabled(False)
            self.hidden.setChecked(all(f.hidden for f in frames))
            aps = {f.aperture for f in frames}
            shs = {f.shutter for f in frames}
            self.aperture.setPlaceholderText(_strip_f(format_aperture(aps.pop())) if len(aps) == 1 else "mixed")
            self.shutter.setPlaceholderText((shs.pop() or "") if len(shs) == 1 else "mixed")
            self.lens.lineEdit().setPlaceholderText("unchanged")
            self.note.setPlaceholderText("unchanged")
        self._rebuild_recent()
        self._rebuild_hints()
        self.focus_aperture()

    def _show_suggestion(self, sug: Suggestion, roll_lens: str) -> None:
        if sug.empty:
            self.aperture.setPlaceholderText("e.g. 8")
            self.shutter.setPlaceholderText("e.g. 125")
        else:
            src = f" (from {sug.source_label})" if sug.source_label else ""
            self.aperture.setPlaceholderText((_strip_f(format_aperture(sug.aperture)) or "unknown") + src)
            self.shutter.setPlaceholderText((sug.shutter or "unknown") + src)
        self.lens.lineEdit().setPlaceholderText(sug.lens or roll_lens or "roll lens")

    def entry(self) -> Entry:
        single = len(self.indices) == 1
        return Entry(
            aperture=self.aperture.text(),
            shutter=self.shutter.text(),
            lens=self.lens.currentText(),
            note=self.note.text(),
            label=self.label_edit.text() if single else None,
        )

    def show_error(self, message: str) -> None:
        self.error.setText(message)

    def focus_aperture(self) -> None:
        self.aperture.setFocus()
        self.aperture.selectAll()

    def set_preview(self, image: QImage | None, rotation: int, message: str = "") -> None:
        self.preview.set_image(image, rotation, message)

    def record_history(self, pair: tuple) -> None:
        if pair != (None, None):
            self.history.append(pair)

    def recent(self) -> list[tuple]:
        return recent_pairs(self.roll, self.history) if self.roll else []

    def fill_fields(self, aperture, shutter) -> None:
        self.aperture.setText(_strip_f(format_aperture(aperture)))
        self.shutter.setText(shutter or "")
        self.aperture.setFocus()

    def refresh_hints(self) -> None:
        self._rebuild_hints()

    # ------------------------------------------------------------------ helpers

    def _rebuild_recent(self) -> None:
        _clear_layout(self.recent_layout)
        pairs = self.recent()
        if not pairs:
            self.recent_layout.addWidget(QLabel("<span style='color:#888'>Nothing yet</span>"), 0, 0)
            return
        for n, (ap, sh) in enumerate(pairs):
            btn = QPushButton(f"{n + 1}:  {_pair_text(ap, sh)}")
            btn.setToolTip(f"Alt+{n + 1}")
            btn.clicked.connect(lambda _=False, a=ap, s=sh: self.pair_chosen.emit(a, s))
            self.recent_layout.addWidget(btn, n // 3, n % 3)

    def current_lens_name(self) -> str:
        """Lens the selected frame was shot with: typed, override, suggestion, or roll lens."""
        typed = self.lens.currentText().strip()
        if typed or not self.roll:
            return typed
        if len(self.indices) == 1:
            fr = self.roll.frames[self.indices[0]]
            if fr.lens:
                return fr.lens
            if not fr.has_exposure():
                sug = suggestion_for(self.roll, self.indices[0])
                if sug.lens:
                    return sug.lens
        return self.roll.lens.strip()

    def _rebuild_hints(self) -> None:
        _clear_layout(self.hint_grid)
        self.hint_info.clear()
        iso = self.roll.effective_iso if self.roll else None
        if not iso:
            self.hint_info.setText("Set the ISO to see estimates.")
            return
        ev100 = self.condition.currentData()
        camera = self.gear.camera(self.roll.camera)
        lens = self.gear.lens(self.current_lens_name())
        apertures, shutters = aperture_choices(lens), shutter_choices(camera)

        limits = []
        limits.append(f"{camera.name}: {format_shutter(camera.fastest)} to "
                      f"{format_shutter(camera.slowest)}" if camera else
                      "camera not in Gear, assuming 1/4000 to 1s")
        limits.append(f"{lens.name}: {format_aperture(lens.widest)} to "
                      f"{format_aperture(lens.smallest)}" if lens else
                      "lens not in Gear, assuming f/1.4 to f/22")
        self.hint_info.setText(
            f"EV {ev100:g} at ISO 100 = EV {ev_at_iso(ev100, iso):.1f} at ISO {iso}. "
            f"Limited to {'; '.join(limits)}.")

        pairs = exposure_pairs(ev100, iso, apertures, shutters)
        if not pairs:
            note = out_of_range_note(ev100, iso, apertures, shutters) or "No settings fit."
            self.hint_grid.addWidget(QLabel(f"<span style='color:#c80'>{note}</span>"), 0, 0)
            return
        for n, (ap, sh) in enumerate(pairs):
            btn = QPushButton(_pair_text(ap, sh))
            btn.clicked.connect(lambda _=False, a=ap, s=sh: self.fill_fields(a, s))
            self.hint_grid.addWidget(btn, n // 4, n % 4)


def _strip_f(text: str) -> str:
    return text[2:] if text.startswith("f/") else text


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
