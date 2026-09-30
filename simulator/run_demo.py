"""Scenario replay against a running API.
  uvicorn app.main:app &    then    python -m simulator.run_demo --scenario accident
Scenarios inject events at fixed ticks so the demo is deterministic and repeatable."""
import argparse
import random
import time
import httpx

API = "http://127.0.0.1:8000"
ORIGIN, DEST = (12.8967, 77.6018), (12.9357, 77.6408)     # opposite corners of the demo grid

SCENARIOS = {
    "accident":   [{"tick": 6, "type": "incident", "ahead": 6, "kind": "closure", "radius_m": 350}],
    "congestion": [{"tick": 5, "type": "incident", "ahead": 5, "kind": "congestion", "factor": 5, "radius_m": 500}],
    "wrong_turn": [{"tick": 5, "type": "wrong_turn", "pings": 5}],
    "combo":      [{"tick": 4, "type": "wrong_turn", "pings": 5},
                   {"tick": 14, "type": "incident", "ahead": 5, "kind": "closure", "radius_m": 350}],
}


def run(scenario: str, dt: float, auto_approve: bool, seed: int = 7):
    rng = random.Random(seed)
    c = httpx.Client(base_url=API, timeout=10)
    c.post("/reset")
    vid = "AMB-01"
    o = c.get("/config").json()["origins"][0]
    v = c.post("/dispatch/auto", json={"vehicle_id": vid, "origin": [o["lat"], o["lon"]], "need": "trauma"}).json()
    route, i, wrong = v["route_coords"], 0, 0
    print(f"[t=0] dispatched {vid}, planned ETA {v['eta_s'] / 60:.1f} min, {len(route)} nodes")
    events = SCENARIOS[scenario]

    for tick in range(1, 400):
        if i >= len(route) - 1:
            break
        for ev in (e for e in events if e["tick"] == tick):
            if ev["type"] == "incident":
                lat, lon = route[min(i + ev["ahead"], len(route) - 1)]
                r = c.post("/incidents", json={"lat": lat, "lon": lon, "radius_m": ev["radius_m"],
                                               "kind": ev["kind"], "factor": ev.get("factor", 3.0)}).json()
                print(f"[tick {tick}] INCIDENT {ev['kind']} injected -> proposals for {r['vehicles_with_proposals']}")
            else:
                wrong = ev["pings"]
                print(f"[tick {tick}] WRONG TURN for {wrong} pings")
        if wrong > 0:
            lat, lon = route[i][0] + 0.0012, route[i][1] + 0.0012      # ~180 m off the road (diagonal, so never parallel to it)
            wrong -= 1
        else:
            i += 1
            lat, lon = route[i]
        lat += rng.gauss(0, 0.00003); lon += rng.gauss(0, 0.00003)   # ~3 m GPS noise
        c.post(f"/vehicles/{vid}/ping", json={"lat": lat, "lon": lon})

        state = c.get(f"/vehicles/{vid}").json()
        if state["pending"]:
            p = state["pending"]
            print(f"[tick {tick}] PROPOSAL ({p['trigger']}): {p['explanation']}")
            for s in p["trace"]:
                print(f"           {s['step']}. [{s['kind']}] {s['text']}")
            if auto_approve:
                a = c.post(f"/vehicles/{vid}/approve").json()
                route, i, wrong = a["route_coords"], 0, 0
                print(f"[tick {tick}] dispatcher APPROVED; rerouted ({len(route)} nodes)")
        time.sleep(dt)

    print("[done]", c.get("/stats").json())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=SCENARIOS, default="accident")
    ap.add_argument("--dt", type=float, default=0.3, help="seconds per tick")
    ap.add_argument("--manual", action="store_true", help="don't auto-approve; use the dashboard")
    a = ap.parse_args()
    run(a.scenario, a.dt, not a.manual)
