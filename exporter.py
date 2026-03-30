
import csv
import json
import math
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
import navpy
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_COLUMNS = [
    "id",
    "drone_lat_deg",
    "drone_lon_deg",
    "drone_alt_m",
    "heading_deg",
]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_rows(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        if isinstance(data.get("exports"), list):
            return data["exports"]
        if isinstance(data.get("annotations"), list):
            return data["annotations"]
    if isinstance(data, list):
        return data
    raise ValueError("Could not find a list of rows. Expected 'exports' in the JSON.")


def normalize_row(row: Dict[str, Any], columns: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for col in columns:
        out[col] = row.get(col, "")
    return out


def rotated_site_from_plan_local(east_m: float, north_m: float, azimuth_deg: Optional[float]) -> Tuple[float, float]:
    if azimuth_deg is None:
        return (east_m, north_m)

    ey = (math.sin(math.radians(azimuth_deg)), math.cos(math.radians(azimuth_deg)))
    ax = azimuth_deg + 90.0
    ex = (math.sin(math.radians(ax)), math.cos(math.radians(ax)))
    site_e = east_m * ex[0] + north_m * ey[0]
    site_n = east_m * ex[1] + north_m * ey[1]
    return (site_e, site_n)


def lla_from_local_enu_navpy(
    lat0_deg: float,
    lon0_deg: float,
    alt0_m: float,
    east_m: float,
    north_m: float,
    up_m: float,
) -> Tuple[float, float, float]:
    # navpy works in NED, so convert ENU (east, north, up) -> NED (north, east, down).
    ned = [north_m, east_m, -up_m]
    lat, lon, alt = navpy.ned2lla(
        ned,
        lat0_deg,
        lon0_deg,
        alt0_m,
        latlon_unit="deg",
        alt_unit="m",
        model="wgs84",
    )
    return (float(lat), float(lon), float(alt))


def compute_drone_lla_from_annotation(row: Dict[str, Any], project: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    lat0 = project.get("georef_lat_deg")
    lon0 = project.get("georef_lon_deg")
    if lat0 is None or lon0 is None:
        return (None, None, None)

    local = row.get("drone_local_m")
    if not isinstance(local, dict):
        return (None, None, None)

    east = local.get("x")
    north = local.get("y")
    if east is None or north is None:
        return (None, None, None)

    az = project.get("plan_y_azimuth_deg_cw_from_north")
    site_e, site_n = rotated_site_from_plan_local(float(east), float(north), az)
    alt0 = float(project.get("georef_alt_m", 0.0) or 0.0)
    height = float(project.get("global_height_m", 0.0) or 0.0)
    return lla_from_local_enu_navpy(float(lat0), float(lon0), alt0, site_e, site_n, height)


def simple_row(row: Dict[str, Any], project: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    lat = row.get("drone_lat_deg", row.get("drone_lat", ""))
    lon = row.get("drone_lon_deg", row.get("drone_lon", ""))
    alt = row.get("drone_alt_m", row.get("drone_alt", ""))

    if (lat in ("", None) or lon in ("", None) or alt in ("", None)) and project:
        c_lat, c_lon, c_alt = compute_drone_lla_from_annotation(row, project)
        if c_lat is not None and c_lon is not None and c_alt is not None:
            lat, lon, alt = c_lat, c_lon, c_alt

    return {
        "id": row.get("id", row.get("ann_id", "")),
        "drone_lat_deg": lat,
        "drone_lon_deg": lon,
        "drone_alt_m": alt,
        "heading_deg": row.get("heading_deg_cw_from_north", row.get("heading_deg", row.get("heading", ""))),
    }


def convert_json_to_csv(json_path: Path, csv_path: Path, columns: Optional[List[str]] = None) -> None:
    data = load_json(json_path)
    rows = get_rows(data)
    if not rows:
        raise ValueError("No rows found in JSON.")

    if columns is None:
        columns = DEFAULT_COLUMNS

    project = data if isinstance(data, dict) else None
    normalized = [normalize_row(simple_row(r, project), columns) for r in rows]

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(normalized)


def pick_paths_with_tk() -> Tuple[Optional[Path], Optional[Path]]:
    root = tk.Tk()
    root.withdraw()
    root.update()

    in_path = filedialog.askopenfilename(
        title="Select input JSON",
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
    )
    if not in_path:
        root.destroy()
        return (None, None)

    json_path = Path(in_path).expanduser().resolve()
    default_out = json_path.with_name(json_path.stem + "_lla_heading.csv")
    out_path = filedialog.asksaveasfilename(
        title="Save output CSV as",
        defaultextension=".csv",
        initialfile=default_out.name,
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
    )
    root.destroy()

    if not out_path:
        return (None, None)

    return (json_path, Path(out_path).expanduser().resolve())


def main() -> None:
    if len(sys.argv) < 2:
        json_path, csv_path = pick_paths_with_tk()
        if json_path is None or csv_path is None:
            print("No file selected. Cancelled.")
            sys.exit(0)
    else:
        json_path = Path(sys.argv[1]).expanduser().resolve()
        if not json_path.exists():
            print(f"Input not found: {json_path}")
            sys.exit(2)

        if len(sys.argv) >= 3:
            csv_path = Path(sys.argv[2]).expanduser().resolve()
        else:
            csv_path = json_path.with_name(json_path.stem + "_lla_heading.csv")

    try:
        convert_json_to_csv(json_path, csv_path)
    except Exception as e:
        print(f"Conversion failed: {e}")
        sys.exit(3)

    print(f"Wrote: {csv_path}")


if __name__ == "__main__":
    main()
