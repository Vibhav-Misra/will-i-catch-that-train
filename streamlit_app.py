# app.py
import os
import time
import json
import hashlib
from dataclasses import is_dataclass, asdict
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import pydeck as pdk

from gtfs_static import load_static
from gtfs_rt import load_rt_entities
from simulate import rt_to_points, next_arrivals_for_stop

def _point_to_dict(p):
    """Convert TrainPoint objects / dataclasses / namedtuples / dicts -> dict with lat, lon, route."""
    if isinstance(p, dict):
        base = dict(p)
    elif is_dataclass(p):
        base = asdict(p)
    else:
        # generic object: pull public attributes
        base = {k: getattr(p, k) for k in dir(p)
                if not k.startswith("_") and not callable(getattr(p, k))}
    # Normalize common field aliases
    lat = (base.get("lat") or base.get("latitude") or base.get("y") or base.get("Lat") or base.get("Latitude"))
    lon = (base.get("lon") or base.get("lng") or base.get("longitude") or base.get("x") or base.get("Lon") or base.get("Longitude"))
    route = (base.get("route") or base.get("route_id") or base.get("line") or base.get("Route"))
    # write back normalized keys (preserve all original keys too)
    base["lat"] = float(lat) if lat is not None else None
    base["lon"] = float(lon) if lon is not None else None
    base["route"] = route
    return base

def _normalize_points(points):
    out = [_point_to_dict(p) for p in points]
    # keep only well-formed points
    return [p for p in out if p.get("lat") is not None and p.get("lon") is not None]

# -------------------------------
# App config
# -------------------------------
st.set_page_config(page_title="Will I Catch That Train?", page_icon="🛤️", layout="wide")
st.title("Will I Catch That Train? — J/Z/M Real-Time Tracker")
st.caption("Static GTFS map + GTFS-RT arrivals • simulated positions between stops • ‘Leave now’ helper")

# -------------------------------
# Sidebar controls
# -------------------------------
with st.sidebar:
    st.header("Settings")
    gtfs_zip = st.text_input("Static GTFS ZIP path", "data/nyc_gtfs_static.zip")
    default_home = "M11S"
    home_stop = st.text_input("Home stop_id", default_home, help="e.g., Myrtle Av southbound might be M11S")
    walk_minutes = st.number_input("Walking time to station (min)", 0, 60, 6)
    buffer_minutes = st.number_input("Buffer (min)", 0, 15, 2)
    refresh_sec = st.slider("Auto-refresh seconds", 15, 60, 20)
    live = st.toggle("Live refresh", value=True, help="Pause to reduce redraws")
    routes_filter = st.multiselect("Routes to show", ["J", "Z", "M"], default=["J", "Z", "M"])

if live:
    st_autorefresh(interval=refresh_sec * 1000, key="rt-refresh")

# -------------------------------
# Utilities
# -------------------------------
def _with_hash(color_str: str, default="#6b7280") -> str:
    x = (str(color_str or "")).strip()
    if not x:
        return default
    return f"#{x}" if not x.startswith("#") else x

def _hex_to_rgb_a(hex_color: str, alpha=255):
    """#RRGGBB -> [r, g, b, a]"""
    h = hex_color.lstrip("#")
    if len(h) == 3:  # #RGB
        h = "".join(c*2 for c in h)
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return [r, g, b, alpha]
    except Exception:
        return [107, 114, 128, alpha]  # slate-500 fallback

def _hash_points(points) -> str:
    # stable signature to avoid unnecessary rerenders
    try:
        s = json.dumps(points, sort_keys=True, ensure_ascii=False)
    except Exception:
        # fallback: coarse signature
        s = str([(p.get("route"), round(p.get("lat", 0), 4), round(p.get("lon", 0), 4)) for p in points])
    return hashlib.md5(s.encode()).hexdigest()

# -------------------------------
# Load static GTFS (cached)
# -------------------------------
@st.cache_resource(show_spinner=False)
def _load_static_cached(path):
    return load_static(path)

try:
    static = _load_static_cached(gtfs_zip)
