# PyInstaller spec for Film Contact Sheets.
#   pip install -r requirements-dev.txt
#   pyinstaller --noconfirm contact_sheet.spec
# Output: dist\FilmContactSheets\FilmContactSheets.exe
#
# Optional: to bundle ExifTool (for TIFF/PNG EXIF), unzip the Windows
# ExifTool download into vendor\exiftool\ so that it contains exiftool.exe
# (rename "exiftool(-k).exe") and the exiftool_files folder.

import sys
from pathlib import Path

ONEFILE = False  # True = single .exe, but it unpacks ~100 MB on every launch (slow start)

root = Path(SPECPATH)

# The .exe icon (shown in Explorer, on shortcuts and on the taskbar) is drawn by the
# app's own code and written out fresh for each build.
sys.path.insert(0, str(root))
from contact_sheet.icon import write_ico  # noqa: E402
ICON = str(write_ico(root / "build" / "app.ico"))

datas = []
exiftool_dir = root / "vendor" / "exiftool"
if (exiftool_dir / "exiftool.exe").exists():
    datas.append((str(exiftool_dir), "exiftool"))

# Qt modules the app never touches; leaving them out cuts the build size a lot.
excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore",
    "PySide6.Qt3DRender", "PySide6.Qt3DExtras", "PySide6.QtMultimedia", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtBluetooth", "PySide6.QtNetworkAuth", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtDesigner", "PySide6.QtLocation", "PySide6.QtPositioning", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtWebSockets", "PySide6.QtWebChannel",
    "tkinter", "matplotlib", "pytest",
]

a = Analysis(
    [str(root / "run_app.py")],
    pathex=[str(root)],
    datas=datas,
    hiddenimports=["tifffile", "piexif", "PIL.ImageCms"],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="FilmContactSheets",
              console=False, upx=False, icon=ICON)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FilmContactSheets",
              console=False, upx=False, icon=ICON)
    coll = COLLECT(exe, a.binaries, a.datas, name="FilmContactSheets", upx=False)
