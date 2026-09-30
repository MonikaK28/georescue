"""Dispatch agent: observe -> call tools -> decide -> explain.
Deterministic tools do all the math; the agent only chooses and narrates.
To add an LLM: give it the tool registry below and the `facts` dict, then
validate that every number in its text appears in `facts` (see explain())."""
from dataclasses import dataclass, field
from . import config, routing


def mmss(s):
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


@dataclass
class Decision:
    vehicle_id: str
    trigger: str
    recommended: bool
    trace: list = field(default_factory=list)
    baseline: routing.RouteOption | None = None
    chosen: routing.RouteOption | None = None
    alternatives: list = field(default_factory=list)
    time_saved_s: float = 0.0
    explanation: str = ""
    new_hospital: dict | None = None


class DispatchAgent:
    def __init__(self, G, state):
        self.G, self.state = G, state
        self.tools = {                                   # the agent's tool registry
            "static_route": lambda a, b: routing.evaluate(G, state, routing.static_route(G, a, b), "current"),
            "get_route_alternatives": lambda a, b: routing.alternatives(G, state, a, b, k=3),
        }

    def replan(self, vehicle_id, here, dest, trigger, detail="") -> Decision:
        d = Decision(vehicle_id, trigger, False)
        log = lambda kind, text: d.trace.append({"step": len(d.trace) + 1, "kind": kind, "text": text})

        log("observe", f"{trigger}: {detail}".strip(": "))
        d.baseline = self.tools["static_route"](here, dest)
        b = d.baseline
        log("tool", f"static_route -> ETA {mmss(b.eta_s)}, {b.closed_segments} closed and "
                    f"{b.congested_segments} congested segments")
        d.alternatives = self.tools["get_route_alternatives"](here, dest)
        if not d.alternatives:
            log("decide", "No viable route found; escalate to dispatcher.")
            d.explanation = "No viable route found under current conditions."
            return d
        for o in d.alternatives:
            log("tool", f"Route {o.id}: ETA {mmss(o.eta_s)}, delay {round(o.delay_s)}s, "
                        f"{round(o.distance_m / 1000, 1)} km")

        d.chosen = min(d.alternatives, key=lambda o: o.eta_s)
        d.time_saved_s = round(b.eta_s - d.chosen.eta_s, 1)
        d.recommended = (trigger == "deviation" or d.time_saved_s >= config.MIN_SAVING_S
                         or b.closed_segments > 0)
        for o in d.alternatives:
            if o.id != d.chosen.id:
                diff = round(o.eta_s - d.chosen.eta_s)
                log("decide", f"Route {o.id} not chosen: " + (f"{diff}s slower." if diff >= 1 else "equal ETA, kept first."))
        log("decide", f"Recommend Route {d.chosen.id}." if d.recommended
            else "Current route is still within tolerance; no change.")
        d.explanation = self.explain(d)
        return d

    def explain(self, d: Decision) -> str:
        """Template explanation built only from computed values (always grounded)."""
        b, c = d.baseline, d.chosen
        if d.trigger == "deviation" and d.time_saved_s < config.MIN_SAVING_S:
            return (f"Vehicle left its planned path. Route {c.id} puts it back on the fastest available "
                    f"route: ETA {mmss(c.eta_s)}.")
        why = []
        if b.closed_segments:
            why.append(f"the current route crosses {b.closed_segments} closed segment(s)")
        if b.congested_segments:
            why.append(f"{b.congested_segments} congested segment(s) add {round(b.delay_s)}s of delay")
        if d.trigger == "deviation":
            why.insert(0, "the vehicle left its planned path")
        reason = "; ".join(why) or "no significant disruption found"
        return (f"Route {c.id} recommended: ETA {mmss(c.eta_s)} vs {mmss(b.eta_s)} on the current route "
                f"(saves {mmss(max(d.time_saved_s, 0))}). Because {reason}.")
