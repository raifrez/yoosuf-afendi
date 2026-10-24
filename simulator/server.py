"""Local API for the dashboard. Loads the model once; every edit reruns it on a copy.

  uv run python -m simulator.server [--port 8765] [--atolls F Dh GA GDh]

  GET  /data/network.json                     the ferry network export (data/export/network.json)
  GET  /api/meta                              region, categories, schools, hospitals, parameters + labels, sources
  GET  /api/baseline                          scores per island x category and atoll x category
  POST /api/scenario                          body: {"timetable_edits": [{"trip_id", "shift_minutes"}],
                                                     "default_session": {"start": "HH:MM", "end": "HH:MM"},
                                                     "school_sessions": {facility_id: {"start", "end"}}}
                                              -> {"scores", "compare"}; becomes the current scenario
  GET  /api/residents?island_id=&category=&outcome=&limit=   residents with baseline/current outcomes
  GET  /api/resident/<person_id>              itineraries, baseline and current scenario
  GET  /api/demo                              the demo resident and scenario
  GET  /api/sweep?trip_id=                    gained/lost for that sailing shifted -120..+120 min (15-min steps)

Dashboard (dashboard/) endpoints, in the record shapes of simulator/dashboard.py. A scenario
body is {"shifts": {trip_id: minutes}, "added_stops": [{island_id, route_id, a, b}],
"default_session": {start, end}, "school_sessions": {facility_id: {start, end}}}:
  GET  /api/dash/meta                         atolls, categories, rules with labels, islands, sources
  POST /api/dash/run      {scenario, categories}  -> {run, compare, trips, added_stops}; becomes current
  GET  /api/dash/journey?group_id=&which=baseline|current   one group's full itinerary
  POST /api/dash/optimize {scenario, atolls}  -> {job_id}   Find better times, one atoll after another
  POST /api/dash/add_stop {scenario, island_id} -> {job_id} best placement for a new stop
  GET  /api/dash/job/<job_id>                 progress, and the result when done

Single-user: the current scenario is kept in memory. The baseline never changes.
"""

import argparse
import gzip
import itertools
import json
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import parse_qs, urlparse

from pipeline.build_gtfs import to_minutes
from pipeline.export_web import EXPORT
from pipeline.stops import DATA
from simulator.dashboard import HOSPITAL, Dashboard
from simulator.demo_story import demo_story
from simulator.model import AddedStop, Model, Scenario
from simulator.optimize import best_stop, run_search
from simulator.schools import DEFAULT_SESSION, Session
from simulator.timetable import TripShift

SWEEP_MINUTES = range(-120, 121, 15)
ROOT = DATA.parent


def parse_session(value: dict) -> Session:
    return Session(to_minutes(value["start"] + ":00"), to_minutes(value["end"] + ":00"))


def parse_scenario(body: dict) -> Scenario:
    """Raises ValueError/KeyError/TypeError on bad input."""
    edits = tuple(TripShift(str(e["trip_id"]), e["shift_minutes"]) for e in body.get("timetable_edits", []))
    edits += tuple(TripShift(str(t), m) for t, m in (body.get("shifts") or {}).items() if m)
    for e in edits:
        if not isinstance(e.shift_minutes, int) or isinstance(e.shift_minutes, bool):
            raise ValueError(f"shift for {e.trip_id} must be an integer number of minutes")
    default = parse_session(body["default_session"]) if body.get("default_session") else DEFAULT_SESSION
    schools = tuple(sorted((str(f), parse_session(v)) for f, v in (body.get("school_sessions") or {}).items()))
    added = tuple(AddedStop(str(a["island_id"]), str(a["route_id"]), str(a["a"]), a.get("b") and str(a["b"]))
                  for a in body.get("added_stops") or [])
    return Scenario(edits, default, schools, added)


