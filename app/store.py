"""SQLite audit log: every dispatch, incident, proposal and decision (compliance trail)."""
import csv, io, json, os, sqlite3, threading, time

_lock = threading.Lock()
_db = sqlite3.connect(os.getenv("GEORESCUE_DB", "georescue.db"), check_same_thread=False)
_db.execute("create table if not exists audit(id integer primary key, ts real, vehicle text, kind text, detail text)")


def log(vehicle, kind, **detail):
    with _lock:
        _db.execute("insert into audit(ts,vehicle,kind,detail) values(?,?,?,?)",
                    (time.time(), vehicle, kind, json.dumps(detail, default=str)))
        _db.commit()


def recent(n=100):
    with _lock:
        rows = _db.execute("select id,ts,vehicle,kind,detail from audit order by id desc limit ?", (n,)).fetchall()
    return [{"id": r[0], "ts": r[1], "vehicle": r[2], "kind": r[3], "detail": json.loads(r[4])} for r in rows]


def to_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "timestamp_utc", "vehicle", "event", "detail"])
    for r in reversed(recent(100000)):
        w.writerow([r["id"], time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["ts"])), r["vehicle"], r["kind"], json.dumps(r["detail"])])
    return out.getvalue()


def clear():
    with _lock:
        _db.execute("delete from audit")
        _db.commit()
