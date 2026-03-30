import customtkinter

try:
    from customtkintermapview import CTkinterMapView as MapViewWidget
except Exception:
    from tkintermapview import TkinterMapView as MapViewWidget

customtkinter.set_default_color_theme("blue")

TILE_SERVERS = {
    "OpenStreetMap": {
        "url": "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "max_zoom": 19,
    },
    "Google normal": {
        "url": "https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga",
        "max_zoom": 22,
    },
    "Google satellite": {
        "url": "https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga",
        "max_zoom": 22,
    },
    "Stamen watercolor": {
        "url": "http://c.tile.stamen.com/watercolor/{z}/{x}/{y}.png",
        "max_zoom": 18,
    },
    "Stamen toner": {
        "url": "http://a.tile.stamen.com/toner/{z}/{x}/{y}.png",
        "max_zoom": 20,
    },
    "HikeBike": {
        "url": "https://tiles.wmflabs.org/hikebike/{z}/{x}/{y}.png",
        "max_zoom": 19,
    },
    "OSM no labels": {
        "url": "https://tiles.wmflabs.org/osm-no-labels/{z}/{x}/{y}.png",
        "max_zoom": 19,
    },
    "Swisstopo": {
        "url": "https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.pixelkarte-farbe/default/current/3857/{z}/{x}/{y}.jpeg",
        "max_zoom": 18,
    },
}

OVERLAY_SERVERS = {
    "None": None,
    "OpenSeaMap": "http://tiles.openseamap.org/seamark/{z}/{x}/{y}.png",
    "OpenRailwayMap": "http://a.tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png",
}


class App(customtkinter.CTk):

    APP_NAME = "TkinterMapView with CustomTkinter"
    WIDTH = 800
    HEIGHT = 500

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.title(App.APP_NAME)
        self.geometry(str(App.WIDTH) + "x" + str(App.HEIGHT))
        self.minsize(App.WIDTH, App.HEIGHT)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.bind("<Command-q>", self.on_closing)
        self.bind("<Command-w>", self.on_closing)
        self.createcommand('tk::mac::Quit', self.on_closing)

        self.marker_list = []

        # ============ create two CTkFrames ============

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.frame_left = customtkinter.CTkFrame(master=self, width=150, corner_radius=0, fg_color=None)
        self.frame_left.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")

        self.frame_right = customtkinter.CTkFrame(master=self, corner_radius=0)
        self.frame_right.grid(row=0, column=1, rowspan=1, pady=0, padx=0, sticky="nsew")

        # ============ frame_left ============

        self.frame_left.grid_rowconfigure(2, weight=1)

        self.button_1 = customtkinter.CTkButton(master=self.frame_left,
                                                text="Set Marker",
                                                command=self.set_marker_event)
        self.button_1.grid(pady=(20, 0), padx=(20, 20), row=0, column=0)

        self.button_2 = customtkinter.CTkButton(master=self.frame_left,
                                                text="Clear Markers",
                                                command=self.clear_marker_event)
        self.button_2.grid(pady=(20, 0), padx=(20, 20), row=1, column=0)

        self.map_label = customtkinter.CTkLabel(self.frame_left, text="Tile Server:", anchor="w")
        self.map_label.grid(row=3, column=0, padx=(20, 20), pady=(20, 0))
        self.map_option_menu = customtkinter.CTkOptionMenu(self.frame_left, values=list(TILE_SERVERS.keys()),
                                                                       command=self.change_map)
        self.map_option_menu.grid(row=4, column=0, padx=(20, 20), pady=(10, 0))

        self.overlay_label = customtkinter.CTkLabel(self.frame_left, text="Overlay:", anchor="w")
        self.overlay_label.grid(row=5, column=0, padx=(20, 20), pady=(20, 0))
        self.overlay_option_menu = customtkinter.CTkOptionMenu(self.frame_left, values=list(OVERLAY_SERVERS.keys()),
                                    command=self.change_overlay)
        self.overlay_option_menu.grid(row=6, column=0, padx=(20, 20), pady=(10, 0))

        self.appearance_mode_label = customtkinter.CTkLabel(self.frame_left, text="Appearance Mode:", anchor="w")
        self.appearance_mode_label.grid(row=7, column=0, padx=(20, 20), pady=(20, 0))
        self.appearance_mode_optionemenu = customtkinter.CTkOptionMenu(self.frame_left, values=["Light", "Dark", "System"],
                                                                       command=self.change_appearance_mode)
        self.appearance_mode_optionemenu.grid(row=8, column=0, padx=(20, 20), pady=(10, 20))

        # ============ frame_right ============

        self.frame_right.grid_rowconfigure(1, weight=1)
        self.frame_right.grid_rowconfigure(0, weight=0)
        self.frame_right.grid_columnconfigure(0, weight=1)
        self.frame_right.grid_columnconfigure(1, weight=0)
        self.frame_right.grid_columnconfigure(2, weight=1)

        self.map_widget = MapViewWidget(self.frame_right, corner_radius=0)
        self.map_widget.grid(row=1, rowspan=1, column=0, columnspan=3, sticky="nswe", padx=(0, 0), pady=(0, 0))

        self.entry = customtkinter.CTkEntry(master=self.frame_right,
                                            placeholder_text="type address")
        self.entry.grid(row=0, column=0, sticky="we", padx=(12, 0), pady=12)
        self.entry.bind("<Return>", self.search_event)

        self.button_5 = customtkinter.CTkButton(master=self.frame_right,
                                                text="Search",
                                                width=90,
                                                command=self.search_event)
        self.button_5.grid(row=0, column=1, sticky="w", padx=(12, 0), pady=12)

        # Set default values
        self.map_option_menu.set("OpenStreetMap")
        self.overlay_option_menu.set("None")
        self.appearance_mode_optionemenu.set("Dark")
        self.change_map("OpenStreetMap")
        self.change_overlay("None")
        self.map_widget.set_position(52.5200, 13.4050)
        self.map_widget.set_zoom(11)

    def search_event(self, event=None):
        self.map_widget.set_address(self.entry.get())

    def set_marker_event(self):
        current_position = self.map_widget.get_position()
        self.marker_list.append(self.map_widget.set_marker(current_position[0], current_position[1]))

    def clear_marker_event(self):
        for marker in self.marker_list:
            marker.delete()
        self.marker_list.clear()

    def change_appearance_mode(self, new_appearance_mode: str):
        customtkinter.set_appearance_mode(new_appearance_mode)

    def change_map(self, new_map: str):
        cfg = TILE_SERVERS.get(new_map)
        if cfg is None:
            return
        self.map_widget.set_tile_server(cfg["url"], max_zoom=cfg["max_zoom"])

    def change_overlay(self, new_overlay: str):
        overlay_url = OVERLAY_SERVERS.get(new_overlay)
        if overlay_url is None:
            try:
                self.map_widget.set_overlay_tile_server("")
            except Exception:
                pass
            return
        self.map_widget.set_overlay_tile_server(overlay_url)

    def on_closing(self, event=0):
        self.destroy()

    def start(self):
        self.mainloop()


if __name__ == "__main__":
    app = App()
    app.start()