class Api:
    def __init__(self, model: Model):
        self.model, self.lock = model, Lock()
        self.current = model.baseline
        self.dash = Dashboard(model)
        self.jobs: dict[str, dict] = {}
        self._ids = itertools.count(1)

    # --- dashboard -----------------------------------------------------------------
    def dash_meta(self) -> dict:
        meta = self.model.meta()
        meta["categories"] = [{"id": HOSPITAL, "note": "Hospital visit, all ages: the three hospital categories together."},
                              *meta["categories"]]
        return meta

    def dash_run(self, body: dict) -> dict:
        scenario = parse_scenario(body.get("scenario") or {})
        categories = body.get("categories") or [HOSPITAL]
        run = self.model.baseline if scenario.is_baseline else self.model.run(scenario)
        with self.lock:
            self.current = run
        return {"scenario": scenario.as_dict(), "run": self.dash.run_payload(run, categories),
                "compare": None if scenario.is_baseline else self.dash.compare_payload(run, categories),
                "trips": self.dash.changed_trips(run), "added_stops": self.dash.added_stops(run)}

    def dash_journey(self, query: dict) -> dict:
        run = self.current if query.get("which", ["current"])[0] == "current" else self.model.baseline
        return self.dash.journey(run, query["group_id"][0])

    def start_job(self, kind: str, body: dict) -> dict:
        scenario = parse_scenario(body.get("scenario") or {})
        if kind == "optimize":
            atolls = [str(a) for a in body.get("atolls") or []]
            if not atolls or any(a not in self.model.atolls for a in atolls):
                raise ValueError(f"atolls must be a non-empty list of {list(self.model.atolls)}")
        else:
            island_id = str(body["island_id"])
            if island_id not in self.model.region:
                raise ValueError(f"unknown island_id {island_id}")
        job_id = f"{kind}-{next(self._ids)}"
        job = self.jobs[job_id] = {"job_id": job_id, "kind": kind, "done": False, "progress": None, "result": None, "error": None}

        def work():
            try:
                if kind == "optimize":
                    per, shifts = [], {}
                    for i, atoll in enumerate(atolls):
                        def progress(step, atoll=atoll, i=i):
                            job["progress"] = {**step, "atoll": atoll, "atoll_index": i, "atolls": len(atolls)}
                        found = run_search(self.model, scenario, atoll, on_progress=progress)
                        per.append({"atoll": atoll, **found})
                        shifts.update(found["shifts"])
                    job["result"] = {"per_atoll": per, "shifts": shifts}
                else:
                    job["result"] = best_stop(self.model, scenario, island_id,
                                              lambda step: job.__setitem__("progress", step))
            except Exception as e:  # reported to the client, never crashes the server
                job["error"] = f"{type(e).__name__}: {e}"
            job["done"] = True

        threading.Thread(target=work, daemon=True).start()
        return {"job_id": job_id}

    def job(self, job_id: str) -> dict:
        return self.jobs[job_id]

    def scenario(self, body: dict) -> dict:
        scenario = parse_scenario(body)
        known = {s["facility_id"] for s in self.model.meta()["schools"]}
        unknown = [f for f, _ in scenario.school_sessions if f not in known]
        if unknown:
            raise ValueError(f"unknown school facility_id: {unknown}")
        run = self.model.run(scenario)
        with self.lock:
            self.current = run
        return {"scores": self.model.scores_payload(run), "compare": self.model.compare_payload(run)}

    def residents(self, query: dict) -> list[dict]:
        q = {k: v[0] for k, v in query.items()}
        return self.model.residents_list(self.current, q["island_id"], q["category"], q.get("outcome"),
                                         min(int(q.get("limit", 50)), 500))

    def sweep(self, query: dict) -> list[dict]:
        trip_id = query["trip_id"][0]
        self.model.timetable.trip(trip_id)  # unknown trip -> KeyError
        out = []
        for shift in SWEEP_MINUTES:
            try:
                run = self.model.run(Scenario((TripShift(trip_id, shift),)))
            except ValueError:  # crosses midnight
                continue
            c = self.model.compare_payload(run)
            out.append({"shift_minutes": shift, "gained": c["gained"], "lost": c["lost"]})
        return out

    def resident(self, person_id: str) -> dict:
        if person_id not in self.model.residents:
            raise KeyError(f"unknown person_id {person_id}")
        return self.model.resident_payload(person_id, self.current)


def handler(api: Api, meta: dict, baseline: dict, demo: dict, dash_meta: dict):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, payload, content_type="application/json"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            gzipped = len(body) > 2048 and "gzip" in self.headers.get("Accept-Encoding", "")
            if gzipped:
                body = gzip.compress(body, compresslevel=5)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if gzipped:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, path: str):
            root = (ROOT / "dashboard").resolve()
            target = (root / (path.lstrip("/") or "index.html")).resolve()
            if root not in target.parents and target != root or not target.is_file():
                return self._error(HTTPStatus.NOT_FOUND, f"no file {path}")
            types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                     ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml"}
            self._send(200, target.read_bytes(), types.get(target.suffix, "application/octet-stream"))

        def _error(self, status: int, message: str):
            self._send(status, {"error": message})

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            try:
                if not url.path.startswith(("/api/", "/data/")):
                    return self._static(url.path)
                if url.path == "/data/network.json":
                    self._send(200, (EXPORT / "network.json").read_bytes())
                elif url.path == "/api/meta":
                    self._send(200, meta)
                elif url.path == "/api/baseline":
                    self._send(200, baseline)
                elif url.path == "/api/demo":
                    self._send(200, demo)
                elif url.path == "/api/dash/meta":
                    self._send(200, dash_meta)
                elif url.path == "/api/dash/journey":
                    self._send(200, api.dash_journey(parse_qs(url.query)))
                elif url.path.startswith("/api/dash/job/"):
                    self._send(200, api.job(url.path.rsplit("/", 1)[1]))
                elif url.path == "/api/sweep":
                    self._send(200, api.sweep(parse_qs(url.query)))
                elif url.path == "/api/residents":
                    self._send(200, api.residents(parse_qs(url.query)))
                elif url.path.startswith("/api/resident/"):
                    self._send(200, api.resident(url.path.rsplit("/", 1)[1]))
                else:
                    self._error(HTTPStatus.NOT_FOUND, f"no route {url.path}")
            except KeyError as e:
                self._error(HTTPStatus.BAD_REQUEST, f"missing or unknown: {e}")
            except ValueError as e:
                self._error(HTTPStatus.BAD_REQUEST, str(e))

        def do_POST(self):  # noqa: N802
            path = urlparse(self.path).path
            routes = {"/api/scenario": api.scenario, "/api/dash/run": api.dash_run,
                      "/api/dash/optimize": lambda b: api.start_job("optimize", b),
                      "/api/dash/add_stop": lambda b: api.start_job("add_stop", b)}
            if path not in routes:
                return self._error(HTTPStatus.NOT_FOUND, f"no route {self.path}")
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                self._send(200, routes[path](body))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
                self._error(HTTPStatus.BAD_REQUEST, f"invalid scenario: {e}")

        def log_message(self, fmt, *args):
            sys.stderr.write("%s %s\n" % (self.command, self.path))

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--atolls", nargs="+", default=None, help="default: every atoll with a ferry stop")
    args = ap.parse_args(argv)
    model = Model(args.atolls)
    api = Api(model)
    meta, baseline, demo = model.meta(), model.scores_payload(model.baseline), demo_story(model)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(api, meta, baseline, demo, api.dash_meta()))
    print(f"Simulator API on http://127.0.0.1:{args.port} for atolls {' '.join(model.atolls)} "
          f"({len(model.residents)} residents)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
