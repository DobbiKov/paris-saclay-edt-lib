import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from saclay_edt import AuthError, web
from saclay_edt.client import ENTITIES, _parse_event

from conftest import EVENT, HOLIDAY


class FakeClient:
    def __init__(self):
        self.group_terms = []

    def list_groups(self, term):
        self.group_terms.append(term)
        return [type("G", (), {"id": "G1", "text": "G1 text", "department": "Dept"})()]

    def get_events(self, group, start, end):
        return [_parse_event(EVENT), _parse_event(HOLIDAY)]

    def fill_details(self, e):
        e.module_names, e.rooms, e.groups, e.staff, e.notes = ["Algèbre"], ["Salle A"], ["G1"], ["Jane Doe"], "(30)"
        return e


@pytest.fixture
def server(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(web, "get_client", lambda entity: fake if entity in ENTITIES else (_ for _ in ()).throw(KeyError(entity)))
    web._details_cache.clear()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", fake
    srv.shutdown()


def get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.headers["Content-Type"], r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers["Content-Type"], e.read()


def test_serves_index_and_entities(server):
    base, _ = server
    status, ctype, body = get(base + "/")
    assert status == 200 and ctype.startswith("text/html") and b"Saclay Timetable" in body
    assert json.loads(get(base + "/api/entities")[2])[0] == "sciences"  # default entity first


def test_groups_endpoint(server):
    base, fake = server
    assert json.loads(get(base + "/api/groups?entity=sciences&q=G")[2]) == [{"id": "G1", "text": "G1 text", "department": "Dept"}]
    assert json.loads(get(base + "/api/groups?entity=sciences&q=")[2]) == []  # empty term never reaches the server (HTTP 500)
    assert fake.group_terms == ["G"]


def test_timetable_with_details_and_cache(server):
    base, _ = server
    url = base + "/api/timetable?entity=sciences&group=G1&start=2026-10-05&end=2026-10-12&details=1"
    events = json.loads(get(url)[2])
    by_id = {e["id"]: e for e in events}
    assert by_id["e1"]["rooms"] == ["Salle A"] and by_id["e1"]["end"] == "2026-10-05T09:30:00"
    assert by_id["h1"]["allDay"] and by_id["h1"]["end"] is None and by_id["h1"]["rooms"] == []  # all-day: no detail lookup
    assert ("sciences", "e1") in web._details_cache and ("sciences", "h1") not in web._details_cache


def test_bad_requests(server):
    base, _ = server
    assert get(base + "/api/timetable?entity=sciences&group=G1&start=2026-10-05&end=2027-10-05")[0] == 400  # range too long
    assert get(base + "/api/timetable?entity=sciences&group=G1&start=nope&end=2026-10-12")[0] == 400
    assert get(base + "/api/groups?entity=unknown&q=x")[0] == 400
    assert get(base + "/api/groups?q=x")[0] == 400  # missing entity
    assert get(base + "/nope")[0] == 404


def test_expired_session_is_401_with_message(server, monkeypatch):
    base, fake = server
    monkeypatch.setattr(fake, "list_groups", lambda term: (_ for _ in ()).throw(AuthError("Session expired")))
    status, _, body = get(base + "/api/groups?entity=sciences&q=x")
    assert status == 401 and json.loads(body)["error"] == "Session expired"


def test_server_credentials_never_prompt(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.delenv("SACLAY_USERNAME", raising=False)
    monkeypatch.delenv("SACLAY_PASSWORD", raising=False)
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("web server must not prompt"))
    with pytest.raises(AuthError):
        web._env_credentials()
