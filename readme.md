# Drone Floor Plan Annotator

Tkinter desktop app for annotating windows on a floor plan image and computing drone observation points, heading, and georeferenced outputs.

## Features

- Load floor plan images (`png`, `jpg`, `jpeg`, `bmp`, `tif`, `tiff`, `webp`)
- Pan and zoom canvas
- Set image origin
- Calibrate X and Y scale with known real-world lengths
- Add window annotations with 3 clicks:
  1. endpoint 1
  2. endpoint 2
  3. side selector click
- Auto-compute drone standoff from window width, HFOV, and fill ratio
- Compute drone heading (degrees clockwise from north)
- Save and load project JSON
- Export CSV and verbose JSON
- View drone points on map from project JSON (`project_map_viewer.py`)

## Coordinate Model

After origin is set:

- image `x` increases to the right
- image `y` increases downward
- local `east` increases to the right
- local `north` increases upward

Image to local conversion:

- `east_m = (px_x - origin_x) * meters_per_pixel`
- `north_m = -(px_y - origin_y) * meters_per_pixel`

## Window Standoff Formula

```text
d_m = W_m / (2 * tan(HFOV / 2) * fill_ratio)
```

Where:

- `W_m` is window width in meters
- `HFOV` is horizontal field of view in degrees
- `fill_ratio` is desired frame fill ratio

## Georeferencing

When georef inputs are provided:

- origin latitude/longitude/altitude
- plan `+Y` azimuth clockwise from true north

the app converts local ENU-like coordinates to LLA using `navpy`.

## Save vs Export

### Save Project

- Saves editable working state
- Saves annotations
- Includes computed `drone_lat_deg`, `drone_lon_deg`, `drone_alt_m` inside annotations when georef is set

### Export JSON

- Contains `project` plus flat `exports` rows
- `project.annotations` also includes computed drone LLA fields

### Export CSV

- Flat per-annotation rows for scripting/spreadsheets

## Controls

### Tools

- `Select`: select annotation
- `Pan`: pan-mode left-click behavior
- `Origin`: place origin
- `Cal X`: set X calibration
- `Cal Y`: set Y calibration
- `Window`: add window

### Mouse

- Mouse wheel: zoom
- Middle drag or right drag: pan
- Left click: active tool action

### Keyboard

- `Esc`: cancel current temp operation and switch to `Select`
- `Ctrl+S`: save project
- `Ctrl+Z`: undo
- `Ctrl+Y`: redo

## Output Folders

Current default outputs are organized as:

- `output/project/json`: project saves and JSON exports
- `output/project/csv`: CSV exports

`exporter.py` also writes CSV output to `output/project/csv`.

## Map Viewer Utility

`project_map_viewer.py` loads project JSON and displays drone LLA + heading markers on a map.

Map style dropdown options:

- Google normal (default)
- Google satellite

Run:

```bash
python project_map_viewer.py
```

Or open directly with a file:

```bash
python project_map_viewer.py path/to/project.json
```

## Requirements

- Python 3.10+
- Tkinter
- Pillow
- navpy
- tkintermapview

Install:

```bash
pip install pillow navpy tkintermapview
```

## Run Main App

```bash
python app.py
```
