from fastapi.testclient import TestClient
from app import graph as g, routing
from app.deviation import DeviationDetector, distance_to_route_m
from app.traffic import TrafficState

G = g.build_synthetic_graph()


def test_distance_and_debounce():
    route = [[12.90, 77.60], [12.90, 77.61]]
    assert distance_to_route_m(route, 12.90, 77.605) < 1
    assert 100 < distance_to_route_m(route, 12.901, 77.605) < 120
    det = DeviationDetector(threshold_m=60, consecutive=3)
    flags = [det.update(route, 12.901, 77.605)[0] for _ in range(3)]
    assert flags == [False, False, True]
    assert det.update(route, 12.90, 77.605)[0] is False       # back on route resets


def test_reroute_avoids_closure():
    a, b = 0, 13 * 14 + 13
    static = routing.static_route(G, a, b)
    st = TrafficState(G)
    st.add_incident(*g.node_latlon(G, static[len(static) // 2]), radius_m=350, kind="closure")
    base = routing.evaluate(G, st, static)
    best = min(routing.alternatives(G, st, a, b), key=lambda o: o.eta_s)
    assert base.closed_segments > 0 and best.closed_segments == 0
    assert best.eta_s < base.eta_s


def test_api_flow():
    from app.main import app
    c = TestClient(app)
    c.post("/reset")
    v = c.post("/dispatch", json={"vehicle_id": "A", "origin": [12.8967, 77.6018],
                                  "destination": [12.9357, 77.6408]}).json()
    lat, lon = v["route_coords"][6]
    r = c.post("/incidents", json={"lat": lat, "lon": lon, "radius_m": 350, "kind": "closure"}).json()
    assert r["vehicles_with_proposals"] == ["A"]
    assert c.get("/vehicles/A").json()["pending"]["chosen"]["closed_segments"] == 0
    c.post("/vehicles/A/approve")
    assert c.get("/stats").json()["reroutes_approved"] == 1


def test_audit_graph_dashboard():
    from app.main import app
    c = TestClient(app)
    c.post("/reset")
    c.post("/dispatch", json={"vehicle_id": "A", "origin": [12.8967, 77.6018], "destination": [12.9357, 77.6408]})
    assert c.get("/audit").json()[0]["kind"] == "dispatched"
    assert "dispatched" in c.get("/audit.csv").text
    assert len(c.get("/graph").json()) > 100
    assert "GeoRescue" in c.get("/").text


def test_hospital_aware():
    from app.main import app
    c = TestClient(app)
    c.post("/reset")
    r = c.post("/dispatch/auto", json={"vehicle_id": "A", "origin": [12.8967, 77.6018], "need": "trauma"}).json()
    first = r["hospital_id"]
    assert first and len(r["ranking"]) == 2
    out = c.post(f"/hospitals/{first}/beds", json={"beds": 0}).json()
    assert out["vehicles_with_proposals"] == ["A"]
    p = c.get("/vehicles/A").json()["pending"]
    assert p["new_hospital"]["id"] != first
    c.post("/vehicles/A/approve")
    assert c.get("/vehicles/A").json()["hospital_id"] == p["new_hospital"]["id"]


def test_offline_assets_and_benchmark():
    from app.main import app
    c = TestClient(app)
    assert c.get("/vendor/leaflet.js").status_code == 200
    assert c.get("/vendor/leaflet.css").status_code == 200
    assert c.get("/benchmark?n=10").json()["runs"] == 10


def test_cosmetic_wording():
    from app.main import app
    c = TestClient(app)
    c.post("/reset")
    r = c.post("/dispatch/auto", json={"vehicle_id": "A", "origin": [12.8967, 77.6018], "need": "trauma"}).json()
    c.post(f"/hospitals/{r['hospital_id']}/beds", json={"beds": 0})
    p = c.get("/vehicles/A").json()["pending"]
    texts = [t["text"] for t in p["trace"]]
    assert not any("still within tolerance" in t for t in texts)
    assert [t["step"] for t in p["trace"]] == list(range(1, len(texts) + 1))
    c.post("/vehicles/A/approve")
    lat, lon = c.get("/vehicles/A").json()["route_coords"][2]
    for _ in range(3):
        c.post("/vehicles/A/ping", json={"lat": lat + 0.0012, "lon": lon + 0.0012})
    d = c.get("/vehicles/A").json()["pending"]
    assert d and "saves 0:00" not in d["explanation"]


def test_config_endpoint():
    from app.main import app
    cfg = TestClient(app).get("/config").json()
    assert cfg["mode"] == "synthetic" and len(cfg["origins"]) >= 1 and len(cfg["center"]) == 2
