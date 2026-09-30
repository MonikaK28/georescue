"""GeoRescue AI backend.  Run:  uvicorn app.main:app --reload
Flow: /dispatch -> /vehicles/{id}/ping (deviation) or /incidents -> agent proposal
-> dashboard (WebSocket) -> /vehicles/{id}/approve | /reject   (human in the loop)."""
from dataclasses import asdict, dataclass, field
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pathlib import Path
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from . import config, graph as g, hospitals, routing, store
from .agent import DispatchAgent, Decision, mmss
from .deviation import DeviationDetector, distance_to_route_m
from .traffic import TrafficState

G = g.load_graph()
traffic = TrafficState(G)
agent = DispatchAgent(G, traffic)
hospitals.init(G)


@dataclass
class Vehicle:
    id: str
    dest_node: int
    lat: float
    lon: float
    route_nodes: list
    route_coords: list
    status: str = "en_route"
    pending: Decision | None = None
    need: str | None = None
    hospital_id: str | None = None
    detector: DeviationDetector = field(default_factory=DeviationDetector)


vehicles: dict[str, Vehicle] = {}
stats = {"incidents": 0, "reroutes_approved": 0, "reroutes_rejected": 0, "time_saved_s": 0.0}


class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def broadcast(self, event: dict):
        for ws in list(self.clients):
            try:
                await ws.send_json(event)
            except Exception:
                self.clients.discard(ws)


