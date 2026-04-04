# Drone Floor Plan Annotator

Desktop Tkinter app to annotate windows on a floor-plan image and compute drone capture points, heading, and optional georeferenced outputs.

## Features

- Load floor-plan images (`png`, `jpg`, `jpeg`, `bmp`, `tif`, `tiff`, `webp`)
- Set plan origin
- Calibrate X and Y scale from known real distances
- Add window annotations with 3 clicks:
  1. window endpoint 1
  2. window endpoint 2
  3. side selector click (which side the drone should stand off)
- Two drone distance modes:
  - `auto`: computed from HFOV + fill ratio
  - `manual`: fixed user-entered distance (`Manual dist m`)
- Real-time update of existing annotations when you click `Apply Settings`
- Save/load project JSON
- Export CSV and verbose JSON
- Export marked plan image with drone positions overlaid
- View drone points on map from project JSON (`project_map_viewer.py`)

## Coordinate Model

After origin is set:

- image `x`: positive to the right
- image `y`: positive downward
- local `east`: positive to the right
- local `north`: positive upward

Conversion:

- `east_m = (px_x - origin_x) * meters_per_pixel`
- `north_m = -(px_y - origin_y) * meters_per_pixel`

## Drone Distance (Standoff)

### Auto Mode

Formula:

```text
d_m = W_m / (2 * tan(HFOV / 2) * fill_ratio)
```

Where:

- `W_m` is window width in meters
- `HFOV` is horizontal field of view in degrees
- `fill_ratio` is desired frame occupancy ratio (0 < ratio <= 1)

### Manual Mode

- Set `Dist mode` to `manual`
- Enter `Manual dist m`
- Click `Apply Settings`
- Manual distance overrides auto formula (HFOV/fill are ignored for standoff)

## Real-Time Settings Apply

When you click `Apply Settings`, the app recalculates existing annotations immediately (no reload needed) using the current settings and distance mode.

## Annotation IDs and Labels

- New annotations are sequentially numbered (`W1`, `W2`, ...)
- Preview rendering does not consume IDs
- IDs are re-numbered sequentially when loading a project and after deletions

## Georeferencing

If georef fields are set:

- origin latitude/longitude/altitude
- plan `+Y` azimuth clockwise from true north

the app converts local EN coordinates to LLA using `navpy`.

## Save vs Export

### Save Project

- Saves editable project state
- Saved under `output/project/json`
- Includes annotation geometry and current settings

### Export JSON

- Verbose structure with:
  - `project` (full project payload)
  - `exports` (flat per-annotation rows)

### Export CSV

- Flat per-annotation table for spreadsheets/scripting

### Export Marked Plan Image

- Exports plan image with drone positions, guide lines, and labels drawn
- Menu: `File -> Export Marked Plan Image...`

## Controls

### Tools

- `Select`: select annotation
- `Pan`: tool mode (mouse pan is still middle/right drag)
- `Origin`: set origin point
- `Cal X`: set X calibration
- `Cal Y`: set Y calibration
- `Window`: add window annotation

### Mouse

- Mouse wheel: zoom
- Middle drag or right drag: pan
- Left click: active tool action

### Keyboard

- `Esc`: switch to `Select` and clear temp tool state
- `Ctrl+S`: save project
- `Ctrl+Z`: undo
- `Ctrl+Y`: redo

## Output Folders

- `output/project/json`: project saves + JSON exports
- `output/project/csv`: CSV exports
- `output/project/images`: marked plan image exports

`exporter.py` also writes output CSV into `output/project/csv`.

## Utility Scripts

### Project Map Viewer

`project_map_viewer.py` loads project JSON and plots drone points on a map.

Run:

```bash
python project_map_viewer.py
```

Or with file:

```bash
python project_map_viewer.py path/to/project.json
```

### JSON to compact CSV exporter

`exporter.py` converts saved/exported JSON to a compact CSV with:

- `id`
- `drone_lat_deg`
- `drone_lon_deg`
- `drone_alt_m`
- `heading_deg`

Run:

```bash
python exporter.py
```

Or:

```bash
python exporter.py path/to/input.json output_name.csv
```

## Requirements

- Python 3.10+
- Tkinter
- Dependencies in `requirements.txt`

Install:

```bash
pip install -r requirements.txt
```

## Run Main App

```bash
python app.py
```
