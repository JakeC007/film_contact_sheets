# film_contact_sheets

Windows app that turns a folder of film scans into a contact sheet, with the
aperture and shutter speed under each frame and the film, ISO, camera, lens and
scanner in a header. Built for lab scans that carry little or no EXIF.

## Running

Double-click `run.bat`. The first run sets up a `.venv` and installs
dependencies; after that it opens straight away. Drag a scan folder onto
`run.bat` to open it directly, or use `run.bat --console` to keep a console
window open for error output. Crashes are also logged to
`%LOCALAPPDATA%\film_contact_sheets\crash.log`.

By hand:

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
   "Portra 400" fill in the box ISO. Film, scanner and lab are
   remembered for next time (when you export, switch folder or close the app).
   Camera and lens dropdowns only list what's saved in Gear; anything else you
   type there is a one-off for that roll. Location is a plain text box.
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
* **Compact**: frames packed edge to edge with a 1 px seam, a thin caption
  strip above each one, and the roll details on a single strip at the top.
  Dark is black with yellow captions; Light is paper white with dark text.
  Frames are cropped slightly to fill their cells (untick "Crop frames to fill
  cells" to keep the full scan).
* **Roll overview**: no per-frame text at all. A large heading (title, or the
  film), then labelled roll facts: film, ISO, camera, every lens used on the
  roll, location, date, who developed it, scanner, frame count and notes.

## Cameras and lenses (Gear)

The Camera and Lens dropdowns list only your saved gear. To make a camera or
lens a choice, add it in Gear and then pick it; typing a name that isn't in
Gear is fine for a one-off (it's kept on that roll and printed on its sheet)
but it won't be offered again. A Pentax MX (1/1000 to 1 s, B) with an SMC Pentax 50mm f/1.4
and a Pentax 28mm f/2.8 (both to f/22) is set up on first run.

The gear's limits do two things:

* The "Estimate from the light" buttons only suggest settings the camera and
  lens can make (no 1/2000 on an MX, nothing wider than f/1.7 on the 50/1.7).
  If nothing fits, it says whether the scene is too bright or too dark.
* Saving a frame the gear couldn't have shot (say 1/2000 on the MX) still
  saves it, but shows an orange warning in the status bar.

The match is by exact name (not case-sensitive), so pick the camera and lens
from the dropdown. A name that isn't in Gear falls back to 1/4000 to 1 s and
f/1.4 to f/22.

**Editing:** Gear > Cameras & lenses. Add, remove or edit rows (double-click
a cell), then Save. Shutter speeds are typed like the frame editor (`1000`,
`1/1000`, `1s`); apertures like `1.7` and `22`. "Add Pentax MX kit" puts the
built-in entries back if you deleted them.

**By hand:** the list lives in `%APPDATA%\film_contact_sheets\gear.json`.
"Open file…" in the same dialog opens it; edit, save, then "Reload from file".
If the file has a typo the app says so and uses the built-in list without
overwriting your file. Copy this file to move your gear to another PC.

## Reading EXIF that's already there

Most lab scans carry no EXIF. When a folder is opened, each new file's EXIF is
read once, and only **empty** fields are filled; anything typed in the app wins.

* **Film-scanner EXIF** (Noritsu, Frontier, Coolscan, Epson, Plustek, Pakon,
  Imacon, SilverFast, VueScan...) fills the Scanner field. No question asked.
* **EXIF this app wrote** (Software "film_contact_sheets") refills your own film
  entries, e.g. if a folder's roll file was lost. No question asked.
* **Camera EXIF from anywhere else** is ambiguous, because it could be the camera
  that took the photos or one used to scan the film. The first time a folder has
  it, the app asks once:
  * *Film scanned with this camera*: the camera goes in Scanner; its exposure
    EXIF (the scan settings) is ignored.
  * *Photos taken with this camera*: the folder becomes a digital set (below).
  * *Ignore the EXIF.*
  The answer is saved with the roll. Closing the question without choosing asks
  again next time.

Each file is checked once, so a value you clear on purpose stays cleared when
you reopen the folder. Frame > Fill blanks from the files' EXIF re-checks every
file (still blanks only).

## Digital sets (DSLR / mirrorless)

Film is the default. A folder becomes digital by answering *Photos taken with
this camera*, or by setting **Type** to Digital at the top of the roll panel.

* The roll panel hides Film, Box ISO, Shot at ISO, Lab and Scanner.
* Each frame gets its own **ISO** (editable) and focal length from EXIF, plus
  aperture, shutter, lens and camera body. The roll gets the most-used camera
  and lens and the date range.
* **Camera and Lens come from EXIF, not Gear.** When a folder becomes digital,
  the files' camera and lens replace whatever was in those fields (e.g. a film
  camera left over from before). Their dropdowns list only the bodies and lenses
  found in this folder; nothing is added to Gear. Frames shot on a second body
  or lens show it in their caption. After that, your edits are kept.
* Frames are labelled by file number (`IMG_7826.JPG` → 7826) and ordered by
  capture time.
* Captions read `7826  f/1.4  1/13  ISO 6400  24mm`; headers say
  `Digital, ISO 3200-6400`; the Roll overview is titled with the camera.
* The light estimates and Gear warnings are hidden, and writing EXIF is off,
  since the camera recorded it.
* Switching Type back to Film restores edge-number labels and order, and drops
  the per-frame ISO and focal length.

JPEG only for now: RAW files (CR2, CR3, NEF, ARW, RAF, DNG...) are skipped, and
the status bar says how many. A RAW file with a JPEG of the same name is
assumed to be its pair and not counted.

## File formats

| | Formats |
|---|---|
| Opens | JPEG, TIFF (8- and 16-bit, colour or black and white), PNG |
| Contact sheet output | JPEG, PNG, PDF |
| Writes EXIF to | JPEG always; TIFF and PNG with ExifTool |
| Skipped, with a note | RAW (CR2, CR3, NEF, ARW, RAF, DNG, PEF...), HEIC, WebP, AVIF, BMP, GIF |

## Writing EXIF

Tick "Also write exposure details into the scans' EXIF" in the export dialog,
or use File > Write EXIF to scans. Written tags: FNumber, ExposureTime, ISO
(the rated ISO), Model (camera), LensModel, ImageDescription (film, note,
scanner). Unknown values are left out rather than guessed.

* Default mode writes copies to a `with_exif` subfolder. "Overwrite originals"
  replaces the scans (asks first).
* JPEGs are tagged with piexif, which does not re-encode the image.
* TIFF and PNG need [ExifTool](https://exiftool.org). The app looks for it on
  PATH, next to the .exe, or wherever File > Set ExifTool location points.
  Use 13.54 or newer, downloaded from exiftool.org itself, and compare the
  download against the SHA256 checksums published on that page.

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

### Moving or installing the built app

The build is a **folder**, not a lone exe: `dist\FilmContactSheets\` holds
`FilmContactSheets.exe` plus an `_internal` folder with Python, Qt and the
libraries. The exe will not start without `_internal` next to it.

* Move or copy the whole `FilmContactSheets` folder anywhere, e.g.
  `C:\Users\<you>\Apps\FilmContactSheets` or a USB stick. Then right-click the
  exe > Send to > Desktop (create shortcut), or pin it to the taskbar/Start.
  Don't drag the exe out on its own; use a shortcut instead.
* It does not need Python, the repo or the `.venv`. You can delete the repo
  and the app keeps working.
* To share it with another PC, zip the `FilmContactSheets` folder. Windows
  SmartScreen may warn the first time, because the exe isn't code-signed.
* Your data isn't inside the app folder, so moving or rebuilding it loses nothing:
  roll entries in `contact_sheet_roll.json` in each scan folder; gear in
  `%APPDATA%\film_contact_sheets\gear.json`; remembered film/lens names in
  `library.json` next to it; window and export settings in the registry
  (`HKCU\Software\film_contact_sheets`); thumbnails and the crash log in
  `%LOCALAPPDATA%\film_contact_sheets`.
* For a single file you can move by itself, set `ONEFILE = True` in
  `contact_sheet.spec` and rebuild. The trade-off is slower start-up, because it
  unpacks itself to a temp folder on every launch.

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
