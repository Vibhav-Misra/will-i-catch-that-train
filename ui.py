# ui.py
import folium
from streamlit_folium import st_folium

def draw_map(center=(40.706, -73.935), zoom=12):
    m = folium.Map(location=center, zoom_start=zoom, tiles="cartodbpositron")
    return m

def add_stops(m, stops_df):
    for _, r in stops_df.iterrows():
        folium.CircleMarker(
            location=(r["stop_lat"], r["stop_lon"]),
            radius=2,
            weight=0,
            fill=True,
            fill_opacity=0.9,
            popup=f"{r['stop_name']} ({r['stop_id']})"
        ).add_to(m)

def add_shapes(m, shapes_df, color="#6b7280"):
    for sid, g in shapes_df.groupby("shape_id"):
        g = g.sort_values("shape_pt_sequence")
        coords = list(zip(g["shape_pt_lat"], g["shape_pt_lon"]))
        folium.PolyLine(locations=coords, weight=3, opacity=0.9, color=color).add_to(m)

def add_trains(m, train_points):
    cmap = {"J": "#FF7F00", "Z": "#FFD300", "M": "#2850AD"}
    for tp in train_points:
        folium.CircleMarker(
            location=(tp.lat, tp.lon),
            radius=7,            # was 5
            weight=3,            # was 2
            color=cmap.get(tp.route_id, "#22c55e"),
            fill=True,
            fill_color=cmap.get(tp.route_id, "#22c55e"),
            fill_opacity=0.95,
            popup=f"{tp.route_id} • Trip {tp.trip_id[:6]}… • next {tp.next_stop_id} in {tp.eta_sec}s",
        ).add_to(m)


def render(m):
    return st_folium(m, width=None, height=580)
