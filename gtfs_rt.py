# gtfs_rt.py  — no API key required
import os
import time
import requests
from google.transit import gtfs_realtime_pb2

# Use the slash-form URLs by default. (You can still override via env.)
DEFAULT_FEEDS = {
    "gtfs-jz": os.getenv(
        "JZ_FEED_URL",
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct/gtfs-jz",
    ),
    "gtfs-bdfm": os.getenv(
        "BDFM_FEED_URL",
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct/gtfs-bdfm",
    ),
}

# Some networks/CDN edges are picky; try both slash and %2F forms when needed.
FALLBACK_MAP = {
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct/gtfs-jz":
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz",
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct/gtfs-bdfm":
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
}

def _fetch(url: str, timeout=20):
    # No x-api-key header anymore
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed

def fetch_feed(url: str, timeout=20):
    """Fetch with a graceful fallback to the URL-encoded variant if needed."""
    try:
        return _fetch(url, timeout=timeout)
    except requests.HTTPError as e:
        # Try fallback form if available (handles occasional 403/401 glitches)
        fb = FALLBACK_MAP.get(url)
        if fb:
            return _fetch(fb, timeout=timeout)
        raise e

def load_rt_entities():
    ents = []
    for name, url in DEFAULT_FEEDS.items():
        try:
            feed = fetch_feed(url)
            ents.extend(feed.entity)
        except Exception:
            # tolerate one feed failing
            continue
        time.sleep(0.1)
    return ents
