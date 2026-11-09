"""Smoke tests for the GUI, run headless."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from contact_sheet import model  # noqa: E402
from contact_sheet.gui.main_window import MainWindow  # noqa: E402
from contact_sheet.library import Library  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "cache"))
    scans = tmp_path / "roll"
    scans.mkdir()
    for i in range(1, 6):
        Image.new("RGB", (300, 200), (40 * i, 80, 120)).save(scans / f"x-R1-0{i}-{i}.jpg")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    win = MainWindow(settings=settings, library=Library(tmp_path / "lib.json"))
    win.show()
    win.open_folder(scans)
    win.pool.waitForDone(5000)
    app.processEvents()
    yield win, scans
    win.close()


def _type(widget, text):
    widget.setFocus()
    widget.selectAll()
    QTest.keyClicks(widget, text)


def test_keyboard_entry_flow(window, app):
    win, scans = window
    ed = win.editor
    assert win.selected() == [0]

    _type(ed.aperture, "8")
    _type(ed.shutter, "125")
    QTest.keyClick(ed.shutter, Qt.Key_Return)
    assert win.selected() == [1]
    assert (win.roll.frames[0].aperture, win.roll.frames[0].shutter) == (8.0, "1/125")

    # Blank + Enter takes the suggestion, twice in a row.
    assert "8" in ed.aperture.placeholderText()
    QTest.keyClick(ed.aperture, Qt.Key_Return)
    QTest.keyClick(ed.aperture, Qt.Key_Return)
    assert win.selected() == [3]
    assert [f.shutter for f in win.roll.frames[:3]] == ["1/125"] * 3

    # Bad input shows an error and does not advance.
    _type(ed.shutter, "banana")
    QTest.keyClick(ed.shutter, Qt.Key_Return)
    assert win.selected() == [3]
    assert ed.error.text()

    # Shift+Enter goes back.
    _type(ed.aperture, "16")
    _type(ed.shutter, "500")
    QTest.keyClick(ed.shutter, Qt.Key_Return, Qt.ShiftModifier)
    assert win.selected() == [2]
    assert win.roll.frames[3].aperture == 16.0

    win.save()
    saved = model.load_roll(scans)
    assert saved.frames[3].shutter == "1/500"


def test_recent_pair_shortcut_and_multi_select(window, app):
    win, _ = window
    ed = win.editor
    _type(ed.aperture, "2.8")
    _type(ed.shutter, "60")
    QTest.keyClick(ed.shutter, Qt.Key_Return)
    win.use_recent(1)
    assert win.roll.frames[1].aperture == 2.8
    assert win.selected() == [2]

    for i in (2, 3, 4):
        win.grid.item(i).setSelected(True)
    app.processEvents()
    assert win.selected() == [2, 3, 4]
    _type(ed.aperture, "11")
    QTest.keyClick(ed.aperture, Qt.Key_Return)
    assert [f.aperture for f in win.roll.frames[2:]] == [11.0, 11.0, 11.0]
    assert [f.shutter for f in win.roll.frames[2:]] == [None, None, None]


def test_roll_panel_and_iso_from_film(window, app):
    win, _ = window
    panel = win.roll_panel
    panel.film.setEditText("Kodak Portra 400")
    panel._film_finished()
    assert win.roll.box_iso == 400
    panel.rated_iso.setText("800")
    assert win.roll.film_line() == "Kodak Portra 400 @ ISO 800 (+1)"
    # hints appear once ISO is known
    assert win.editor.hint_grid.count() > 1


def test_rotate_hide_and_move(window, app):
    win, _ = window
    win.select(1)
    win.rotate_selected()
    assert win.roll.frames[1].rotation == 90
    win.set_hidden(True)
    assert win.roll.frames[1].hidden
    win.select(0)
    win.move_selected(1)
    assert win.roll.frames[1].label == "1"
    win.sort_by_label()
    assert [f.label for f in win.roll.frames] == ["1", "2", "3", "4", "5"]


def test_exif_job_and_dialog(window, app):
    from contact_sheet.exif_write import COPY_DIR
    from contact_sheet.gui.export_dialog import ExportDialog
    from contact_sheet.gui.workers import ExifJob, ExifSignals
    from contact_sheet.render import SheetOptions

    win, scans = window
    dlg = ExportDialog(scans, SheetOptions(), "jpg", "", write_exif=True, exif_mode="inplace",
                       exiftool=None)
    assert dlg.exif_choice() == (True, "inplace")
    assert "not found" in dlg.exif_status.text()
    dlg.write_exif.setChecked(False)
    assert not dlg.exif_mode.isEnabled()

    win.roll.frames[0].aperture = 8.0
    sig = ExifSignals()
    reports = []
    sig.done.connect(reports.append)
    win.pool.start(ExifJob(win.roll, scans, "copy", None, sig))
    win.pool.waitForDone(10000)
    app.processEvents()
    assert reports and len(reports[0].written) == 5
    assert (scans / COPY_DIR / win.roll.frames[0].filename).exists()
    # copies in the subfolder are not picked up as new scans
    assert len(model.load_roll(scans).frames) == 5


def test_render_job_runs(window, app, tmp_path):
    from contact_sheet.gui.workers import RenderJob, RenderSignals
    from contact_sheet.render import SheetOptions

    win, scans = window
    out = tmp_path / "out_contact_sheet.jpg"
    sig = RenderSignals()
    done = []
    sig.done.connect(done.append)
    win.pool.start(RenderJob(win.roll, scans, SheetOptions(cell_width=200), out, sig))
    win.pool.waitForDone(10000)
    app.processEvents()
    assert done and out.exists()
