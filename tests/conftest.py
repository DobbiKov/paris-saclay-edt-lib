"""Offline fixtures: a fake requests.Session that replays canned Celcat/CAS responses (synthetic data)."""
import json

import pytest
import requests

from saclay_edt import CelcatClient

EVENT = {
    "id": "e1", "start": "2026-10-05T08:00:00", "end": "2026-10-05T09:30:00", "allDay": False,
    "description": "Cours Magistral (CM)\r\n\r\n<br />\r\n\r\nAlg&#232;bre\r\n\r\n<br />\r\n\r\nSalle A\r\n\r\n<br />\r\n\r\nG1\r\n\r\n<br />\r\n\r\nJane Doe\r\n",
    "eventCategory": "Cours Magistral (CM)", "modules": ["MATH1"], "sites": ["Site A"],
    "department": "Dept X", "faculty": "Fac X",
}
HOLIDAY = {
    "id": "h1", "start": "2026-11-01T07:00:00", "end": None, "allDay": True,
    "description": "jour f&#233;ri&#233;\r\n", "eventCategory": "jour férié", "modules": None, "sites": None,
    "department": None, "faculty": None,
}
SIDEBAR = {"elements": [
    {"label": "Event category", "content": "Cours Magistral (CM)", "federationId": None, "entityType": 0, "isNotes": False},
    {"label": "Module", "content": "Algèbre", "federationId": "MATH1", "entityType": 100, "isNotes": False},
    {"label": "Room", "content": "Salle A", "federationId": "A", "entityType": 102, "isNotes": False},
    {"label": "Group", "content": "G1", "federationId": "G1", "entityType": 103, "isNotes": False},
    {"label": "Notes", "content": "(30)", "federationId": None, "entityType": 0, "isNotes": True},
]}


class FakeResponse:
    def __init__(self, body="", status=200, ctype="application/json; charset=utf-8", url="https://x/"):
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.status_code = status
        self.headers = {"content-type": ctype}
        self.url = url

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(self.status_code)


class FakeSession:
    """Routes (METHOD, path-suffix) -> FakeResponse or callable(params, data)."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []
        self.cookies = requests.cookies.RequestsCookieJar()
        self.headers = {}

    def request(self, method, url, params=None, data=None, headers=None, timeout=None):
        self.calls.append((method, url, params, data))
        for (m, suffix), handler in self.routes.items():
            if m == method and url.endswith(suffix):
                return handler(params, data) if callable(handler) else handler
        raise AssertionError(f"unexpected request {method} {url}")


@pytest.fixture
def make_client(tmp_path):
    def _make(routes, **kw):
        def no_credentials():
            raise AssertionError("credentials requested in an offline test")

        c = CelcatClient("sciences", session_file=tmp_path / "s.json", credentials=kw.pop("credentials", no_credentials))
        c.session = FakeSession(routes)
        return c

    return _make
