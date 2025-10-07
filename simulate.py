# simulate.py
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
import time
import pandas as pd
import numpy as np
from shapely.geometry import LineString, Point

@dataclass
class TrainPoint:
    lat: float
    lon: float
    route_id: str
    trip_id: str
    next_stop_id: Optional[str]
    eta_sec: Optional[int]  # seconds until next stop

def _to_epoch(ts):
    # ts is GTFS epoch seconds already in RT feed (UTC). Streamlit runs UTC servers typically.
    return int(ts)

def build_shape_index(shapes_df: pd.DataFrame) -> Dict[Any, LineString]:
    """Build LineString per shape_id ordered by sequence."""
    out = {}
    for sid, g in shapes_df.groupby("shape_id"):
        g = g.sort_values("shape_pt_sequence")
        coords = list(zip(g["shape_pt_lon"].to_numpy(), g["shape_pt_lat"].to_numpy()))
        out[sid] = LineString(coords)
    return out

def stops_lookup(stops_df: pd.DataFrame) -> Dict[str, Tuple[float, float]]:
    return {row.stop_id: (row.stop_lat, row.stop_lon) for _, row in stops_df.iterrows()}

def interpolate_on_segment(a_latlon, b_latlon, t0, t1, now) -> Tuple[float, float, float]:
    """Linear interpolation between two stops by time. Returns (lat, lon, progress[0..1])"""
    (alat, alon), (blat, blon) = a_latlon, b_latlon
    dur = max(1, t1 - t0)
    alpha = np.clip((now - t0) / dur, 0.0, 1.0)
    lat = alat + (blat - alat) * alpha
    lon = alon + (blon - alon) * alpha
    return lat, lon, alpha

def rt_to_points(entities, static):
    """
    Convert GTFS-RT TripUpdates into approximate positions using stop-to-stop interpolation.
    """
    st = static["stop_times"]
    stops = static["stops"]
    trips = static["trips"]

    stop_coord = stops_lookup(stops)
    now = int(time.time())

    trip_route = trips.set_index("trip_id")["route_id"].to_dict()

    points: List[TrainPoint] = []

    for e in entities:
        if not e.HasField("trip_update"):
            continue
        tu = e.trip_update
        trip_id = tu.trip.trip_id

        # Prefer route_id from RT; fall back to static mapping
        route_id_rt = tu.trip.route_id if tu.trip.route_id else None
        route_id = (route_id_rt or trip_route.get(trip_id))

        # if still unknown, keep it (don’t drop yet); we’ll filter later only if it’s clearly not J/Z/M
        if route_id not in {"J", "Z", "M", None}:
            continue

        stus = list(tu.stop_time_update)
        # find the pair such that now is between departure of i and arrival of i+1
        # fallback: if now before first arrival, pin to first stop; if after last, skip.
        # Convert arrival/departure times to epoch
        times = []
        for u in stus:
            arr = u.arrival.time if u.HasField("arrival") else None
            dep = u.departure.time if u.HasField("departure") else None
            times.append(dict(stop_id=u.stop_id, arr=arr, dep=dep))

        if not times:
            continue

        # find segment
        placed = False
        for i in range(len(times) - 1):
            a, b = times[i], times[i + 1]
            t0 = a.get("dep") or a.get("arr")
            t1 = b.get("arr") or b.get("dep")
            if not t0 or not t1:
                continue
            if t0 <= now <= t1:
                a_xy = stop_coord.get(a["stop_id"])
                b_xy = stop_coord.get(b["stop_id"])
                if not a_xy or not b_xy:
                    break
                lat, lon, progress = interpolate_on_segment(a_xy, b_xy, t0, t1, now)
                eta = max(0, t1 - now)
                points.append(TrainPoint(lat, lon, route_id, trip_id, b["stop_id"], eta))
                placed = True
                break

        if not placed:
            first = times[0]
            t0 = first.get("arr") or first.get("dep")
            if t0 and now < t0 and first["stop_id"] in stop_coord:
                lat, lon = stop_coord[first["stop_id"]]
                eta = t0 - now
                points.append(TrainPoint(lat, lon, route_id or "?", trip_id, b["stop_id"], eta))
                continue
    return points

def next_arrivals_for_stop(entities, stop_id: str, max_results=5):
    now = int(time.time())
    arrivals = []
    for e in entities:
        if not e.HasField("trip_update"):
            continue
        route_id = e.trip_update.trip.route_id or ""
        for u in e.trip_update.stop_time_update:
            if u.stop_id == stop_id:
                t = (u.arrival.time if u.HasField("arrival") else None) or \
                    (u.departure.time if u.HasField("departure") else None)
                if t and t >= now:
                    arrivals.append((route_id, t))
    arrivals.sort(key=lambda x: x[1])
    return arrivals[:max_results]