except Exception as e:
    st.error(str(e))
    st.stop()

stops_df = static["stops"].copy()
routes_df = static["routes"].copy()
trips_df = static["trips"].copy()
shapes_df = static["shapes"].copy()

# Center view on the median stop
center_lat = stops_df["stop_lat"].median()
center_lon = stops_df["stop_lon"].median()

# -------------------------------
# Prepare route colors (once)
# -------------------------------
if "route_colors" not in st.session_state:
    color_col = "color" if "color" in routes_df.columns else ("route_color" if "route_color" in routes_df.columns else None)
    route_colors = {}
    if color_col:
        route_colors = (
            routes_df.assign(_c=routes_df[color_col].map(lambda c: _with_hash(c)))
                     .set_index("route_id")["_c"]
                     .to_dict()
        )
    st.session_state["route_colors"] = route_colors

if "route_colors_rgb" not in st.session_state:
    st.session_state["route_colors_rgb"] = {rid: _hex_to_rgb_a(col) for rid, col in st.session_state["route_colors"].items()}

# -------------------------------
# Build static pydeck layers (cached)
#   - PathLayer for shapes (selected routes)
#   - ScatterplotLayer for stops
# -------------------------------
def _build_shapes_paths(trips: pd.DataFrame, shapes: pd.DataFrame, wanted_routes: set):
    # Filter trips by route_id, pull shape_ids, then build paths from shapes points
    sub_trips = trips[trips["route_id"].isin(wanted_routes)]
    shape_ids = sub_trips["shape_id"].dropna().unique().tolist()
    if not shape_ids:
        return pd.DataFrame({"path": [], "route": [], "color": []})
    shp = shapes[shapes["shape_id"].isin(shape_ids)].copy()
    shp = shp.sort_values(["shape_id", "shape_pt_sequence"])

    # map each shape_id -> route_id (pick first trip mapping)
    sid_to_rid = (
        sub_trips.dropna(subset=["shape_id"])
                 .drop_duplicates(subset=["shape_id"])
                 .set_index("shape_id")["route_id"]
                 .to_dict()
    )

    rows = []
    for sid, part in shp.groupby("shape_id"):
        coords = [{"lon": float(lon), "lat": float(lat)} for lat, lon in zip(part["shape_pt_lat"], part["shape_pt_lon"])]
        rid = sid_to_rid.get(sid, None)
        rows.append({
            "shape_id": sid,
            "route": rid,
            "path": coords,
            "color": st.session_state["route_colors_rgb"].get(rid, [90, 90, 90, 180]),
        })
    return pd.DataFrame(rows)

def _build_stops_df(stops: pd.DataFrame, wanted_routes: set):
    # If you want only stops for selected routes, join through trips/stop_times (requires stop_times).
    # For simplicity, show all stops but fade them. If you have stop_times, you can filter precisely.
    df = stops.copy()
    df.rename(columns={"stop_lon": "lon", "stop_lat": "lat"}, inplace=True)
    return df

if "view_state" not in st.session_state:
    st.session_state["view_state"] = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=12, pitch=0, bearing=0)

wanted = set(routes_filter)
if "static_layers" not in st.session_state or st.session_state.get("static_routes_sig") != tuple(sorted(wanted)):
    shapes_paths_df = _build_shapes_paths(trips_df, shapes_df, wanted_routes=wanted)
    stops_vis_df = _build_stops_df(stops_df, wanted_routes=wanted)

    # PathLayer for route shapes
    shapes_layer = pdk.Layer(
        "PathLayer",
        data=shapes_paths_df,
        get_path="path",
        get_color="color",
        width_scale=1,
        width_min_pixels=2,
        pickable=False,
    )

    # Stops layer (light)
    stops_layer = pdk.Layer(
        "ScatterplotLayer",
        data=stops_vis_df,
        get_position="[lon, lat]",
        get_radius=20,
        radius_min_pixels=1,
        radius_max_pixels=4,
        opacity=0.5,
        pickable=False,
    )

    st.session_state["static_layers"] = [shapes_layer, stops_layer]
    st.session_state["static_routes_sig"] = tuple(sorted(wanted))