hub = Hub()
app = FastAPI(title="GeoRescue AI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class DispatchReq(BaseModel):
    vehicle_id: str
    origin: tuple[float, float]         # (lat, lon)
    destination: tuple[float, float]


class PingReq(BaseModel):
    lat: float
    lon: float


class IncidentReq(BaseModel):
    lat: float
    lon: float
    radius_m: float = 300
    kind: str = "congestion"            # "closure" | "congestion"
    factor: float = 3.0


def vehicle_view(v: Vehicle) -> dict:
    return {"id": v.id, "lat": v.lat, "lon": v.lon, "status": v.status,
            "route_coords": v.route_coords, "route_nodes": v.route_nodes,
            "need": v.need, "hospital_id": v.hospital_id,
            "pending": asdict(v.pending) if v.pending else None}


def remaining_nodes(v: Vehicle) -> list:
    """Planned nodes from the point nearest the vehicle onward."""
    if not v.route_coords:
        return []
    idx = min(range(len(v.route_coords)),
              key=lambda i: g.haversine_m(v.lat, v.lon, *v.route_coords[i]))
    return v.route_nodes[idx:]


def consider_hospital_switch(v: Vehicle, here: int, d: Decision):
    """Destination-level reasoning: is another eligible hospital now clearly better?"""
    if not v.need or not d.baseline:
        return
    rk = hospitals.rank(G, traffic, here, v.need)
    if not rk or rk[0]["id"] == v.hospital_id:
        return
    best = rk[0]
    cur = next((r for r in rk if r["id"] == v.hospital_id), None)
    if cur is not None and best["score_s"] > cur["score_s"] - config.MIN_SAVING_S:
        return
    opts = routing.alternatives(G, traffic, here, best["node"], k=1)
    if not opts:
        return
    reason = ("current hospital has no free beds" if cur is None
              else f"{round(cur['score_s'] - best['score_s'])}s faster including capacity")
    d.trace = [t for t in d.trace if not t["text"].startswith("Current route is still within tolerance")]
    d.new_hospital, d.chosen = best, opts[0]
    d.time_saved_s = round(d.baseline.eta_s - opts[0].eta_s, 1)
    d.recommended = True
    d.trace.append({"step": len(d.trace) + 1, "kind": "tool",
                    "text": "rank_hospitals -> " + ", ".join(f"{r['name']} {mmss(r['eta_s'])}/{r['beds']} beds" for r in rk)})
    d.trace.append({"step": len(d.trace) + 1, "kind": "decide", "text": f"Switch destination to {best['name']} ({reason})."})
    for n, t in enumerate(d.trace, 1):
        t["step"] = n
    d.explanation = f"Redirect to {best['name']} ({reason}). New ETA {mmss(opts[0].eta_s)}."


async def propose(v: Vehicle, trigger: str, detail: str) -> Decision:
    here = g.nearest_node(G, v.lat, v.lon)
    d = agent.replan(v.id, here, v.dest_node, trigger, detail)
    consider_hospital_switch(v, here, d)
    if d.recommended:
        v.pending = d
        store.log(v.id, "proposal", trigger=trigger, chosen=d.chosen.id, time_saved_s=d.time_saved_s, explanation=d.explanation)
        await hub.broadcast({"type": "proposal", "vehicle": v.id, **asdict(d)})
    return d


@app.post("/dispatch")
async def dispatch(req: DispatchReq):
    src, dst = g.nearest_node(G, *req.origin), g.nearest_node(G, *req.destination)
    opts = routing.alternatives(G, traffic, src, dst, k=1)
    if not opts:
        raise HTTPException(404, "No route between origin and destination")
    r = opts[0]
    v = Vehicle(req.vehicle_id, dst, *g.node_latlon(G, src), r.nodes, r.coords)
    vehicles[v.id] = v
    store.log(v.id, "dispatched", eta_s=r.eta_s)
    await hub.broadcast({"type": "dispatched", "vehicle": vehicle_view(v), "eta_s": r.eta_s})
    return vehicle_view(v) | {"eta_s": r.eta_s}


@app.post("/vehicles/{vid}/ping")
async def ping(vid: str, p: PingReq):
    v = vehicles.get(vid) or (_ for _ in ()).throw(HTTPException(404, "Unknown vehicle"))
    v.lat, v.lon = p.lat, p.lon
    if g.haversine_m(p.lat, p.lon, *g.node_latlon(G, v.dest_node)) < 40:
        v.status = "arrived"
    await hub.broadcast({"type": "position", "vehicle": v.id, "lat": p.lat, "lon": p.lon, "status": v.status})
    if v.status != "en_route" or v.pending:
        return {"deviating": False, "proposal": bool(v.pending)}
    deviating, dist = v.detector.update(v.route_coords, p.lat, p.lon)
    if deviating:
        d = await propose(v, "deviation", f"{round(dist)} m off planned route")
        return {"deviating": True, "distance_m": round(dist), "proposal": bool(v.pending)}
    return {"deviating": False, "distance_m": round(dist), "proposal": False}


@app.post("/incidents")
async def add_incident(req: IncidentReq):
    inc = traffic.add_incident(req.lat, req.lon, req.radius_m, req.kind, req.factor)
    stats["incidents"] += 1
    store.log("-", "incident", incident_kind=req.kind, lat=req.lat, lon=req.lon, radius_m=req.radius_m)
    await hub.broadcast({"type": "incident", **asdict(inc)})
    flagged = []
    for v in vehicles.values():
        if v.status != "en_route" or v.pending:
            continue
        rem = routing.evaluate(G, traffic, remaining_nodes(v))
        if rem.closed_segments or rem.congested_segments:
            await propose(v, "incident", f"{req.kind} near route")
            if v.pending:
                flagged.append(v.id)
    return {"incident": inc.id, "vehicles_with_proposals": flagged}


@app.post("/vehicles/{vid}/approve")
async def approve(vid: str):
    v = vehicles.get(vid)
    if not v or not v.pending:
        raise HTTPException(404, "No pending proposal")
    d, c = v.pending, v.pending.chosen
    v.route_nodes, v.route_coords, v.pending = c.nodes, c.coords, None
    if d.new_hospital:
        v.dest_node, v.hospital_id = d.new_hospital["node"], d.new_hospital["id"]
        store.log(vid, "destination_changed", hospital=d.new_hospital["id"])
    v.detector.reset()
    stats["reroutes_approved"] += 1
    store.log(vid, "approved", time_saved_s=d.time_saved_s)
    stats["time_saved_s"] += max(d.time_saved_s, 0)
    await hub.broadcast({"type": "route_updated", "vehicle": vid, "time_saved_s": d.time_saved_s,
                         "route_coords": c.coords, "hospital": d.new_hospital})
    return vehicle_view(v)


@app.post("/vehicles/{vid}/reject")
async def reject(vid: str):
    v = vehicles.get(vid)
    if not v or not v.pending:
        raise HTTPException(404, "No pending proposal")
    v.pending = None
    stats["reroutes_rejected"] += 1
    store.log(vid, "rejected")
    await hub.broadcast({"type": "proposal_rejected", "vehicle": vid})
    return {"ok": True}


@app.get("/vehicles")
def list_vehicles():
    return [vehicle_view(v) for v in vehicles.values()]


@app.get("/vehicles/{vid}")
def get_vehicle(vid: str):
    if vid not in vehicles:
        raise HTTPException(404, "Unknown vehicle")
    return vehicle_view(vehicles[vid])


@app.get("/stats")
def get_stats():
    return stats


@app.post("/reset")
def reset():
    vehicles.clear()
    traffic.clear()
    store.clear()
    hospitals.reset()
    for k in stats:
        stats[k] = 0 if k != "time_saved_s" else 0.0
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    hub.clients.add(ws)
    try:
        while True:
            await ws.receive_text()          # keep-alive; the dashboard only listens
    except WebSocketDisconnect:
        hub.clients.discard(ws)


@app.get("/audit")
def audit(n: int = 50):
    return store.recent(n)


@app.get("/audit.csv", response_class=PlainTextResponse)
def audit_csv():
    return PlainTextResponse(store.to_csv(), headers={"Content-Disposition": "attachment; filename=georescue_audit.csv"})


@app.get("/graph")
def graph_segments(limit: int = 6000):
    if config.USE_OSMNX:                 # real roads come from the street-map tiles instead
        return []
    seen, out = set(), []
    for u, v in G.edges:
        k = (min(u, v), max(u, v))
        if k in seen:
            continue
        seen.add(k)
        out.append([list(g.node_latlon(G, u)), list(g.node_latlon(G, v))])
        if len(out) >= limit:
            break
    return out


class AutoDispatchReq(BaseModel):
    vehicle_id: str
    origin: tuple[float, float]
    need: str = "trauma"                # trauma | cardiac | stroke | general


class BedsReq(BaseModel):
    beds: int


@app.get("/hospitals")
def list_hospitals():
    return [hospitals.public(h) for h in hospitals.HOSPITALS.values()]


@app.post("/dispatch/auto")
async def dispatch_auto(req: AutoDispatchReq):
    src = g.nearest_node(G, *req.origin)
    rk = hospitals.rank(G, traffic, src, req.need)
    if not rk:
        raise HTTPException(404, "No eligible hospital")
    best = rk[0]
    r = routing.alternatives(G, traffic, src, best["node"], k=1)[0]
    v = Vehicle(req.vehicle_id, best["node"], *g.node_latlon(G, src), r.nodes, r.coords,
                need=req.need, hospital_id=best["id"])
    vehicles[v.id] = v
    store.log(v.id, "dispatched", eta_s=r.eta_s, need=req.need, hospital=best["id"])
    await hub.broadcast({"type": "dispatched", "vehicle": vehicle_view(v), "eta_s": r.eta_s, "ranking": rk})
    return vehicle_view(v) | {"eta_s": r.eta_s, "ranking": rk}


@app.post("/hospitals/{hid}/beds")
async def set_beds(hid: str, req: BedsReq):
    h = hospitals.HOSPITALS.get(hid)
    if not h:
        raise HTTPException(404, "Unknown hospital")
    h["beds"] = max(0, req.beds)
    store.log("-", "hospital_beds", hospital=hid, beds=h["beds"])
    await hub.broadcast({"type": "hospital_update", **hospitals.public(h)})
    flagged = []
    for v in vehicles.values():
        if v.status == "en_route" and v.hospital_id == hid:
            await propose(v, "hospital_capacity", f"{h['name']} now has {h['beds']} free beds")
            if v.pending:
                flagged.append(v.id)
    return {"hospital": hospitals.public(h), "vehicles_with_proposals": flagged}


@app.get("/benchmark")
def run_benchmark(n: int = 100):
    """Adaptive vs static routing over n simulated incidents (runs in a worker thread)."""
    from benchmark.benchmark import run
    return run(min(max(n, 10), 300))


@app.get("/config")
def get_config():
    return {"mode": "osmnx" if config.USE_OSMNX else "synthetic", "center": list(config.CENTER),
            "origins": config.ORIGINS, "zoom": 13}


# Must be last: serves the dispatcher dashboard at http://localhost:8000/
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
