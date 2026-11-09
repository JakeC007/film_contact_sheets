# film_contact_sheets

Windows app that turns a folder of film scans into a contact sheet, with the
aperture and shutter speed under each frame and the film, ISO, camera, lens and
scanner in a header. Built for lab scans that carry little or no EXIF.

## Running

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m contact_sheet            # or: python -m contact_sheet "D:\Scans\Roll 12"
pytest
```

## Workflow

1. Open a folder of scans (Ctrl+O, or drag the folder onto the window).
2. Fill the roll panel once: film, ISO, camera, lens, scanner. Film names like
   "Portra 400" fill in the box ISO; everything you type is remembered for next time.
3. Enter exposures frame by frame. A new frame shows the previous frame's
   values in grey; press Enter to accept them, or type over them.
4. Ctrl+E to export the sheet.

| Key               | Action                                         |
|-------------------|------------------------------------------------|
| Enter             | save frame, go to next                         |
| Shift+Enter       | save frame, go to previous                     |
| PgDn / PgUp       | move without saving                            |
| Esc               | discard edits to this frame                    |
| Alt+1 … Alt+6     | apply a recent aperture/shutter pair, go next  |
| Ctrl+D            | copy previous frame's exposure to selection    |
| Ctrl+R            | rotate 90°                                     |
| Alt+H             | hide frame from the sheet                      |
| Alt+Left / Right  | move frame earlier / later                     |
| Ctrl+E            | export contact sheet                           |

Select several thumbnails (Ctrl/Shift+click) to set the same values on all of
them; only the fields you type in are applied.

## Sheet layouts

* **Standard**: header block with film, ISO, camera, lens and scanner, spaced
  frames, dark or light background.
* **Compact**: frames packed edge to edge on black with a 1 px seam, a thin
  caption strip of small yellow text above each one, and the roll details on a
  single strip at the top. Frames are cropped slightly to fill their cells
  (untick "Crop frames to fill cells" to keep the full scan).
* **Roll overview**: no per-frame text at all. A large heading (title, or the
  film), then labelled roll facts: film, ISO, camera, every lens used on the
  roll, location, date, who developed it, scanner, frame count and notes.

## EXIF

Tick "Also write exposure details into the scans' EXIF" in the export dialog,
or use File > Write EXIF to scans. Written tags: FNumber, ExposureTime, ISO
(the rated ISO), Model (camera), LensModel, ImageDescription (film, note,
scanner). Unknown values are left out rather than guessed.

* Default mode writes copies to a `with_exif` subfolder. "Overwrite originals"
  replaces the scans (asks first).
* JPEGs are tagged with piexif, which does not re-encode the image.
* TIFF and PNG need [ExifTool](https://exiftool.org). The app looks for it on
  PATH, next to the .exe, or wherever File > Set ExifTool location points.

## Building the .exe

```
build.bat
```

This creates a venv, installs dependencies, runs the tests and produces
`dist\FilmContactSheets\FilmContactSheets.exe`. To bundle ExifTool, unzip the
Windows ExifTool download into `vendor\exiftool\` (rename `exiftool(-k).exe`
to `exiftool.exe`, keep the `exiftool_files` folder next to it) before building.
Set `ONEFILE = True` in `contact_sheet.spec` for a single-file exe that starts
more slowly.

## Typing exposures

| You type          | Means                     |
|-------------------|---------------------------|
| `8`, `f8`, `f/8`  | f/8                       |
| `56`, `28`        | f/5.6, f/2.8              |
| `125`, `1/125`    | 1/125                     |
| `2s`, `2"`        | 2 seconds                 |
| `B`, `T`, `A`     | bulb, time, auto          |
| blank, `?`        | unknown (left off sheet)  |

Frame numbers are read from the end of lab filenames
(`...-34A.jpg` → frame 34A) and frames are ordered 00, 0, 1, 1A, 2 ...

Entered data is saved to `contact_sheet_roll.json` in the scan folder.
