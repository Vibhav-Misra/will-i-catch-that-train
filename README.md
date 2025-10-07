# Will I Catch That Train?
*A Real-Time J/Z/M NYC Subway Tracker & Commute Optimizer*

A Streamlit web app that helps you decide when to leave home for the J, Z, M subway lines in NYC.  
It combines static GTFS schedules with real-time GTFS-RT feeds to draw trains moving on the map and to compute a “Leave-Now” suggestion.

---

## Features
- **Static Map** Plots only J/Z/M routes on a dark map (via Folium / Pydeck). 
- **Live Positions** Interpolates train positions between stops using live arrival times (no GPS required). 
- **Leave-Now Assistant** Calculates when to leave home based on walking time + buffer vs upcoming train arrivals. 
- **Platform-specific Stop IDs** Supports separate northbound / southbound platforms (e.g., `M11S`). 
- **Feed-agnostic** Works without API keys — uses the public MTA GTFS-RT endpoints. 
- **Deploy-ready** Runs locally or on Hugging Face Spaces as a Streamlit app. 

## Data Sources

Static GTFS → schedules, stops, shapes
(downloaded zip you placed in data/)

Realtime feeds → public MTA endpoints

J/Z → https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct/gtfs-jz

B/D/F/M (for M) → https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct/gtfs-bdfm

Some CDN edges still return 403 for the slash-based URL; the code automatically retries with the %2F-encoded URL.

## Tech Stack
- Frontend / UI: Streamlit, Pydeck (or Folium)
- Realtime data: MTA GTFS-RT (protobuf via gtfs-realtime-bindings)
- Static data: MTA GTFS static bundle (CSV in zip)
- Computation: Python 3.9+, pandas, numpy, shapely
- Hosting: HuggingFace Spaces
- Version control: Git + GitHub / HF Repo

