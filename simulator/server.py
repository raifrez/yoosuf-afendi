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

Single-user: the current scenario is kept in memory. The baseline never changes.
"""

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import parse_qs, urlparse

from pipeline.build_gtfs import to_minutes
from pipeline.export_web import EXPORT
from simulator.demo_story import demo_story
from simulator.model import DEMO_ATOLLS, Model, Scenario
from simulator.schools import DEFAULT_SESSION, Session
from simulator.timetable import TripShift

SWEEP_MINUTES = range(-120, 121, 15)


def parse_session(value: dict) -> Session:
    return Session(to_minutes(value["start"] + ":00"), to_minutes(value["end"] + ":00"))


def parse_scenario(body: dict) -> Scenario:
    """Raises ValueError/KeyError/TypeError on bad input."""
    edits = tuple(TripShift(str(e["trip_id"]), e["shift_minutes"]) for e in body.get("timetable_edits", []))
    for e in edits:
        if not isinstance(e.shift_minutes, int):
            raise ValueError(f"shift_minutes for {e.trip_id} must be an integer")
    default = parse_session(body["default_session"]) if body.get("default_session") else DEFAULT_SESSION
    schools = tuple(sorted((str(f), parse_session(v)) for f, v in (body.get("school_sessions") or {}).items()))
    return Scenario(edits, default, schools)


class Api:
    def __init__(self, model: Model):
        self.model, self.lock = model, Lock()
        self.current = model.baseline

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


def handler(api: Api, meta: dict, baseline: dict, demo: dict):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, payload, content_type="application/json"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str):
            self._send(status, {"error": message})

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            try:
                if url.path == "/data/network.json":
                    self._send(200, (EXPORT / "network.json").read_bytes())
                elif url.path == "/api/meta":
                    self._send(200, meta)
                elif url.path == "/api/baseline":
                    self._send(200, baseline)
                elif url.path == "/api/demo":
                    self._send(200, demo)
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
            if urlparse(self.path).path != "/api/scenario":
                return self._error(HTTPStatus.NOT_FOUND, f"no route {self.path}")
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                self._send(200, api.scenario(body))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
                self._error(HTTPStatus.BAD_REQUEST, f"invalid scenario: {e}")

        def log_message(self, fmt, *args):
            sys.stderr.write("%s %s\n" % (self.command, self.path))

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--atolls", nargs="+", default=list(DEMO_ATOLLS))
    args = ap.parse_args(argv)
    model = Model(args.atolls)
    api = Api(model)
    meta, baseline, demo = model.meta(), model.scores_payload(model.baseline), demo_story(model)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(api, meta, baseline, demo))
    print(f"Simulator API on http://127.0.0.1:{args.port} for atolls {' '.join(args.atolls)} "
          f"({len(model.residents)} residents)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
