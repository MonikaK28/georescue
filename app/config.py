import json
import math
import os
from pathlib import Path

USE_OSMNX = os.getenv("USE_OSMNX", "0") == "1"

# --- locations (edit locations.json, or point GEORESCUE_LOCATIONS at another file) ---
_LOC = Path(os.getenv("GEORESCUE_LOCATIONS", Path(__file__).resolve().parent.parent / "locations.json"))
LOCATIONS = json.loads(_LOC.read_text()) if _LOC.exists() else {}
CENTER = tuple(LOCATIONS.get("center", (12.9177, 77.6228)))          # (lat, lon)
if USE_OSMNX:
    ORIGINS = LOCATIONS.get("origins") or [{"name": "Center", "lat": CENTER[0], "lon": CENTER[1]}]
    HOSPITALS = LOCATIONS.get("hospitals") or []                     # empty -> synthetic hospitals
else:                                                                # synthetic grid demo
    ORIGINS = [{"name": "Grid SW corner", "lat": CENTER[0] - 0.021, "lon": CENTER[1] - 0.021},
               {"name": "Grid NW corner", "lat": CENTER[0] + 0.018, "lon": CENTER[1] - 0.021}]
    HOSPITALS = []


def _hav(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


# road-network download radius: covers every origin and hospital (+1 km), 4-9 km
_pts = [(o["lat"], o["lon"]) for o in ORIGINS] + [(h["lat"], h["lon"]) for h in HOSPITALS]
GRAPH_DIST_M = int(os.getenv("GRAPH_DIST_M") or min(9000, max(4000, max((_hav(CENTER, p) for p in _pts), default=0) + 1000)))

DEVIATION_THRESHOLD_M = 60             # distance from planned route that counts as "off route"
DEVIATION_CONSECUTIVE = 3              # consecutive pings needed (filters GPS noise)
MIN_SAVING_S = 30                      # only propose a reroute if it saves at least this much
CLOSURE_PENALTY_S = 180                # per closed segment: drive to the blockage, turn around (baseline only; tunable assumption)
