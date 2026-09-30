"""Road graph. Synthetic grid by default (runs anywhere, no downloads);
real OpenStreetMap roads with USE_OSMNX=1."""
import math
import networkx as nx
from . import config


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def build_synthetic_graph(n=14, step_deg=0.003):
    """n x n grid; every 4th row/column is a fast arterial (50 km/h), rest 25 km/h."""
    lat0, lon0 = config.CENTER
    G = nx.DiGraph()
    nid = lambda i, j: i * n + j
    for i in range(n):
        for j in range(n):
            G.add_node(nid(i, j), y=lat0 + (i - n // 2) * step_deg, x=lon0 + (j - n // 2) * step_deg)
    for i in range(n):
        for j in range(n):
            for di, dj in ((0, 1), (1, 0)):
                a, b = (i, j), (i + di, j + dj)
                if b[0] >= n or b[1] >= n:
                    continue
                u, v = nid(*a), nid(*b)
                length = haversine_m(G.nodes[u]["y"], G.nodes[u]["x"], G.nodes[v]["y"], G.nodes[v]["x"])
                arterial = (i % 4 == 0 and di == 0) or (j % 4 == 0 and dj == 0)
                t = length / ((50 if arterial else 25) / 3.6)
                G.add_edge(u, v, length=length, travel_time=t)
                G.add_edge(v, u, length=length, travel_time=t)
    return G


def load_graph():
    if config.USE_OSMNX:
        import osmnx as ox
        M = ox.graph_from_point(config.CENTER, dist=config.GRAPH_DIST_M, network_type="drive")
        routing = getattr(ox, "routing", ox)          # osmnx >= 1.9 moved these into ox.routing
        M = routing.add_edge_speeds(M, fallback=30)   # km/h for roads with no speed tag
        M = routing.add_edge_travel_times(M)
        G = nx.DiGraph()
        for u, v, d in M.edges(data=True):          # collapse parallel edges, keep the fastest
            if G.has_edge(u, v) and G[u][v]["travel_time"] <= d["travel_time"]:
                continue
            G.add_edge(u, v, length=d["length"], travel_time=d["travel_time"])
        for n, d in M.nodes(data=True):
            G.add_node(n, x=d["x"], y=d["y"])
        return G
    return build_synthetic_graph()


def node_latlon(G, n):
    return G.nodes[n]["y"], G.nodes[n]["x"]


def nearest_node(G, lat, lon):
    # O(N) is fine for a demo graph; swap for osmnx.nearest_nodes / a KD-tree at scale
    return min(G.nodes, key=lambda n: haversine_m(lat, lon, G.nodes[n]["y"], G.nodes[n]["x"]))
