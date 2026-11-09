# film_contact_sheets

Windows app that turns a folder of film scans into a contact sheet, with the
aperture and shutter speed under each frame and the film, ISO, camera, lens and
scanner in a header. Built for lab scans that carry little or no EXIF.

Status: in progress.

## Development

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

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
