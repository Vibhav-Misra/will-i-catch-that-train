# gtfs_static.py
import zipfile
import pandas as pd
from pathlib import Path

ROUTES = {"J", "Z", "M"}  # allowed route_ids

def load_static(gtfs_zip_path: str):
    zpath = Path(gtfs_zip_path)
    if not zpath.exists():
        raise FileNotFoundError(
            f"Static GTFS not found at {gtfs_zip_path}. "
            "Download MTA static GTFS and place as data/nyc_gtfs_static.zip"
        )

    with zipfile.ZipFile(zpath) as zf:
        stops = pd.read_csv(zf.open("stops.txt"))
        routes = pd.read_csv(zf.open("routes.txt"))
        trips = pd.read_csv(zf.open("trips.txt"))
        stop_times = pd.read_csv(zf.open("stop_times.txt"))
        shapes = pd.read_csv(zf.open("shapes.txt"))

    # keep only J/Z/M routes
    keep_routes = routes[routes["route_id"].isin(ROUTES)].copy()
    keep_trips = trips[trips["route_id"].isin(ROUTES)].copy()

    # useful joins
    st = stop_times.merge(
        keep_trips[["route_id", "trip_id", "shape_id"]],
        on="trip_id", how="inner"
    )

    # reduce shapes to those used by J/Z/M
    keep_shape_ids = keep_trips["shape_id"].dropna().unique()
    keep_shapes = shapes[shapes["shape_id"].isin(keep_shape_ids)].copy()

    # stops subset that appear in these routes
    keep_stop_ids = st["stop_id"].unique()
    keep_stops = stops[stops["stop_id"].isin(keep_stop_ids)].copy()

    # sometimes stop_lat/stop_lon come as strings
    for col in ("stop_lat", "stop_lon"):
        keep_stops[col] = pd.to_numeric(keep_stops[col], errors="coerce")

    # route colors (fallbacks)
    color_map = {"J": "#FF7F00", "Z": "#FFD300", "M": "#2850AD"}  # orange, yellow, blue-ish
    keep_routes["color"] = keep_routes["route_id"].map(color_map).fillna("#6b7280")

    return {
        "routes": keep_routes,
        "trips": keep_trips,
        "stop_times": st,
        "stops": keep_stops,
        "shapes": keep_shapes,
    }
