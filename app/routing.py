"""Deterministic routing core. The LLM/agent never computes geometry or ETAs."""
import math
from dataclasses import dataclass
from itertools import islice
import networkx as nx
from . import config, graph as g


@dataclass
class RouteOption:
    id: str
    nodes: list
    coords: list              # [[lat, lon], ...]
    distance_m: float
    eta_s: float
    free_flow_s: float
    delay_s: float
    closed_segments: int
    congested_segments: int


def make_weight(state):
    def w(u, v, d):
        t = state.edge_time(u, v, d)
        return None if math.isinf(t) else t      # None = edge hidden from the search
    return w


def evaluate(G, state, nodes, label="-") -> RouteOption:
    dist = free = eta = 0.0
    closed = cong = 0
    for u, v in zip(nodes, nodes[1:]):
        d = G[u][v]
        dist += d["length"]
        free += d["travel_time"]
        f = state.factor(u, v)
        if math.isinf(f):
            closed += 1
            eta += d["travel_time"] + config.CLOSURE_PENALTY_S
        else:
            eta += d["travel_time"] * f
            cong += f > 1.0
    coords = [list(g.node_latlon(G, n)) for n in nodes]
    return RouteOption(label, list(nodes), coords, round(dist), round(eta, 1), round(free, 1),
                       round(eta - free, 1), closed, int(cong))


def static_route(G, src, dst):
    """What a conventional navigator does: fastest path assuming free-flow."""
    return nx.shortest_path(G, src, dst, weight="travel_time")


def _edges(nodes):
    return set(zip(nodes, nodes[1:]))


def alternatives(G, state, src, dst, k=3, max_overlap=0.8, scan=40) -> list[RouteOption]:
    """Up to k *meaningfully different* routes: a candidate is dropped if it shares
    more than `max_overlap` of its edges with an already-kept route."""
    kept = []
    try:
        for p in islice(nx.shortest_simple_paths(G, src, dst, weight=make_weight(state)), scan):
            e = _edges(p)
            if all(len(e & _edges(q)) / max(len(e), 1) <= max_overlap for q in kept):
                kept.append(p)
            if len(kept) == k:
                break
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []
    return [evaluate(G, state, p, chr(65 + i)) for i, p in enumerate(kept)]