# -------------------------------
# Fetch realtime + simulate train points
# -------------------------------
entities = load_rt_entities()
train_points = rt_to_points(entities, static)

# NEW: normalize objects -> dicts once
train_points = _normalize_points(train_points)

# Optional: filter to selected routes
if routes_filter:
    train_points = [p for p in train_points if (p.get("route") in routes_filter)]

# Signature to avoid unnecessary re-draw
sig = _hash_points(train_points)

# -------------------------------
# Build dynamic trains layer
# -------------------------------
trains_df = pd.DataFrame(train_points) if train_points else pd.DataFrame(columns=["lat", "lon", "route"])

# Pick color by route (defaults applied)
def _color_for_route(route_id):
    return st.session_state["route_colors_rgb"].get(route_id, [0, 173, 239, 230])  # fallback sky-ish

if "fill_color" not in trains_df.columns:
    trains_df["fill_color"] = trains_df.get("route", pd.Series(dtype=object)).map(_color_for_route)

trains_layer = pdk.Layer(
    "ScatterplotLayer",
    data=trains_df,
    get_position="[lon, lat]",
    get_fill_color="fill_color",
    get_radius=60,         # subway scale
    radius_min_pixels=3,
    radius_max_pixels=10,
    pickable=True,
)

tooltip = {"html": "<b>{route}</b>", "style": {"font-size": "12px"}}

# Choose a basemap only if MAPBOX_API_KEY is available
map_style = "mapbox://styles/mapbox/dark-v11" if os.getenv("MAPBOX_API_KEY") else None

# Render: only re-create deck object if signature changed (reduces churn)
if "last_trains_sig" not in st.session_state or st.session_state["last_trains_sig"] != sig:
    deck = pdk.Deck(
        layers=[*st.session_state["static_layers"], trains_layer],
        initial_view_state=st.session_state["view_state"],
        map_style=map_style,
        tooltip=tooltip,
    )
    st.session_state["deck"] = deck
    st.session_state["last_trains_sig"] = sig
else:
    # Update layers in place for smoother refresh
    deck = st.session_state["deck"]
    deck.layers = [*st.session_state["static_layers"], trains_layer]

# Layout: map left, assistant right
col1, col2 = st.columns([7, 5], gap="large")

with col1:
    st.pydeck_chart(deck, use_container_width=True)

with col2:
    st.subheader("Leave-Now Assistant")
    st.write(f"**Home stop:** `{home_stop}`  •  **Walk:** {walk_minutes} min  •  **Buffer:** {buffer_minutes} min")

    arrivals = next_arrivals_for_stop(entities, home_stop, max_results=6) if entities else []
    now = int(time.time())
    arrivals = [(r, int(t.timestamp()) if hasattr(t, "timestamp") else int(t)) for (r, t) in arrivals]
    arrivals = [(r, t) for (r, t) in arrivals if t >= now]
    arrivals.sort(key=lambda x: x[1])

    if not arrivals:
        st.warning("No upcoming arrivals found for this stop right now.")
    else:
        df = pd.DataFrame([
            dict(
                route=r,
                eta_min=max(0, (t - now) // 60),
                eta_str=time.strftime("%I:%M %p", time.localtime(t)).lstrip("0"),
            )
            for (r, t) in arrivals
        ])
        st.dataframe(df, hide_index=True)

        needed = (walk_minutes + buffer_minutes)
        choice = df[df["eta_min"] >= needed].head(1)
        if choice.empty:
            st.info("If you **leave now**, you might still catch the earliest train — move! 🏃")
        else:
            row = choice.iloc[0]
            leave_in = row["eta_min"] - needed
            if leave_in <= 0:
                st.success(f"**Leave now** to catch the {row['route']} at {row['eta_str']}!")
            else:
                st.success(f"Leave in **{leave_in} min** to catch the {row['route']} at {row['eta_str']}.")

    st.divider()
    st.caption("Tip: stop_id is platform-specific (e.g., northbound vs southbound). Use the one you actually board from.")

if live:
    st.caption("Live refresh enabled.")
