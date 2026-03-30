from __future__ import annotations

from pathlib import Path




import csv
import json
import math
import os
import copy
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Tuple, Dict, Any, Sequence, TypeAlias

from PIL import Image, ImageTk
from tkintermapview import TkinterMapView
import navpy
import tkintermapview


APP_TITLE = "Drone Floor Plan Annotator"
PROJECT_VERSION = 1
Vec2: TypeAlias = Tuple[float, float]


# ----------------------------- math helpers ----------------------------- #

def clamp_angle_360(deg: float) -> float:
    deg %= 360.0
    return deg if deg >= 0 else deg + 360.0


def v_add(a: Vec2, b: Vec2) -> Vec2: return (a[0] + b[0], a[1] + b[1])
def v_sub(a: Vec2, b: Vec2) -> Vec2: return (a[0] - b[0], a[1] - b[1])
def v_mul(a: Vec2, s: float) -> Vec2: return (a[0] * s, a[1] * s)
def v_dot(a: Vec2, b: Vec2) -> float: return a[0] * b[0] + a[1] * b[1]
def v_len(a: Vec2) -> float: return math.hypot(a[0], a[1])


def v_norm(a: Vec2) -> Vec2:
    L = v_len(a)
    if L <= 1e-12:
        return (0.0, 0.0)
    return (a[0] / L, a[1] / L)


def v_mid(a: Vec2, b: Vec2) -> Vec2:
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)


def rotate_deg_ccw(x: float, y: float, deg: float) -> Vec2:
    r = math.radians(deg)
    c = math.cos(r)
    s = math.sin(r)
    return (c * x - s * y, s * x + c * y)


def heading_cw_from_north(from_xy: Vec2, to_xy: Vec2) -> float:
    dx = to_xy[0] - from_xy[0]
    dy = to_xy[1] - from_xy[1]
    return clamp_angle_360(math.degrees(math.atan2(dx, dy)))


def signed_side_of_perp_line(p1: Vec2, p2: Vec2, click: Vec2) -> float:
    """
    Window endpoints p1,p2 define midpoint m and perpendicular axis n=(-uy, ux).
    Returns signed distance-like scalar relative to the midpoint-perpendicular line.
    """
    m = v_mid(p1, p2)
    u = v_norm(v_sub(p2, p1))
    n = (-u[1], u[0])
    return v_dot(v_sub(click, m), n)


def line_angle_deg(p1: Vec2, p2: Vec2) -> float:
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    return math.degrees(math.atan2(dy, dx))


def local_from_pixel(pixel_xy: Vec2, origin_px: Vec2, m_per_px: float) -> Vec2:
    """
    pixel x right positive
    pixel y down positive
    local east = +x right
    local north = +y up, so flip sign on image y
    """
    dx_px = pixel_xy[0] - origin_px[0]
    dy_px = pixel_xy[1] - origin_px[1]
    east_m = dx_px * m_per_px
    north_m = -dy_px * m_per_px
    return (east_m, north_m)


def lla_from_local_enu_approx(
    lat0_deg: float,
    lon0_deg: float,
    alt0_m: float,
    east_m: float,
    north_m: float,
    up_m: float,
) -> Tuple[float, float, float]:
    """
    Convert local ENU to LLA.
    Uses navpy when available, otherwise falls back to a local tangent approximation.
    """
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




# ----------------------------- data model ----------------------------- #

@dataclass
class Point2:
    x: float
    y: float

    @classmethod
    def from_tuple(cls, p: Sequence[float]) -> "Point2":
        return cls(float(p[0]), float(p[1]))

    def tup(self) -> Vec2:
        return (self.x, self.y)


@dataclass
class Calibration:
    p1: Optional[Point2] = None
    p2: Optional[Point2] = None
    known_length_m: Optional[float] = None

    def length_px(self) -> Optional[float]:
        if not self.p1 or not self.p2:
            return None
        return v_len(v_sub(self.p2.tup(), self.p1.tup()))

    def m_per_px(self) -> Optional[float]:
        L = self.length_px()
        if L and self.known_length_m and self.known_length_m > 0:
            return self.known_length_m / L
        return None


@dataclass
class WindowAnnotation:
    ann_id: int
    label: str
    p1_px: Point2
    p2_px: Point2
    side_sign: int
    midpoint_px: Point2
    window_width_px: float
    window_width_m: float
    standoff_m: float
    drone_px: Point2
    midpoint_local_m: Point2
    drone_local_m: Point2
    heading_deg: float
    notes: str = ""

    def to_export_row(self, project: "Project") -> Dict[str, Any]:
        row = {
            "id": self.ann_id,
            "label": self.label,
            "p1_px_x": self.p1_px.x,
            "p1_px_y": self.p1_px.y,
            "p2_px_x": self.p2_px.x,
            "p2_px_y": self.p2_px.y,
            "mid_px_x": self.midpoint_px.x,
            "mid_px_y": self.midpoint_px.y,
            "drone_px_x": self.drone_px.x,
            "drone_px_y": self.drone_px.y,
            "side_sign": self.side_sign,
            "window_width_px": self.window_width_px,
            "window_width_m": self.window_width_m,
            "standoff_m": self.standoff_m,
            "mid_east_m": self.midpoint_local_m.x,
            "mid_north_m": self.midpoint_local_m.y,
            "drone_east_m": self.drone_local_m.x,
            "drone_north_m": self.drone_local_m.y,
            "height_m": project.global_height_m,
            "heading_deg_cw_from_north": self.heading_deg,
            "notes": self.notes,
        }

        if project.has_georef():
            lat, lon, alt = project.drone_lla_for(self)
            mlat, mlon, malt = project.mid_lla_for(self)
            row.update({
                "mid_lat_deg": mlat,
                "mid_lon_deg": mlon,
                "mid_alt_m": malt,
                "drone_lat_deg": lat,
                "drone_lon_deg": lon,
                "drone_alt_m": alt,
            })
        return row

    def to_annotation_json_row(self, project: "Project") -> Dict[str, Any]:
        row = asdict(self)
        if project.has_georef():
            lat, lon, alt = project.drone_lla_for(self)
            row.update({
                "drone_lat_deg": lat,
                "drone_lon_deg": lon,
                "drone_alt_m": alt,
            })
        return row


