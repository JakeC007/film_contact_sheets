"""Smoke tests for the GUI, run headless."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from contact_sheet import model  # noqa: E402
from contact_sheet.gui.main_window import MainWindow  # noqa: E402
from contact_sheet.gear import Gear  # noqa: E402
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
    win = MainWindow(settings=settings, library=Library(tmp_path / "lib.json"),
                     gear=Gear.load(tmp_path / "gear.json"))
    win.show()
    win.open_folder(scans)
    win.pool.waitForDone(5000)
    app.processEvents()
    yield win, scans
    win.close()


@pytest.fixture
def slot_errors(monkeypatch):
    """PySide6 reports exceptions raised inside slots via sys.excepthook; collect them."""
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc[1]))
    return errors


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


def test_hidden_checkbox_click_does_not_crash(window, app, slot_errors):
    win, _ = window
    win.select(1)
    app.processEvents()
    box = win.editor.hidden
    from PySide6.QtCore import QPoint
    # A real mouse click on the box itself, the path that crashed before.
    QTest.mouseClick(box, Qt.LeftButton, Qt.NoModifier, QPoint(8, box.height() // 2))
    app.processEvents()
    assert not slot_errors, slot_errors
    assert win.roll.frames[1].hidden is True
    # and back again, applied to several selected frames
    for i in (1, 2):
        win.grid.item(i).setSelected(True)
    app.processEvents()
    box.click()
    app.processEvents()
    assert not slot_errors, slot_errors
    assert [f.hidden for f in win.roll.frames[1:3]] in ([False, False], [True, True])


def test_rotate_button_and_menu_actions_do_not_crash(window, app, slot_errors):
    win, _ = window
    win.select(0)
    app.processEvents()
    from PySide6.QtWidgets import QPushButton
    rotate = next(b for b in win.editor.findChildren(QPushButton) if b.text().startswith("Rotate"))
    rotate.click()
    for action in win.actions():
        if action.text() in ("Rotate 90°", "Next frame (no save)", "Previous frame (no save)"):
            action.trigger()
    app.processEvents()
    assert not slot_errors, slot_errors
    assert win.roll.frames[0].rotation in (90, 180)


def test_gear_dropdowns_and_limited_hints(window, app):
    win, _ = window
    panel = win.roll_panel
    cams = [panel.camera.itemText(i) for i in range(panel.camera.count())]
    lenses = [panel.lens.itemText(i) for i in range(panel.lens.count())]
    assert "Pentax MX" in cams
    assert "SMC Pentax 50mm f/1.4" in lenses and "Pentax 28mm f/2.8" in lenses

    panel.film.setEditText("Kodak Portra 400")
    panel.box_iso.setText("400")
    panel.rated_iso.setText("800")
    panel.camera.setEditText("Pentax MX")
    panel.lens.setEditText("SMC Pentax 50mm f/1.4")
    app.processEvents()
    from PySide6.QtWidgets import QPushButton

    def hint_labels():
        return [w.text() for w in win.editor.findChildren(QPushButton)
                if w.parent() is not None and win.editor.hint_grid.indexOf(w) >= 0]

    labels = hint_labels()
    assert labels and not any("1/2000" in t or "1/4000" in t for t in labels), labels
    assert "Pentax MX: 1/1000 to 1s" in win.editor.hint_info.text()
    assert "SMC Pentax 50mm f/1.4: f/1.4 to f/22" in win.editor.hint_info.text()

    # Dim light: the 50/1.4 can offer f/1.4; switching the frame to the 28/2.8 can't.
    win.editor.condition.setCurrentIndex(
        next(i for i in range(win.editor.condition.count())
             if win.editor.condition.itemText(i) == "Home interior"))
    app.processEvents()
    assert any(t.startswith("f/1.4") for t in hint_labels())
    win.editor.lens.setEditText("Pentax 28mm f/2.8")
    app.processEvents()
    assert hint_labels() and not any(t.startswith(("f/1.4", "f/2 ")) for t in hint_labels())
    assert "Pentax 28mm f/2.8: f/2.8 to f/22" in win.editor.hint_info.text()


def test_impossible_entry_is_saved_but_flagged(window, app):
    win, _ = window
    win.roll_panel.camera.setEditText("Pentax MX")
    app.processEvents()
    win.select(0)
    ed = win.editor
    _type(ed.aperture, "8")
    _type(ed.shutter, "2000")
    QTest.keyClick(ed.shutter, Qt.Key_Return)
    assert win.roll.frames[0].shutter == "1/2000"
    assert "faster than Pentax MX" in win.gear_warning.text()
    _type(ed.aperture, "8")
    _type(ed.shutter, "500")
    QTest.keyClick(ed.shutter, Qt.Key_Return)
    assert win.gear_warning.text() == ""


def test_gear_dialog_edit_and_save(window, app):
    from contact_sheet.gui.gear_dialog import GearDialog
    win, _ = window
    dlg = GearDialog(win.gear, win)
    dlg._add_row("camera")
    r = dlg.cameras.rowCount() - 1
    dlg.cameras.item(r, 0).setText("Nikon FM2")
    dlg.cameras.item(r, 1).setText("4000")        # typed like the frame editor
    dlg.cameras.item(r, 2).setText("1s")
    cams, lenses = dlg.collect()
    assert cams[-1].name == "Nikon FM2" and cams[-1].fastest == "1/4000"
    dlg._save()
    assert Gear.load(win.gear.path).camera("Nikon FM2") is not None

    dlg2 = GearDialog(win.gear, win)
    dlg2.lenses.item(0, 1).setText("banana")
    from contact_sheet.stops import ParseError
    with pytest.raises(ParseError):
        dlg2.collect()


def test_compact_layout_allows_light_background(window, app):
    from contact_sheet.gui.export_dialog import ExportDialog
    from contact_sheet.render import SheetOptions
    win, scans = window
    dlg = ExportDialog(scans, SheetOptions(style="compact"), "jpg", "")
    assert dlg.theme.isEnabled()
    dlg.theme.setCurrentIndex(dlg.theme.findData("light"))
    assert dlg.options().theme == "light" and dlg.options().style == "compact"


def test_app_icon_has_all_sizes(app):
    from contact_sheet.icon import ICO_SIZES, app_qicon
    sizes = {(s.width(), s.height()) for s in app_qicon().availableSizes()}
    assert {(n, n) for n in ICO_SIZES} <= sizes


def test_typed_camera_is_a_one_off_and_partials_are_never_remembered(window, app):
    win, scans = window
    panel = win.roll_panel

    def items(combo):
        return [combo.itemText(i) for i in range(combo.count()) if combo.itemText(i)]

    # Typing letter by letter, with autosaves in between, used to save "P", "Pe", ...
    for partial in ("P", "Pe", "Pen"):
        panel.camera.setEditText(partial)
        panel.lab.setEditText(partial)
        win.save()
    assert win.roll.camera == "Pen"                      # kept on this roll
    assert model.load_roll(scans).camera == "Pen"        # and in its JSON
    assert items(panel.camera) == ["Pentax MX"]          # dropdown is Gear only
    assert "Pen" not in win.library.values("lab")   # nothing remembered mid-typing

    # Finished values are remembered when the roll is put away (folder switch / close / export).
    panel.lab.setEditText("The Darkroom")
    panel.location.setText("Edinburgh")
    panel.lens.setEditText("Some borrowed 35mm")
    win.remember_roll()
    assert win.library.values("lab") == ["The Darkroom"]
    assert win.roll.location == "Edinburgh"
    assert not hasattr(panel.location, "itemText")      # plain text box, no dropdown
    assert "location" not in win.library.items
    assert "Some borrowed 35mm" not in items(panel.lens)
    assert items(panel.lens) == ["SMC Pentax 50mm f/1.4", "Pentax 28mm f/2.8"]
    lens_override = [win.editor.lens.itemText(i) for i in range(win.editor.lens.count())
                     if win.editor.lens.itemText(i)]
    assert lens_override == ["SMC Pentax 50mm f/1.4", "Pentax 28mm f/2.8"]


def _digital_folder(tmp_path):
    import piexif
    scans = tmp_path / "digital"
    scans.mkdir()
    for name, iso, when in (("IMG_7827.JPG", 3200, b"2026:11:08 05:10:00"),
                            ("IMG_7826.JPG", 6400, b"2026:11:08 04:43:18")):
        exif = piexif.dump({
            "0th": {piexif.ImageIFD.Make: b"Canon", piexif.ImageIFD.Model: b"Canon EOS 100D"},
            "Exif": {piexif.ExifIFD.FNumber: (14, 10), piexif.ExifIFD.ExposureTime: (1, 13),
                     piexif.ExifIFD.ISOSpeedRatings: iso, piexif.ExifIFD.FocalLength: (24, 1),
                     piexif.ExifIFD.DateTimeOriginal: when}})
        Image.new("RGB", (300, 200)).save(scans / name, exif=exif)
    return scans


def _new_window(app, tmp_path, monkeypatch, answer):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "cache"))
    win = MainWindow(settings=QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat),
                     library=Library(tmp_path / "lib.json"), gear=Gear.load(tmp_path / "gear.json"))
    asked = []
    win.ask_exif_source = lambda folder, found, total: (asked.append(total), answer)[1]
    win.show()
    return win, asked


def test_digital_folder_asks_once_then_becomes_a_digital_set(app, tmp_path, monkeypatch):
    scans = _digital_folder(tmp_path)
    win, asked = _new_window(app, tmp_path, monkeypatch, "digital")
    win.open_folder(scans)
    win.pool.waitForDone(5000)
    app.processEvents()
    assert asked == [2]
    r = win.roll
    assert r.medium == "digital" and r.exif_source == "digital"
    assert [f.label for f in r.frames] == ["7826", "7827"]           # capture order
    assert [(f.aperture, f.shutter, f.iso, f.focal) for f in r.frames] == [
        (1.4, "1/13", 6400, 24.0), (1.4, "1/13", 3200, 24.0)]
    assert r.camera == "Canon EOS 100D" and r.date == "8 Nov 2026"
    assert "ISO 6400" in win.grid.item(0).text() and "24mm" in win.grid.item(0).text()

    panel, ed = win.roll_panel, win.editor
    assert panel.medium.currentData() == "digital"
    assert not panel.form.isRowVisible(panel.film) and not panel.form.isRowVisible(panel.scanner)
    assert ed.form.isRowVisible(ed.iso) and ed.iso.text() == "6400"
    assert ed.hint_box.isHidden()

    # Camera / lens dropdowns list what EXIF found, not film Gear.
    cams = [panel.camera.itemText(i) for i in range(panel.camera.count()) if panel.camera.itemText(i)]
    assert cams == ["Canon EOS 100D"]
    assert "Pentax MX" not in cams

    # Saved: reopening doesn't ask again.
    win.open_folder(scans)
    assert asked == [2]

    # Edit ISO on a frame.
    win.select(1)
    ed.iso.setText("1600")
    QTest.keyClick(ed.iso, Qt.Key_Return)
    assert win.roll.frames[1].iso == 1600

    from contact_sheet.gui.export_dialog import ExportDialog
    from contact_sheet.render import SheetOptions
    dlg = ExportDialog(scans, SheetOptions(), "jpg", "", allow_exif=False)
    assert not dlg.write_exif.isEnabled() and dlg.exif_choice()[0] is False
    win.close()


def test_film_scanned_with_camera_answer(app, tmp_path, monkeypatch):
    scans = _digital_folder(tmp_path)
    win, asked = _new_window(app, tmp_path, monkeypatch, "scan")
    win.open_folder(scans)
    r = win.roll
    assert r.medium == "film" and r.scanner == "Canon EOS 100D" and r.camera == ""
    assert all(f.aperture is None for f in r.frames)
    assert not win.editor.hint_box.isHidden() and not win.editor.form.isRowVisible(win.editor.iso)
    win.close()


def test_closing_the_question_asks_again_next_time(app, tmp_path, monkeypatch):
    scans = _digital_folder(tmp_path)
    win, asked = _new_window(app, tmp_path, monkeypatch, None)
    win.open_folder(scans)
    assert win.roll.exif_source == "" and all(f.aperture is None for f in win.roll.frames)
    win.open_folder(scans)
    assert asked == [2, 2]
    win.close()


def test_switching_type_by_hand(app, tmp_path, monkeypatch):
    scans = _digital_folder(tmp_path)
    win, asked = _new_window(app, tmp_path, monkeypatch, "ignore")
    win.open_folder(scans)
    assert win.roll.medium == "film" and win.roll.frames[0].aperture is None
    panel = win.roll_panel
    panel.camera.setEditText("Pentax MX")       # set up as film first
    app.processEvents()
    assert win.roll.camera == "Pentax MX"
    panel.medium.setCurrentIndex(panel.medium.findData("digital"))
    panel.medium.activated.emit(panel.medium.currentIndex())
    app.processEvents()
    assert win.roll.medium == "digital" and win.roll.frames[0].iso == 6400
    assert win.roll.camera == "Canon EOS 100D" and panel.camera.currentText() == "Canon EOS 100D"
    film_gear = [panel.camera.itemText(i) for i in range(panel.camera.count())]
    assert "Pentax MX" not in film_gear
    panel.medium.setCurrentIndex(panel.medium.findData("film"))
    panel.medium.activated.emit(panel.medium.currentIndex())
    app.processEvents()
    assert win.roll.medium == "film" and all(f.iso is None for f in win.roll.frames)
    assert panel.form.isRowVisible(panel.film)
    assert "Pentax MX" in [panel.camera.itemText(i) for i in range(panel.camera.count())]
    win.close()


def test_raw_only_folder_explains_why_it_is_empty(app, tmp_path, monkeypatch):
    raws = tmp_path / "raw"
    raws.mkdir()
    for n in ("IMG_1.CR3", "IMG_2.CR3"):
        (raws / n).write_bytes(b"x")
    win, _ = _new_window(app, tmp_path, monkeypatch, None)
    win.open_folder(raws)
    assert "2 RAW file(s) (CR3)" in win.empty_hint.text()
    win.close()


def test_about_text():
    from contact_sheet.gui.main_window import about_html
    html = about_html()
    assert "Jake Chanenson (JakeC007)" in html and "Claude Opus 5.5" in html
    assert "as is" in html and "MIT License" in html
