"""Adaptive routing vs static shortest path across N random incidents.
Baseline = free-flow route, evaluated under live conditions (closed road = +CLOSURE_PENALTY_S).
Report this assumption on your slide; it is a simulation, not field data."""
import random
import statistics as st
import time
from app import graph as g, routing
from app.traffic import TrafficState


def run(n=100, seed=1):
    rng = random.Random(seed)
    G = g.load_graph()
    nodes = list(G.nodes)
    saved, solve_ms = [], []
    while len(saved) < n:
        a, b = rng.sample(nodes, 2)
        if g.haversine_m(*g.node_latlon(G, a), *g.node_latlon(G, b)) < 2500:
            continue
        static = routing.static_route(G, a, b)
        if len(static) < 6:
            continue
        mid = static[rng.randint(2, len(static) - 3)]
        state = TrafficState(G)
        state.add_incident(*g.node_latlon(G, mid), radius_m=350,
                           kind=rng.choice(["closure", "congestion"]), factor=rng.choice([3, 5]))
        base = routing.evaluate(G, state, static)
        t0 = time.perf_counter()
        opts = routing.alternatives(G, state, a, b, k=3)
        solve_ms.append((time.perf_counter() - t0) * 1000)
        saved.append(base.eta_s - min(o.eta_s for o in opts))
    q = st.quantiles(saved, n=10)
    res = {"runs": n, "mean_s": round(st.mean(saved)), "median_s": round(st.median(saved)), "p10_s": round(q[0]),
           "p90_s": round(q[-1]), "worst_s": round(min(saved)), "improved_pct": round(100 * sum(s > 1 for s in saved) / n),
           "compute_ms_mean": round(st.mean(solve_ms)), "compute_ms_max": round(max(solve_ms))}
    print(f"runs={n}  mean saved={st.mean(saved):.0f}s  median={st.median(saved):.0f}s  "
          f"p10={q[0]:.0f}s  p90={q[-1]:.0f}s  worst={min(saved):.0f}s")
    print(f"improved in {sum(s > 1 for s in saved) / n:.0%} of runs;  "
          f"reroute compute: mean {st.mean(solve_ms):.0f} ms, max {max(solve_ms):.0f} ms")
    return res


if __name__ == "__main__":
    run()