@dataclass
class Project:
    version: int = PROJECT_VERSION
    image_path: str = ""
    image_width: int = 0
    image_height: int = 0

    origin_px: Optional[Point2] = None
    x_cal: Calibration = field(default_factory=Calibration)
    y_cal: Calibration = field(default_factory=Calibration)

    camera_hfov_deg: float = 90.0
    frame_fill_ratio: float = 0.70
    global_height_m: float = 3.0

    georef_lat_deg: Optional[float] = None
    georef_lon_deg: Optional[float] = None
    georef_alt_m: float = 0.0
    plan_y_azimuth_deg_cw_from_north: Optional[float] = None

    next_ann_id: int = 1
    annotations: List[WindowAnnotation] = field(default_factory=list)

    ui_notes: str = ""

    def x_m_per_px(self) -> Optional[float]:
        return self.x_cal.m_per_px()

    def y_m_per_px(self) -> Optional[float]:
        return self.y_cal.m_per_px()

    def avg_m_per_px(self) -> Optional[float]:
        xs = self.x_m_per_px()
        ys = self.y_m_per_px()
        vals = [v for v in (xs, ys) if v is not None]
        return sum(vals) / len(vals) if vals else None

    def scale_mismatch_ratio(self) -> Optional[float]:
        xs = self.x_m_per_px()
        ys = self.y_m_per_px()
        if xs is None or ys is None or xs == 0:
            return None
        return abs(xs - ys) / xs

    def has_scale(self) -> bool:
        return self.avg_m_per_px() is not None

    def has_georef(self) -> bool:
        return (
            self.georef_lat_deg is not None and
            self.georef_lon_deg is not None and
            self.plan_y_azimuth_deg_cw_from_north is not None
        )

    def export_ready(self) -> Tuple[bool, List[str]]:
        errs = []
        if not self.image_path:
            errs.append("No image loaded.")
        if not self.origin_px:
            errs.append("Origin not set.")
        if self.x_cal.m_per_px() is None:
            errs.append("X calibration incomplete.")
        if self.y_cal.m_per_px() is None:
            errs.append("Y calibration incomplete.")
        if self.global_height_m is None:
            errs.append("Global height not set.")
        if self.frame_fill_ratio <= 0 or self.frame_fill_ratio > 1:
            errs.append("Frame fill ratio must be > 0 and <= 1.")
        if self.camera_hfov_deg <= 0 or self.camera_hfov_deg >= 180:
            errs.append("HFOV must be between 0 and 180.")
        if not self.annotations:
            errs.append("No window annotations.")
        return (len(errs) == 0, errs)

    def compute_window_annotation(self, p1: Vec2, p2: Vec2, side_click: Vec2, label: str = "") -> WindowAnnotation:
        m_per_px = self.avg_m_per_px()
        if m_per_px is None:
            raise ValueError("Scale is not calibrated.")

        if self.frame_fill_ratio <= 0:
            raise ValueError("Fill ratio must be > 0.")
        if self.camera_hfov_deg <= 0 or self.camera_hfov_deg >= 180:
            raise ValueError("HFOV must be in (0, 180).")

        win_vec = v_sub(p2, p1)
        width_px = v_len(win_vec)
        if width_px <= 1e-9:
            raise ValueError("Window line length is zero.")

        width_m = width_px * m_per_px
        half_angle = math.radians(self.camera_hfov_deg * 0.5)
        standoff_m = width_m / (2.0 * math.tan(half_angle) * self.frame_fill_ratio)
        standoff_px = standoff_m / m_per_px

        u = v_norm(win_vec)
        n = (-u[1], u[0])
        mid = v_mid(p1, p2)

        side_val = v_dot(v_sub(side_click, mid), n)
        if abs(side_val) <= 1e-12:
            raise ValueError("Side click lies on perpendicular line.")
        side_sign = 1 if side_val > 0 else -1

        drone_px = v_add(mid, v_mul(n, side_sign * standoff_px))

        if self.origin_px is None:
            raise ValueError("Origin is not set.")

        mid_local = local_from_pixel(mid, self.origin_px.tup(), m_per_px)
        drone_local = local_from_pixel(drone_px, self.origin_px.tup(), m_per_px)
        heading = heading_cw_from_north(drone_local, mid_local)

        ann = WindowAnnotation(
            ann_id=self.next_ann_id,
            label=label or f"W{self.next_ann_id}",
            p1_px=Point2.from_tuple(p1),
            p2_px=Point2.from_tuple(p2),
            side_sign=side_sign,
            midpoint_px=Point2.from_tuple(mid),
            window_width_px=width_px,
            window_width_m=width_m,
            standoff_m=standoff_m,
            drone_px=Point2.from_tuple(drone_px),
            midpoint_local_m=Point2.from_tuple(mid_local),
            drone_local_m=Point2.from_tuple(drone_local),
            heading_deg=heading,
        )
        self.next_ann_id += 1
        return ann

    def rotated_site_from_plan_local(self, east_m: float, north_m: float) -> Tuple[float, float]:
        """
        plan +Y azimuth clockwise from true north.
        Convert plan local east/north to site east/north.
        Equivalent:
            plan +Y basis azimuth = A
            plan +X basis azimuth = A + 90
        Practical rotation: rotate local vector by -A about origin in EN frame? No.
        Safer basis form:
            ex = unit vector of plan +X in EN
            ey = unit vector of plan +Y in EN
        """
        A = self.plan_y_azimuth_deg_cw_from_north
        if A is None:
            return (east_m, north_m)

        # azimuth cw from north to EN components:
        ey = (math.sin(math.radians(A)), math.cos(math.radians(A)))
        ax = clamp_angle_360(A + 90.0)
        ex = (math.sin(math.radians(ax)), math.cos(math.radians(ax)))

        site_e = east_m * ex[0] + north_m * ey[0]
        site_n = east_m * ex[1] + north_m * ey[1]
        return (site_e, site_n)

    def drone_lla_for(self, ann: WindowAnnotation):
        e, n = self.rotated_site_from_plan_local(ann.drone_local_m.x, ann.drone_local_m.y)
        if self.georef_lat_deg is None or self.georef_lon_deg is None:
            raise ValueError("Georeference origin is not set.")
        return lla_from_local_enu_approx(
            self.georef_lat_deg, self.georef_lon_deg, self.georef_alt_m,
            e, n, self.global_height_m
        )

    def mid_lla_for(self, ann: WindowAnnotation):
        e, n = self.rotated_site_from_plan_local(ann.midpoint_local_m.x, ann.midpoint_local_m.y)
        if self.georef_lat_deg is None or self.georef_lon_deg is None:
            raise ValueError("Georeference origin is not set.")

        return lla_from_local_enu_approx(
            self.georef_lat_deg, self.georef_lon_deg, self.georef_alt_m,
            e, n, 0.0
        )

    def to_json_obj(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json_obj(cls, obj: Dict[str, Any]) -> "Project":
        def p2(v):
            if v is None:
                return None
            return Point2(**v)

        def cal(v):
            out = Calibration()
            out.p1 = p2(v.get("p1"))
            out.p2 = p2(v.get("p2"))
            out.known_length_m = v.get("known_length_m")
            return out

        proj = Project()
        proj.version = obj.get("version", PROJECT_VERSION)
        proj.image_path = obj.get("image_path", "")
        proj.image_width = obj.get("image_width", 0)
        proj.image_height = obj.get("image_height", 0)
        proj.origin_px = p2(obj.get("origin_px"))
        proj.x_cal = cal(obj.get("x_cal", {}))
        proj.y_cal = cal(obj.get("y_cal", {}))
        proj.camera_hfov_deg = obj.get("camera_hfov_deg", 90.0)
        proj.frame_fill_ratio = obj.get("frame_fill_ratio", 0.70)
        proj.global_height_m = obj.get("global_height_m", 3.0)
        proj.georef_lat_deg = obj.get("georef_lat_deg")
        proj.georef_lon_deg = obj.get("georef_lon_deg")
        proj.georef_alt_m = obj.get("georef_alt_m", 0.0)
        proj.plan_y_azimuth_deg_cw_from_north = obj.get("plan_y_azimuth_deg_cw_from_north")
        proj.next_ann_id = obj.get("next_ann_id", 1)
        proj.ui_notes = obj.get("ui_notes", "")
        proj.annotations = []
        for a in obj.get("annotations", []):
            proj.annotations.append(WindowAnnotation(
                ann_id=a["ann_id"],
                label=a["label"],
                p1_px=Point2(**a["p1_px"]),
                p2_px=Point2(**a["p2_px"]),
                side_sign=a["side_sign"],
                midpoint_px=Point2(**a["midpoint_px"]),
                window_width_px=a["window_width_px"],
                window_width_m=a["window_width_m"],
                standoff_m=a["standoff_m"],
                drone_px=Point2(**a["drone_px"]),
                midpoint_local_m=Point2(**a["midpoint_local_m"]),
                drone_local_m=Point2(**a["drone_local_m"]),
                heading_deg=a["heading_deg"],
                notes=a.get("notes", ""),
            ))
        return proj


# ----------------------------- map popup ----------------------------- #

class MapOriginDialog(tk.Toplevel):
    def __init__(self, master, lat=None, lon=None):
        super().__init__(master)
        self.title("Map Origin Picker")
        self.geometry("900x600")
        self.result = None
        self.map_widget = None
        self.marker = None

        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=6)

        ttk.Label(top, text="Latitude").pack(side="left")
        self.lat_var = tk.StringVar(value="" if lat is None else str(lat))
        ttk.Entry(top, textvariable=self.lat_var, width=16).pack(side="left", padx=(4, 12))

        ttk.Label(top, text="Longitude").pack(side="left")
        self.lon_var = tk.StringVar(value="" if lon is None else str(lon))
        ttk.Entry(top, textvariable=self.lon_var, width=16).pack(side="left", padx=(4, 12))

        ttk.Button(top, text="Use typed coords", command=self.use_typed).pack(side="left")
        ttk.Button(top, text="Close", command=self.destroy).pack(side="right")

        if TkinterMapView is None:
            msg = (
                "tkintermapview is not installed.\n\n"
                "Install with:\n"
                "    pip install tkintermapview\n\n"
                "You can still type latitude/longitude manually."
            )
            ttk.Label(self, text=msg, justify="left").pack(fill="both", expand=True, padx=10, pady=10)
            return

        self.map_widget = TkinterMapView(self, corner_radius=0)
        self.map_widget.pack(fill="both", expand=True)
        try:
            self.map_widget.set_position(lat or 49.2827, lon or -123.1207)
            self.map_widget.set_zoom(18)
        except Exception:
            pass

        self.map_widget.add_left_click_map_command(self.on_map_click)

    def on_map_click(self, coords):
        lat, lon = coords
        self.lat_var.set(f"{lat:.8f}")
        self.lon_var.set(f"{lon:.8f}")
        try:
            if self.marker:
                self.marker.delete()
            if not self.map_widget:
                raise ValueError("Map widget is not available.")
            self.marker = self.map_widget.set_marker(lat, lon, text="Origin")
        except Exception:
            pass

    def use_typed(self):
        try:
            lat = float(self.lat_var.get().strip())
            lon = float(self.lon_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid", "Latitude/longitude must be numbers.", parent=self)
            return
        self.result = (lat, lon)
        self.destroy()


# ----------------------------- main app ----------------------------- #

class AnnotatorApp(tk.Tk):
    TOOL_SELECT = "select"
    TOOL_PAN = "pan"
    TOOL_ORIGIN = "origin"
    TOOL_CAL_X = "cal_x"
    TOOL_CAL_Y = "cal_y"
    TOOL_WINDOW = "window"

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1500x900")
        self.minsize(1100, 700)

        self.output_root = Path(__file__).resolve().parent / "output"
        self.project_output_dir = self.output_root / "project"
        self.project_json_output_dir = self.project_output_dir / "json"
        self.project_csv_output_dir = self.project_output_dir / "csv"
        self._ensure_output_dirs()

        self.project = Project()
        self.project_path: Optional[str] = None

        self.undo_stack: List[Dict[str, Any]] = []
        self.redo_stack: List[Dict[str, Any]] = []

        self.tool_var = tk.StringVar(value=self.TOOL_SELECT)
        self.status_var = tk.StringVar(value="Ready.")

        self.image_pil: Optional[Image.Image] = None
        self.image_tk = None
        self.canvas_image_id = None

        self.view_scale = 1.0
        self.view_off_x = 40.0
        self.view_off_y = 40.0

        self.dragging_pan = False
        self.pan_last = (0, 0)

        self.temp_points: List[Tuple[float, float]] = []
        self.temp_preview_ids: List[int] = []

        self.selected_ann_id: Optional[int] = None
        self.hover_canvas_px = None

        self._build_ui()
        self._bind_canvas()
        self.refresh_all()

    def _ensure_output_dirs(self) -> None:
        self.project_json_output_dir.mkdir(parents=True, exist_ok=True)
        self.project_csv_output_dir.mkdir(parents=True, exist_ok=True)

    def _project_save_path(self) -> str:
        return str(self.project_json_output_dir / self._default_project_filename())

    def _default_project_filename(self) -> str:
        if self.project_path:
            return Path(self.project_path).name
        if self.project.image_path:
            return f"{Path(self.project.image_path).stem}_project.json"
        return "project.json"

    def _default_export_stem(self) -> str:
        if self.project_path:
            return Path(self.project_path).stem
        if self.project.image_path:
            return Path(self.project.image_path).stem
        return "export"

    # ---------- UI ---------- #

    def _build_ui(self):
        self._build_menu()

        root = ttk.Frame(self)
        root.pack(fill="both", expand=True)

        toolbar = ttk.Frame(root)
        toolbar.pack(fill="x", padx=4, pady=4)

        self._tb_btn(toolbar, "Select", self.TOOL_SELECT)
        self._tb_btn(toolbar, "Pan", self.TOOL_PAN)
        self._tb_btn(toolbar, "Origin", self.TOOL_ORIGIN)
        self._tb_btn(toolbar, "Cal X", self.TOOL_CAL_X)
        self._tb_btn(toolbar, "Cal Y", self.TOOL_CAL_Y)
        self._tb_btn(toolbar, "Window", self.TOOL_WINDOW)

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(toolbar, text="Undo", command=self.undo).pack(side="left")
        ttk.Button(toolbar, text="Redo", command=self.redo).pack(side="left", padx=(4, 0))
        ttk.Button(toolbar, text="Delete", command=self.delete_selected).pack(side="left", padx=(8, 0))
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(toolbar, text="Fit", command=self.fit_image).pack(side="left")
        ttk.Button(toolbar, text="Zoom +", command=lambda: self.zoom_at_canvas_center(1.2)).pack(side="left", padx=(4, 0))
        ttk.Button(toolbar, text="Zoom -", command=lambda: self.zoom_at_canvas_center(1/1.2)).pack(side="left", padx=(4, 0))

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, width=320)
        left.pack(side="left", fill="y", padx=(4, 2), pady=4)
        left.pack_propagate(False)

        center = ttk.Frame(body)
        center.pack(side="left", fill="both", expand=True, padx=2, pady=4)

        self.canvas = tk.Canvas(center, bg="#1e1e1e", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        status = ttk.Label(root, textvariable=self.status_var, anchor="w")
        status.pack(fill="x", padx=4, pady=(0, 4))

        # left panel content
        lf = ttk.LabelFrame(left, text="Project")
        lf.pack(fill="x", padx=4, pady=4)

        self.image_path_var = tk.StringVar()
        ttk.Label(lf, textvariable=self.image_path_var, wraplength=280).pack(anchor="w", padx=6, pady=4)

        ttk.Button(lf, text="Load Image", command=self.load_image_dialog).pack(fill="x", padx=6, pady=2)
        ttk.Button(lf, text="Map Origin", command=self.open_map_origin_dialog).pack(fill="x", padx=6, pady=2)

        sf = ttk.LabelFrame(left, text="Settings")
        sf.pack(fill="x", padx=4, pady=4)

        self.hfov_var = tk.StringVar(value=str(self.project.camera_hfov_deg))
        self.fill_var = tk.StringVar(value=str(self.project.frame_fill_ratio))
        self.height_var = tk.StringVar(value=str(self.project.global_height_m))
        self.lat_var = tk.StringVar()
        self.lon_var = tk.StringVar()
        self.alt_var = tk.StringVar(value=str(self.project.georef_alt_m))
        self.az_var = tk.StringVar()

        self._labeled_entry(sf, "HFOV deg", self.hfov_var)
        self._labeled_entry(sf, "Fill ratio", self.fill_var)
        self._labeled_entry(sf, "Height m", self.height_var)
        ttk.Separator(sf).pack(fill="x", padx=6, pady=4)
        self._labeled_entry(sf, "Origin lat", self.lat_var)
        self._labeled_entry(sf, "Origin lon", self.lon_var)
        self._labeled_entry(sf, "Origin alt m", self.alt_var)
        self._labeled_entry(sf, "Plan +Y azimuth", self.az_var)

        ttk.Button(sf, text="Apply Settings", command=self.apply_settings_from_ui).pack(fill="x", padx=6, pady=6)

        vf = ttk.LabelFrame(left, text="Validation / Scale")
        vf.pack(fill="x", padx=4, pady=4)

        self.validation_text = tk.Text(vf, height=12, wrap="word")
        self.validation_text.pack(fill="x", padx=6, pady=6)
        self.validation_text.configure(state="disabled")

        af = ttk.LabelFrame(left, text="Annotations")
        af.pack(fill="both", expand=True, padx=4, pady=4)

        self.ann_list = tk.Listbox(af)
        self.ann_list.pack(fill="both", expand=True, padx=6, pady=6)
        self.ann_list.bind("<<ListboxSelect>>", self.on_list_select)

    def _build_menu(self):
        menubar = tk.Menu(self)

        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="New Project", command=self.new_project)
        m_file.add_command(label="Open Project...", command=self.open_project_dialog)
        m_file.add_command(label="Save Project", command=self.save_project)
        m_file.add_command(label="Save Project As...", command=self.save_project_as)
        m_file.add_separator()
        m_file.add_command(label="Load Image...", command=self.load_image_dialog)
        m_file.add_separator()
        m_file.add_command(label="Export CSV...", command=self.export_csv)
        m_file.add_command(label="Export JSON...", command=self.export_json)
        m_file.add_separator()
        m_file.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=m_file)

        m_edit = tk.Menu(menubar, tearoff=0)
        m_edit.add_command(label="Undo", command=self.undo)
        m_edit.add_command(label="Redo", command=self.redo)
        m_edit.add_command(label="Delete Selected", command=self.delete_selected)
        menubar.add_cascade(label="Edit", menu=m_edit)

        m_view = tk.Menu(menubar, tearoff=0)
        m_view.add_command(label="Fit Image", command=self.fit_image)
        m_view.add_command(label="Zoom In", command=lambda: self.zoom_at_canvas_center(1.2))
        m_view.add_command(label="Zoom Out", command=lambda: self.zoom_at_canvas_center(1/1.2))
        menubar.add_cascade(label="View", menu=m_view)

        m_tools = tk.Menu(menubar, tearoff=0)
        m_tools.add_command(label="Select", command=lambda: self.set_tool(self.TOOL_SELECT))
        m_tools.add_command(label="Pan", command=lambda: self.set_tool(self.TOOL_PAN))
        m_tools.add_command(label="Set Origin", command=lambda: self.set_tool(self.TOOL_ORIGIN))
        m_tools.add_command(label="Calibrate X", command=lambda: self.set_tool(self.TOOL_CAL_X))
        m_tools.add_command(label="Calibrate Y", command=lambda: self.set_tool(self.TOOL_CAL_Y))
        m_tools.add_command(label="Add Window", command=lambda: self.set_tool(self.TOOL_WINDOW))
        m_tools.add_command(label="Map Origin", command=self.open_map_origin_dialog)
        menubar.add_cascade(label="Tools", menu=m_tools)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="Validation Status", command=self.show_validation_popup)
        m_help.add_command(label="About", command=lambda: messagebox.showinfo("About", APP_TITLE))
        menubar.add_cascade(label="Help", menu=m_help)

        self.config(menu=menubar)

    def _tb_btn(self, parent, text, tool):
        ttk.Radiobutton(parent, text=text, variable=self.tool_var, value=tool,
                        command=self._on_tool_button).pack(side="left")

    def _on_tool_button(self):
        self.set_tool(self.tool_var.get())

    def _labeled_entry(self, parent, label, var):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text=label, width=16).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)

    # ---------- canvas transforms ---------- #

    def image_to_canvas(self, p: Vec2) -> Vec2:
        return (p[0] * self.view_scale + self.view_off_x,
                p[1] * self.view_scale + self.view_off_y)

    def canvas_to_image(self, p: Vec2) -> Vec2:
        return ((p[0] - self.view_off_x) / self.view_scale,
                (p[1] - self.view_off_y) / self.view_scale)

    def zoom_at(self, canvas_xy: Vec2, factor: float) -> None:
        old_img = self.canvas_to_image(canvas_xy)
        self.view_scale *= factor
        self.view_scale = max(0.05, min(40.0, self.view_scale))
        self.view_off_x = canvas_xy[0] - old_img[0] * self.view_scale
        self.view_off_y = canvas_xy[1] - old_img[1] * self.view_scale
        self.refresh_canvas()

    def zoom_at_canvas_center(self, factor):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        self.zoom_at((w * 0.5, h * 0.5), factor)

    def fit_image(self):
        if not self.image_pil:
            return
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        iw, ih = self.image_pil.size
        self.view_scale = min(cw / iw, ch / ih) * 0.95
        self.view_off_x = (cw - iw * self.view_scale) * 0.5
        self.view_off_y = (ch - ih * self.view_scale) * 0.5
        self.refresh_canvas()

    # ---------- state / undo ---------- #

    def snapshot(self):
        self.undo_stack.append(copy.deepcopy(self.project.to_json_obj()))
        if len(self.undo_stack) > 200:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(copy.deepcopy(self.project.to_json_obj()))
        state = self.undo_stack.pop()
        self.project = Project.from_json_obj(state)
        self.after_project_change()

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(copy.deepcopy(self.project.to_json_obj()))
        state = self.redo_stack.pop()
        self.project = Project.from_json_obj(state)
        self.after_project_change()

    def after_project_change(self):
        if self.project.image_path and os.path.exists(self.project.image_path):
            self.load_image_file(self.project.image_path, push_undo=False, keep_project_image_meta=True)
        else:
            self.image_pil = None
            self.image_tk = None
        self.refresh_all()

    # ---------- model sync ---------- #

    def apply_settings_from_ui(self):
        try:
            self.project.camera_hfov_deg = float(self.hfov_var.get().strip())
            self.project.frame_fill_ratio = float(self.fill_var.get().strip())
            self.project.global_height_m = float(self.height_var.get().strip())

            lat_s = self.lat_var.get().strip()
            lon_s = self.lon_var.get().strip()
            az_s = self.az_var.get().strip()
            alt_s = self.alt_var.get().strip()

            self.project.georef_lat_deg = float(lat_s) if lat_s else None
            self.project.georef_lon_deg = float(lon_s) if lon_s else None
            self.project.georef_alt_m = float(alt_s) if alt_s else 0.0
            self.project.plan_y_azimuth_deg_cw_from_north = float(az_s) if az_s else None
        except ValueError:
            messagebox.showerror("Invalid", "One or more settings are not valid numbers.")
            return

        self.refresh_all()

    def sync_ui_from_project(self):
        self.image_path_var.set(self.project.image_path or "(no image)")
        self.hfov_var.set(str(self.project.camera_hfov_deg))
        self.fill_var.set(str(self.project.frame_fill_ratio))
        self.height_var.set(str(self.project.global_height_m))
        self.lat_var.set("" if self.project.georef_lat_deg is None else str(self.project.georef_lat_deg))
        self.lon_var.set("" if self.project.georef_lon_deg is None else str(self.project.georef_lon_deg))
        self.alt_var.set(str(self.project.georef_alt_m))
        self.az_var.set("" if self.project.plan_y_azimuth_deg_cw_from_north is None else str(self.project.plan_y_azimuth_deg_cw_from_north))

    # ---------- file ops ---------- #

    def new_project(self):
        self.project = Project()
        self.project_path = None
        self.image_pil = None
        self.image_tk = None
        self.canvas_image_id = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.temp_points.clear()
        self.selected_ann_id = None
        self.refresh_all()

    def load_image_dialog(self):
        path = filedialog.askopenfilename(
            title="Load floor plan image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"), ("All files", "*.*")]
        )
        if path:
            self.load_image_file(path)

    def load_image_file(self, path, push_undo=True, keep_project_image_meta=False):
        try:
            img = Image.open(path).convert("RGBA")
        except Exception as e:
            messagebox.showerror("Image Load Failed", str(e))
            return

        if push_undo:
            self.snapshot()

        self.image_pil = img
        self.project.image_path = path
        if not keep_project_image_meta:
            self.project.image_width, self.project.image_height = img.size
        self.sync_ui_from_project()
        self.fit_image()
        self.refresh_all()

    def open_project_dialog(self):
        path = filedialog.askopenfilename(
            title="Open project JSON",
            initialdir=str(self.project_json_output_dir),
            filetypes=[("JSON", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            self.project = Project.from_json_obj(obj)
            self.project_path = path
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.after_project_change()
        except Exception as e:
            messagebox.showerror("Open failed", str(e))

    def save_project(self):
        if not self.project_path:
            self.project_path = self._project_save_path()
        self.apply_settings_from_ui()
        try:
            project_obj = self.project.to_json_obj()
            project_obj["annotations"] = [ann.to_annotation_json_row(self.project) for ann in self.project.annotations]
            # Keep all project saves in output/project/json regardless of where a project was opened from.
            self.project_path = str(self.project_json_output_dir / Path(self.project_path).name)
            Path(self.project_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.project_path, "w", encoding="utf-8") as f:
                json.dump(project_obj, f, indent=2)
            self.status(f"Project saved: {self.project_path}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def save_project_as(self):
        self.apply_settings_from_ui()
        path = filedialog.asksaveasfilename(
            title="Save project",
            defaultextension=".json",
            initialdir=str(self.project_json_output_dir),
            initialfile=self._default_project_filename(),
            filetypes=[("JSON", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return
        # Save As still chooses file name, but path is normalized to output/project/json.
        self.project_path = str(self.project_json_output_dir / Path(path).name)
        self.save_project()

    def export_json(self):
        self.apply_settings_from_ui()
        ok, errs = self.project.export_ready()
        if not ok:
            messagebox.showerror("Export blocked", "\n".join(errs))
            return

        path = filedialog.asksaveasfilename(
            title="Export verbose JSON",
            defaultextension=".json",
            initialdir=str(self.project_json_output_dir),
            initialfile=f"{self._default_export_stem()}_export.json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return

        project_obj = self.project.to_json_obj()
        project_obj["annotations"] = [ann.to_annotation_json_row(self.project) for ann in self.project.annotations]

        export_obj = {
            "format": "drone_floorplan_export_v1",
            "project": project_obj,
            "exports": [ann.to_export_row(self.project) for ann in self.project.annotations],
        }
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(export_obj, f, indent=2)
            self.status(f"JSON exported: {path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def export_csv(self):
        self.apply_settings_from_ui()
        ok, errs = self.project.export_ready()
        if not ok:
            messagebox.showerror("Export blocked", "\n".join(errs))
            return

        path = filedialog.asksaveasfilename(
            title="Export CSV",
            defaultextension=".csv",
            initialdir=str(self.project_csv_output_dir),
            initialfile=f"{self._default_export_stem()}_export.csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return

        rows = [ann.to_export_row(self.project) for ann in self.project.annotations]
        if not rows:
            messagebox.showerror("No data", "No export rows.")
            return

        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            self.status(f"CSV exported: {path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    # ---------- validation ---------- #

    def validation_lines(self):
        lines = []

        lines.append(f"Image: {'OK' if self.project.image_path else 'Missing'}")
        lines.append(f"Origin: {'OK' if self.project.origin_px else 'Missing'}")

        x_mpp = self.project.x_m_per_px()
        y_mpp = self.project.y_m_per_px()
        avg = self.project.avg_m_per_px()
        mismatch = self.project.scale_mismatch_ratio()

        lines.append(f"X cal: {'OK' if x_mpp is not None else 'Missing'}")
        lines.append(f"Y cal: {'OK' if y_mpp is not None else 'Missing'}")
        if x_mpp is not None:
            lines.append(f"X m/px: {x_mpp:.8f}")
        if y_mpp is not None:
            lines.append(f"Y m/px: {y_mpp:.8f}")
        if avg is not None:
            lines.append(f"AVG m/px: {avg:.8f}")
        if mismatch is not None:
            lines.append(f"Scale mismatch: {mismatch*100:.2f}%")

        lines.append(f"HFOV: {self.project.camera_hfov_deg}")
        lines.append(f"Fill ratio: {self.project.frame_fill_ratio}")
        lines.append(f"Height m: {self.project.global_height_m}")
        lines.append(f"Georef: {'OK' if self.project.has_georef() else 'Local only'}")
        lines.append(f"Annotations: {len(self.project.annotations)}")

        ready, errs = self.project.export_ready()
        lines.append("")
        lines.append(f"Export ready: {'YES' if ready else 'NO'}")
        if errs:
            lines.extend(f"- {e}" for e in errs)
        return lines

    def show_validation_popup(self):
        messagebox.showinfo("Validation", "\n".join(self.validation_lines()))

    # ---------- annotations ---------- #

    def on_list_select(self, _evt=None):
        sel = self.ann_list.curselection()
        if not sel:
            self.selected_ann_id = None
        else:
            idx = sel[0]
            if 0 <= idx < len(self.project.annotations):
                self.selected_ann_id = self.project.annotations[idx].ann_id
        self.refresh_canvas()

    def delete_selected(self):
        if self.selected_ann_id is None:
            return
        self.snapshot()
        self.project.annotations = [a for a in self.project.annotations if a.ann_id != self.selected_ann_id]
        self.selected_ann_id = None
        self.refresh_all()

    # ---------- tool handling ---------- #

    def set_tool(self, tool):
        self.tool_var.set(tool)
        self.temp_points.clear()
        self.clear_temp_preview()
        self.status(f"Tool: {tool}")

    # ---------- map dialog ---------- #

    def open_map_origin_dialog(self):
        dlg = MapOriginDialog(self, self.project.georef_lat_deg, self.project.georef_lon_deg)
        self.wait_window(dlg)
        if dlg.result:
            lat, lon = dlg.result
            self.lat_var.set(str(lat))
            self.lon_var.set(str(lon))
            self.apply_settings_from_ui()

    # ---------- canvas events ---------- #

    def _bind_canvas(self):
        self.bind_all("<Escape>", self.on_escape)
        self.bind_all("<Control-z>", self.on_undo_shortcut)
        self.bind_all("<Control-y>", self.on_redo_shortcut)
        self.bind_all("<Control-s>", self.on_save_shortcut)
        self.bind_all("<Control-Z>", self.on_undo_shortcut)
        self.bind_all("<Control-Y>", self.on_redo_shortcut)
        self.bind_all("<Control-S>", self.on_save_shortcut)

        self.canvas.bind("<Configure>", lambda e: self.refresh_canvas())
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<ButtonPress-2>", self.on_middle_down)
        self.canvas.bind("<B2-Motion>", self.on_middle_drag)
        self.canvas.bind("<ButtonRelease-2>", self.on_middle_up)
        self.canvas.bind("<ButtonPress-3>", self.on_right_down)
        self.canvas.bind("<B3-Motion>", self.on_right_drag)
        self.canvas.bind("<ButtonRelease-3>", self.on_right_up)
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", lambda e: self.zoom_at((e.x, e.y), 1.1))
        self.canvas.bind("<Button-5>", lambda e: self.zoom_at((e.x, e.y), 1/1.1))

    def on_escape(self, _e=None):
        self.set_tool(self.TOOL_SELECT)
        return "break"

    def on_undo_shortcut(self, _e=None):
        self.undo()
        return "break"

    def on_redo_shortcut(self, _e=None):
        self.redo()
        return "break"

    def on_save_shortcut(self, _e=None):
        self.save_project()
        return "break"

    def on_middle_down(self, e):
        self.dragging_pan = True
        self.pan_last = (e.x, e.y)

    def on_middle_drag(self, e):
        if not self.dragging_pan:
            return
        dx = e.x - self.pan_last[0]
        dy = e.y - self.pan_last[1]
        self.pan_last = (e.x, e.y)
        self.view_off_x += dx
        self.view_off_y += dy
        self.refresh_canvas()

    def on_middle_up(self, _e):
        self.dragging_pan = False

    def on_right_down(self, e):
        self.on_middle_down(e)

    def on_right_drag(self, e):
        self.on_middle_drag(e)

    def on_right_up(self, e):
        self.on_middle_up(e)

    def on_mousewheel(self, e):
        factor = 1.1 if e.delta > 0 else 1/1.1
        self.zoom_at((e.x, e.y), factor)

    def on_mouse_move(self, e):
        self.hover_canvas_px = self.canvas_to_image((e.x, e.y))
        self.update_temp_preview()
        self.update_status_coords()

    def update_status_coords(self):
        if self.hover_canvas_px is None:
            return
        ix, iy = self.hover_canvas_px
        self.status(f"Tool: {self.tool_var.get()} | img=({ix:.1f}, {iy:.1f}) | zoom={self.view_scale:.3f}")

    def on_left_click(self, e):
        if not self.image_pil:
            return

        img_p = self.canvas_to_image((e.x, e.y))
        if not self.point_in_image(img_p):
            return

        tool = self.tool_var.get()

        if tool == self.TOOL_SELECT:
            self.pick_annotation_near(img_p)
            return

        if tool == self.TOOL_PAN:
            return

        if tool == self.TOOL_ORIGIN:
            self.snapshot()
            self.project.origin_px = Point2.from_tuple(img_p)
            self.refresh_all()
            return

        if tool == self.TOOL_CAL_X:
            self.handle_calibration_click(img_p, which="x")
            return

        if tool == self.TOOL_CAL_Y:
            self.handle_calibration_click(img_p, which="y")
            return

        if tool == self.TOOL_WINDOW:
            self.handle_window_click(img_p)
            return

    def pick_annotation_near(self, img_p):
        best = None
        best_d = 1e18
        for ann in self.project.annotations:
            pts = [ann.p1_px.tup(), ann.p2_px.tup(), ann.midpoint_px.tup(), ann.drone_px.tup()]
            for p in pts:
                d = v_len(v_sub(p, img_p))
                if d < best_d:
                    best_d = d
                    best = ann.ann_id
        if best is not None and best_d <= (12.0 / self.view_scale):
            self.selected_ann_id = best
        else:
            self.selected_ann_id = None
        self.sync_list_selection()
        self.refresh_canvas()

    def sync_list_selection(self):
        self.ann_list.selection_clear(0, "end")
        if self.selected_ann_id is None:
            return
        for i, ann in enumerate(self.project.annotations):
            if ann.ann_id == self.selected_ann_id:
                self.ann_list.selection_set(i)
                self.ann_list.see(i)
                break

    def handle_calibration_click(self, img_p, which):
        self.temp_points.append(img_p)
        if len(self.temp_points) < 2:
            self.update_temp_preview()
            return

        p1, p2 = self.temp_points[:2]
        length_m = simpledialog.askfloat("Known length", f"Enter known {which.upper()} dimension in meters:", parent=self, minvalue=1e-9)
        if length_m is None:
            self.temp_points.clear()
            self.clear_temp_preview()
            return

        self.snapshot()
        cal = Calibration(Point2.from_tuple(p1), Point2.from_tuple(p2), float(length_m))
        if which == "x":
            self.project.x_cal = cal
        else:
            self.project.y_cal = cal

        self.temp_points.clear()
        self.clear_temp_preview()
        self.refresh_all()

    def handle_window_click(self, img_p):
        if not self.project.origin_px or not self.project.has_scale():
            messagebox.showerror("Blocked", "Set origin and complete calibration first.")
            return

        self.temp_points.append(img_p)
        if len(self.temp_points) < 3:
            self.update_temp_preview()
            return

        p1, p2, side_click = self.temp_points[:3]
        side_deadband_px = 6.0 / self.view_scale
        side_val = signed_side_of_perp_line(p1, p2, side_click)
        if abs(side_val) < side_deadband_px:
            self.status("Side click too close to midpoint-perpendicular line. Click clearly on one side.")
            self.temp_points = [p1, p2]
            self.update_temp_preview()
            return

        try:
            label = f"W{self.project.next_ann_id}"
            ann = self.project.compute_window_annotation(p1, p2, side_click, label=label)
        except Exception as ex:
            messagebox.showerror("Window failed", str(ex))
            self.temp_points.clear()
            self.clear_temp_preview()
            return

        self.snapshot()
        self.project.annotations.append(ann)
        self.selected_ann_id = ann.ann_id
        self.temp_points.clear()
        self.clear_temp_preview()
        self.refresh_all()

    def point_in_image(self, p):
        if not self.image_pil:
            return False
        w, h = self.image_pil.size
        return 0 <= p[0] <= w and 0 <= p[1] <= h

    # ---------- drawing ---------- #

    def refresh_all(self):
        self.sync_ui_from_project()
        self.refresh_validation_text()
        self.refresh_annotation_list()
        self.refresh_canvas()

    def refresh_validation_text(self):
        txt = "\n".join(self.validation_lines())
        self.validation_text.configure(state="normal")
        self.validation_text.delete("1.0", "end")
        self.validation_text.insert("1.0", txt)
        self.validation_text.configure(state="disabled")

    def refresh_annotation_list(self):
        self.ann_list.delete(0, "end")
        for ann in self.project.annotations:
            self.ann_list.insert("end", f"{ann.label} | heading={ann.heading_deg:.1f} | d={ann.standoff_m:.2f}m")
        self.sync_list_selection()

    def refresh_canvas(self):
        self.canvas.delete("all")
        self.clear_temp_preview()

        if self.image_pil:
            self.draw_image()
            self.draw_project_overlays()
            self.update_temp_preview()

    def draw_image(self):
        if not self.image_pil:
            return
        w, h = self.image_pil.size
        sw = max(1, int(round(w * self.view_scale)))
        sh = max(1, int(round(h * self.view_scale)))
        resized = self.image_pil.resize((sw, sh), Image.Resampling.LANCZOS)
        self.image_tk = ImageTk.PhotoImage(resized)
        self.canvas_image_id = self.canvas.create_image(self.view_off_x, self.view_off_y, image=self.image_tk, anchor="nw")

    def draw_project_overlays(self):
        if self.project.origin_px:
            self.draw_cross(self.project.origin_px.tup(), "#ffd200", size=10, width=2)
            self.draw_text(self.project.origin_px.tup(), "Origin", "#ffd200", dy=-16)

        self.draw_calibration(self.project.x_cal, "red", "X Cal")
        self.draw_calibration(self.project.y_cal, "#00d000", "Y Cal")

        for ann in self.project.annotations:
            sel = (ann.ann_id == self.selected_ann_id)
            self.draw_annotation(ann, selected=sel)

    def draw_calibration(self, cal: Calibration, color: str, label: str):
        if not cal.p1 or not cal.p2:
            return
        self.draw_line(cal.p1.tup(), cal.p2.tup(), color, width=2)
        self.draw_circle(cal.p1.tup(), 4, color)
        self.draw_circle(cal.p2.tup(), 4, color)
        mid = v_mid(cal.p1.tup(), cal.p2.tup())
        txt = label
        if cal.known_length_m:
            txt += f" {cal.known_length_m:g}m"
        self.draw_text(mid, txt, color, dy=-12)

    def draw_annotation(self, ann: WindowAnnotation, selected=False):
        color = "#4db8ff" if not selected else "#ff9f1c"
        self.draw_line(ann.p1_px.tup(), ann.p2_px.tup(), color, width=3)
        self.draw_circle(ann.p1_px.tup(), 4, color)
        self.draw_circle(ann.p2_px.tup(), 4, color)
        self.draw_circle(ann.midpoint_px.tup(), 4, "#ffffff")
        self.draw_line(ann.midpoint_px.tup(), ann.drone_px.tup(), "#ff00ff", width=2, dash=(6, 3))
        self.draw_circle(ann.drone_px.tup(), 5, "#ff00ff")
        self.draw_text(ann.drone_px.tup(), f"{ann.label} {ann.heading_deg:.1f}°", "#ff00ff", dy=-14)

    def update_temp_preview(self):
        self.clear_temp_preview()
        if not self.image_pil:
            return

        pts = self.temp_points[:]
        if self.hover_canvas_px and self.point_in_image(self.hover_canvas_px):
            pts_hover = pts + [self.hover_canvas_px]
        else:
            pts_hover = pts

        tool = self.tool_var.get()

        if tool in (self.TOOL_CAL_X, self.TOOL_CAL_Y):
            color = "red" if tool == self.TOOL_CAL_X else "#00d000"
            if len(pts_hover) >= 2:
                self.temp_preview_ids.append(self._create_line(pts_hover[0], pts_hover[1], color, 2, dash=(4, 2)))

        elif tool == self.TOOL_WINDOW:
            if len(pts_hover) >= 2:
                p1, p2 = pts_hover[0], pts_hover[1]
                self.temp_preview_ids.append(self._create_line(p1, p2, "#4db8ff", 2, dash=(4, 2)))
                mid = v_mid(p1, p2)
                u = v_norm(v_sub(p2, p1))
                if v_len(u) > 0:
                    n = (-u[1], u[0])
                    # guide line
                    a = v_add(mid, v_mul(n, -1000))
                    b = v_add(mid, v_mul(n, 1000))
                    self.temp_preview_ids.append(self._create_line(a, b, "#cccc00", 1, dash=(3, 3)))

                if len(pts_hover) >= 3:
                    side_click = pts_hover[2]
                    side_deadband_px = 6.0 / self.view_scale
                    side_val = signed_side_of_perp_line(p1, p2, side_click)
                    if abs(side_val) >= side_deadband_px and self.project.origin_px and self.project.has_scale():
                        try:
                            ann = self.project.compute_window_annotation(p1, p2, side_click, label="preview")
                            self.temp_preview_ids.append(self._create_line(ann.midpoint_px.tup(), ann.drone_px.tup(), "#ff00ff", 2, dash=(6, 3)))
                            self.temp_preview_ids.append(self._create_circle(ann.drone_px.tup(), 5, "#ff00ff"))
                        except Exception:
                            pass

    def clear_temp_preview(self):
        for item in self.temp_preview_ids:
            self.canvas.delete(item)
        self.temp_preview_ids.clear()

    # ---------- low-level canvas helpers ---------- #

    def _create_line(self, p1: Vec2, p2: Vec2, color: str, width: int = 1, dash: Optional[Tuple[int, int]] = None):
        c1 = self.image_to_canvas(p1)
        c2 = self.image_to_canvas(p2)
        return self.canvas.create_line(c1[0], c1[1], c2[0], c2[1], fill=color, width=width, dash=1)

    def _create_circle(self, p, r, color):
        c = self.image_to_canvas(p)
        rr = r
        return self.canvas.create_oval(c[0]-rr, c[1]-rr, c[0]+rr, c[1]+rr, outline=color, fill=color)

    def draw_line(self, p1, p2, color, width=1, dash=None):
        self._create_line(p1, p2, color, width, dash)

    def draw_circle(self, p, r, color):
        self._create_circle(p, r, color)

    def draw_cross(self, p, color, size=8, width=1):
        x, y = p
        self.draw_line((x-size, y), (x+size, y), color, width)
        self.draw_line((x, y-size), (x, y+size), color, width)

    def draw_text(self, p, txt, color, dy=0):
        c = self.image_to_canvas((p[0], p[1]))
        self.canvas.create_text(c[0], c[1] + dy, text=txt, fill=color, anchor="s")

    # ---------- misc ---------- #

    def status(self, msg):
        self.status_var.set(msg)

    def destroy(self):
        super().destroy()


if __name__ == "__main__":
    app = AnnotatorApp()
    app.mainloop()


