# GeoRescue AI

Detect -> Reason -> Reroute -> Explain -> Prove it worked.
Deterministic routing core (NetworkX/OSMnx + Shapely); the agent chooses between computed
candidates and explains using only computed numbers; a dispatcher approves every reroute.

## Run
Open http://localhost:8000 for the dispatcher dashboard (Dispatch -> Start -> Accident ahead -> Approve).

    pip install -r requirements.txt
    uvicorn app.main:app --reload            # API + WebSocket at /ws, docs at /docs
    python -m simulator.run_demo --scenario combo      # accident | congestion | wrong_turn | combo
    python -m benchmark.benchmark            # 100 simulated incidents: adaptive vs static
    pytest

Real Bengaluru roads: `pip install osmnx` then `USE_OSMNX=1 uvicorn app.main:app`.
Use `--manual` on the simulator to approve proposals from your own dashboard instead.

## Layout
    app/config.py      thresholds (deviation 60 m x 3 pings, min saving 30 s)
    app/graph.py       synthetic grid or OSMnx graph, nearest-node snap
    app/traffic.py     incidents -> per-edge delay/closure (swap in a TomTom/HERE poller)
    app/routing.py     k diverse routes, ETA/delay evaluation, static baseline
    app/deviation.py   Shapely distance-to-route + debounce
    app/agent.py       tool registry, decision trace, grounded explanation
    app/hospitals.py   specialty + capacity + live-ETA destination ranking
    app/store.py       SQLite audit log + CSV export
    app/static/        dispatcher dashboard (Leaflet, WebSocket)
    app/main.py        FastAPI: /dispatch /ping /incidents /approve /reject /stats /ws
    simulator/         deterministic scenario replay
    benchmark/         adaptive vs static, reports mean/median/p10/p90/worst

## Honest limits (put these on a slide)
Traffic is simulated; baseline penalises a closed segment by 180 s (config.CLOSURE_PENALTY_S);
synthetic grid produces tied ETAs; nearest-node snap is O(N); state is in-memory, single process.

## Hospital-aware demo
Dispatch (choose Trauma) -> Start -> click *Hospital full*: the agent proposes a destination change with a new route.
Hospitals are synthetic; ranking = live ETA + 120 s crowding penalty under 3 free beds (`app/hospitals.py`).

## Offline
Leaflet is bundled in app/static/vendor. The map defaults to schematic mode (no internet needed); the *Street map* button adds OSM tiles when online.

## Change locations
Edit `locations.json` (center, start points, hospitals with specialties and beds), then run with `USE_OSMNX=1`.
Look up coordinates for any place: `python -m tools.geocode "Jayadeva Hospital, Bengaluru"` (needs internet + osmnx).
The road download radius adapts to cover all listed places (4-9 km); fewer/closer places = faster start.
Hospital specialties and beds in the preset are illustrative assumptions. Without USE_OSMNX the synthetic grid demo is used.
