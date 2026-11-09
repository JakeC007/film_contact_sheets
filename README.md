# film_contact_sheets

Windows app that turns a folder of film scans into a contact sheet, with the
aperture and shutter speed under each frame and the film, ISO, camera, lens and
scanner in a header. Built for lab scans that carry little or no EXIF.

Status: in progress.

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
