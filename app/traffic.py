"""Live-conditions store. Simulated here; swap `add_incident` callers for a
TomTom/HERE poller and keep the same interface."""
import math
from dataclasses import dataclass
from . import graph as g


@dataclass
class Incident:
    id: int
    lat: float
    lon: float
    radius_m: float
    kind: str          # "closure" | "congestion"
    factor: float


class TrafficState:
    def __init__(self, G):
        self.G = G
        self.incidents: list[Incident] = []
        self._factor: dict[tuple, float] = {}

    def add_incident(self, lat, lon, radius_m=300.0, kind="congestion", factor=3.0) -> Incident:
        inc = Incident(len(self.incidents) + 1, lat, lon, radius_m, kind, factor)
        self.incidents.append(inc)
        f = math.inf if kind == "closure" else factor
        for u, v in self.G.edges:
            mlat = (self.G.nodes[u]["y"] + self.G.nodes[v]["y"]) / 2
            mlon = (self.G.nodes[u]["x"] + self.G.nodes[v]["x"]) / 2
            if g.haversine_m(lat, lon, mlat, mlon) <= radius_m:
                self._factor[(u, v)] = max(self._factor.get((u, v), 1.0), f)
        return inc

    def clear(self):
        self.incidents.clear()
        self._factor.clear()

    def factor(self, u, v) -> float:
        return self._factor.get((u, v), 1.0)

    def edge_time(self, u, v, d) -> float:
        return d["travel_time"] * self.factor(u, v)
