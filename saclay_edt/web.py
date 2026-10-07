"""Local web UI: `python3 -m saclay_edt.web` then open http://127.0.0.1:8000.

Serves static/index.html plus a small JSON API on top of CelcatClient (it reuses .session.json and
never prompts: if the CAS session expired it answers 401 and you re-login from a terminal).
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .auth import AuthError
from .client import ENTITIES, ApiError, CelcatClient, Event, _read_dotenv

STATIC = Path(__file__).parent / "static"
MAX_RANGE_DAYS = 62

_clients: dict[str, CelcatClient] = {}
_details_cache: dict[tuple[str, str], dict] = {}
_lock = threading.Lock()


def _env_credentials() -> tuple[str, str]:
    """Non-interactive credentials (environment / .env only); the web server must never block on input()."""
    env = _read_dotenv(Path(".env"))
    user = os.environ.get("SACLAY_USERNAME") or env.get("SACLAY_USERNAME")
    pwd = os.environ.get("SACLAY_PASSWORD") or env.get("SACLAY_PASSWORD")
    if not (user and pwd):
        raise AuthError("Session expired. Log in from a terminal (python3 example.py) and reload this page.")
    return user, pwd


def get_client(entity: str) -> CelcatClient:
    if entity not in ENTITIES:
        raise KeyError(entity)
    with _lock:
        if entity not in _clients:
            _clients[entity] = CelcatClient(entity, credentials=_env_credentials)
        return _clients[entity]


def serialize(e: Event) -> dict:
    return {
        "id": e.id,
        "start": e.start.isoformat(),
        "end": e.end.isoformat() if e.end else None,
        "allDay": e.all_day,
        "category": e.category,
        "modules": e.modules,
        "moduleNames": e.module_names,
        "rooms": e.rooms,
        "groups": e.groups,
        "staff": e.staff,
        "sites": e.sites,
        "notes": e.notes,
        "details": e.details,
    }


def timetable(entity: str, group: str, start: date, end: date, details: bool) -> list[dict]:
    client = get_client(entity)
    events = client.get_events(group, start, end)
    if details:
        todo = []
        for e in events:
            cached = _details_cache.get((entity, e.id))
            if cached:
                e.module_names, e.rooms, e.groups, e.staff, e.notes = (cached[k] for k in ("m", "r", "g", "s", "n"))
            elif not e.all_day:
                todo.append(e)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(client.fill_details, todo))
        for e in todo:
            _details_cache[(entity, e.id)] = {"m": e.module_names, "r": e.rooms, "g": e.groups, "s": e.staff, "n": e.notes}
    return [serialize(e) for e in events]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet, and never log query strings
        pass

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if url.path == "/api/entities":
                return self._json(200, list(ENTITIES))
            if url.path == "/api/groups":
                term = q.get("q", "").strip()
                if not term:
                    return self._json(200, [])
                groups = get_client(q["entity"]).list_groups(term)[:200]
                return self._json(200, [{"id": g.id, "text": g.text, "department": g.department} for g in groups])
            if url.path == "/api/timetable":
                start, end = date.fromisoformat(q["start"]), date.fromisoformat(q["end"])
                if not 0 < (end - start).days <= MAX_RANGE_DAYS:
                    return self._json(400, {"error": f"range must be 1..{MAX_RANGE_DAYS} days"})
                return self._json(200, timetable(q["entity"], q["group"], start, end, q.get("details") == "1"))
            self._json(404, {"error": "not found"})
        except (KeyError, ValueError) as e:
            self._json(400, {"error": f"bad request: {e}"})
        except AuthError as e:
            self._json(401, {"error": str(e)})
        except ApiError as e:
            self._json(502, {"error": str(e)})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)  # localhost only: it exposes your session
    print(f"http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
