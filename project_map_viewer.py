from __future__ import annotations

import json
import math
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Any, Dict, Optional, Tuple

import navpy
from tkintermapview import TkinterMapView


MAP_TILE_SERVERS = {
    "Google normal": ("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga", 22),
    "Google satellite": ("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga", 22),
}


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


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def _project_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(data.get("project"), dict):
        return data["project"]
    return data


def compute_drone_lla(annotation: Dict[str, Any], project: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    # Prefer explicit LLA fields if present.
    lat = _to_float(annotation.get("drone_lat_deg"))
    lon = _to_float(annotation.get("drone_lon_deg"))
    alt = _to_float(annotation.get("drone_alt_m"))
    if lat is not None and lon is not None and alt is not None:
        return (lat, lon, alt)

    # Fallback to local coordinate conversion.
    lat0 = _to_float(project.get("georef_lat_deg"))
    lon0 = _to_float(project.get("georef_lon_deg"))
    if lat0 is None or lon0 is None:
        return (None, None, None)

    local = annotation.get("drone_local_m")
    if not isinstance(local, dict):
        return (None, None, None)

    east = _to_float(local.get("x"))
    north = _to_float(local.get("y"))
    if east is None or north is None:
        return (None, None, None)

    az = _to_float(project.get("plan_y_azimuth_deg_cw_from_north"))
    site_e, site_n = rotated_site_from_plan_local(east, north, az)

    alt0 = _to_float(project.get("georef_alt_m"))
    if alt0 is None:
        alt0 = 0.0
    height = _to_float(project.get("global_height_m"))
    if height is None:
        height = 0.0

    return lla_from_local_enu_navpy(lat0, lon0, alt0, site_e, site_n, height)


def heading_for_annotation(annotation: Dict[str, Any]) -> Optional[float]:
    for k in ("heading_deg", "heading_deg_cw_from_north", "heading"):
        h = _to_float(annotation.get(k))
        if h is not None:
            return h
    return None


class ProjectMapViewer(tk.Tk):
    def __init__(self, initial_project: Optional[Path] = None):
        super().__init__()
        self.title("Project Drone LLA Viewer")
        self.geometry("1200x760")
        self.minsize(960, 620)

        self.project_path: Optional[Path] = None
        self.markers = []

        self.style_var = tk.StringVar(value="Google normal")
        self.status_var = tk.StringVar(value="Load a project JSON to begin.")

        self._build_ui()
        self._apply_map_style(self.style_var.get())

        if initial_project is not None:
            self.load_project_file(initial_project)

    def _build_ui(self) -> None:
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x", padx=8, pady=8)

        ttk.Button(top, text="Open Project JSON", command=self.open_project_dialog).pack(side="left")

        ttk.Label(top, text="Map style").pack(side="left", padx=(12, 4))
        ttk.OptionMenu(top, self.style_var, "Google normal", *MAP_TILE_SERVERS.keys(), command=self._apply_map_style).pack(side="left")

        self.path_var = tk.StringVar(value="(no file loaded)")
        ttk.Label(top, textvariable=self.path_var).pack(side="left", padx=(12, 0))

        body = ttk.Panedwindow(root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(body, width=360)
        right = ttk.Frame(body)
        body.add(left, weight=0)
        body.add(right, weight=1)

        cols = ("id", "lat", "lon", "alt", "heading")
        self.table = ttk.Treeview(left, columns=cols, show="headings", height=20)
        for c, w in (("id", 72), ("lat", 90), ("lon", 90), ("alt", 70), ("heading", 70)):
            self.table.heading(c, text=c)
            self.table.column(c, width=w, anchor="e")
        self.table.pack(fill="both", expand=True)

        self.map_widget = TkinterMapView(right, corner_radius=0)
        self.map_widget.pack(fill="both", expand=True)

        status = ttk.Label(root, textvariable=self.status_var, anchor="w")
        status.pack(fill="x", padx=8, pady=(0, 8))

    def _apply_map_style(self, style: Any = None) -> None:
        style_name = str(style) if style is not None else self.style_var.get()
        cfg = MAP_TILE_SERVERS.get(style_name)
        if not cfg:
            return
        url, max_zoom = cfg
        self.map_widget.set_tile_server(url, max_zoom=max_zoom)

    def open_project_dialog(self) -> None:
        path = filedialog.askopenfilename(
            title="Open project JSON",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        self.load_project_file(Path(path))

    def _clear_markers(self) -> None:
        for marker in self.markers:
            try:
                marker.delete()
            except Exception:
                pass
        self.markers.clear()

    def load_project_file(self, path: Path) -> None:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Open failed", str(e), parent=self)
            return

        project = _project_payload(data)
        anns = project.get("annotations")
        if not isinstance(anns, list):
            messagebox.showerror("Invalid JSON", "No annotations list found.", parent=self)
            return

        rows = []
        for ann in anns:
            if not isinstance(ann, dict):
                continue
            lat, lon, alt = compute_drone_lla(ann, project)
            hdg = heading_for_annotation(ann)
            if lat is None or lon is None:
                continue
            ann_id = ann.get("ann_id", ann.get("id", ""))
            rows.append((ann_id, lat, lon, alt if alt is not None else 0.0, hdg if hdg is not None else 0.0))

        if not rows:
            messagebox.showwarning(
                "No plottable points",
                "No drone LLA points found/computed. Ensure georef values and drone_local_m are present.",
                parent=self,
            )
            return

        self._clear_markers()
        self.table.delete(*self.table.get_children())

        for ann_id, lat, lon, alt, hdg in rows:
            label = f"{ann_id} | hdg={hdg:.1f}"
            self.markers.append(self.map_widget.set_marker(lat, lon, text=label))
            self.table.insert(
                "",
                "end",
                values=(
                    ann_id,
                    f"{lat:.7f}",
                    f"{lon:.7f}",
                    f"{alt:.2f}",
                    f"{hdg:.1f}",
                ),
            )

        first = rows[0]
        self.map_widget.set_position(first[1], first[2])
        self.map_widget.set_zoom(18)

        self.project_path = path
        self.path_var.set(str(path))
        self.status_var.set(f"Loaded {len(rows)} drone points from {path.name}")


def main() -> None:
    initial_path: Optional[Path] = None
    if len(sys.argv) >= 2:
        p = Path(sys.argv[1]).expanduser().resolve()
        if p.exists():
            initial_path = p

    app = ProjectMapViewer(initial_project=initial_path)
    app.mainloop()


if __name__ == "__main__":
    main()
