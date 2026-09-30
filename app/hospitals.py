"""Hospital-aware destination choice. Synthetic hospitals near the demo grid.
Eligible = has the needed specialty and >0 free beds.
score = live ETA + crowding penalty (120 s when fewer than 3 beds free). Fully explainable."""
from . import config, graph as g, routing

_lat0, _lon0 = config.CENTER
_S = 0.003
_SEED = [
    {"id": "H1", "name": "City Trauma Centre",     "off": (5, 5),   "specialties": ["trauma", "general"],  "beds0": 5},
    {"id": "H2", "name": "Heart Institute",        "off": (-3, 4),  "specialties": ["cardiac", "general"], "beds0": 2},
    {"id": "H3", "name": "Stroke & Neuro Centre",  "off": (4, -5),  "specialties": ["stroke", "general"],  "beds0": 3},
    {"id": "H4", "name": "Riverside Trauma & General", "off": (-1, -1), "specialties": ["trauma", "general"], "beds0": 3},
]
HOSPITALS: dict[str, dict] = {}


def init(G):
    HOSPITALS.clear()
    if config.HOSPITALS:                                   # real places from locations.json (USE_OSMNX=1)
        seed = [{"id": f"H{i + 1}", "name": h["name"], "lat": h["lat"], "lon": h["lon"],
                 "specialties": h["specialties"], "beds0": h.get("beds", 3)} for i, h in enumerate(config.HOSPITALS)]
    else:                                                  # synthetic hospitals around the demo grid
        seed = [{"id": h["id"], "name": h["name"], "lat": _lat0 + h["off"][0] * _S, "lon": _lon0 + h["off"][1] * _S,
                 "specialties": h["specialties"], "beds0": h["beds0"]} for h in _SEED]
    for h in seed:
        HOSPITALS[h["id"]] = {**h, "beds": h["beds0"], "node": g.nearest_node(G, h["lat"], h["lon"])}


def reset():
    for h in HOSPITALS.values():
        h["beds"] = h["beds0"]


def public(h):
    return {k: h[k] for k in ("id", "name", "lat", "lon", "specialties", "beds")}


def rank(G, state, origin_node, need):
    out = []
    for h in HOSPITALS.values():
        if need not in h["specialties"] or h["beds"] <= 0:
            continue
        opts = routing.alternatives(G, state, origin_node, h["node"], k=1)
        if not opts:
            continue
        pen = 0 if h["beds"] >= 3 else 120
        out.append({**public(h), "node": h["node"], "eta_s": opts[0].eta_s,
                    "penalty_s": pen, "score_s": opts[0].eta_s + pen})
    return sorted(out, key=lambda r: r["score_s"])
