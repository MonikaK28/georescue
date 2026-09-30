"""Off-route detection: metric distance from GPS point to the planned polyline,
debounced over N consecutive pings so single noisy fixes don't trigger alerts."""
import math
from shapely.geometry import LineString, Point
from . import config


def _to_xy(lat, lon, lat0):
    return lon * 111320.0 * math.cos(math.radians(lat0)), lat * 110540.0


def distance_to_route_m(route_coords, lat, lon) -> float:
    """route_coords: [[lat, lon], ...]"""
    if len(route_coords) < 2:
        return 0.0
    line = LineString([_to_xy(a, b, lat) for a, b in route_coords])
    return line.distance(Point(*_to_xy(lat, lon, lat)))


class DeviationDetector:
    def __init__(self, threshold_m=config.DEVIATION_THRESHOLD_M, consecutive=config.DEVIATION_CONSECUTIVE):
        self.threshold_m, self.consecutive, self.count = threshold_m, consecutive, 0

    def reset(self):
        self.count = 0

    def update(self, route_coords, lat, lon):
        d = distance_to_route_m(route_coords, lat, lon)
        self.count = self.count + 1 if d > self.threshold_m else 0
        return self.count >= self.consecutive, d
