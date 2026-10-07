"""Client for the Celcat Calendar JSON endpoints used by edt.universite-paris-saclay.fr."""
from __future__ import annotations

import getpass
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator

from .auth import BASE_URL, DEFAULT_SESSION_FILE, AuthError, load_session, login, new_session, save_session

# Celcat entities (one calendar instance per faculty/institute) linked from the landing page.
ENTITIES = {
    "sciences": "Calendar_DEG_FSO_F2S",  # also STAPS, UFR Sceaux (droit/eco/gestion), pharmacie
    "iut_sceaux": "Calendar_IutSceaux",
    "iut_cachan": "Calendar_IutCachan",
    "medecine": "Calendar_UfrKB",
}

# resType values used by the API.
MODULE, STAFF, ROOM, GROUP, STUDENT = 100, 101, 102, 103, 104

_CHUNK_DAYS = 31


def _read_dotenv(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser (no dependency); missing file -> {}."""
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("\"'")
    return out


def credentials_from_env(dotenv: Path | str = ".env") -> tuple[str, str] | None:
    """(username, password) from SACLAY_USERNAME / SACLAY_PASSWORD (environment first, then `dotenv`), or None.

    Never prompts, so it is safe to use from servers; pass it as `CelcatClient(credentials=...)` after
    wrapping it to raise when it returns None.
    """
    env = _read_dotenv(Path(dotenv))
    user = os.environ.get("SACLAY_USERNAME") or env.get("SACLAY_USERNAME")
    pwd = os.environ.get("SACLAY_PASSWORD") or env.get("SACLAY_PASSWORD")
    return (user, pwd) if user and pwd else None


@dataclass
class Resource:
    id: str  # federationId, e.g. "L3 CHI Chimie [O3XCHI-910]"
    text: str
    department: str | None = None


@dataclass
class Event:
    id: str
    start: datetime
    end: datetime | None
    category: str | None
    modules: list[str]
    sites: list[str]
    department: str | None
    faculty: str | None
    all_day: bool
    # Free-text lines of the description, in Celcat order (category, module name, room, group(s), staff...).
    details: list[str] = field(default_factory=list)
    # Named fields, filled only when details were fetched (get_timetable(..., details=True)).
    module_names: list[str] = field(default_factory=list)
    rooms: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    staff: list[str] = field(default_factory=list)
    notes: str | None = None
    raw: dict = field(default_factory=dict, repr=False)


def _parse_event(d: dict) -> Event:
    parts = [html.unescape(p).strip() for p in re.split(r"<br\s*/?>", d.get("description") or "")]
    return Event(
        id=d["id"],
        start=datetime.fromisoformat(d["start"]),
        end=datetime.fromisoformat(d["end"]) if d.get("end") else None,  # all-day events (holidays) have no end
        category=d.get("eventCategory"),
        modules=d.get("modules") or [],
        sites=d.get("sites") or [],
        department=d.get("department"),
        faculty=d.get("faculty"),
        all_day=bool(d.get("allDay")),
        details=[p for p in parts if p],
        raw=d,
    )


class ApiError(Exception):
    """The server answered with an HTTP error (not an authentication problem)."""


class CelcatClient:
    def __init__(
        self,
        entity: str = "sciences",
        session_file: Path | str = DEFAULT_SESSION_FILE,
        credentials: Callable[[], tuple[str, str]] | None = None,
    ):
        """`entity` is a key of ENTITIES or a raw 'Calendar_*' name.

        `credentials` returns (username, password) when a new login is required; by default the
        user is prompted in the terminal (getpass), so the password never touches disk.
        """
        self.entity = ENTITIES.get(entity, entity)
        self.base = f"{BASE_URL}/{self.entity}"
        self.session_file = Path(session_file)
        self._credentials = credentials or self._prompt
        self.session = load_session(self.session_file) or new_session()

    @staticmethod
    def _prompt() -> tuple[str, str]:
        """SACLAY_USERNAME / SACLAY_PASSWORD from the environment or a local .env file, else ask."""
        return credentials_from_env() or (input("Paris-Saclay login: "), getpass.getpass("Password: "))

    # -- auth -------------------------------------------------------------------------------
    def is_authenticated(self) -> bool:
        try:
            self._json("GET", "Home/ReadResourceListItems", params=self._list_params("a", 1, 1, GROUP), reauth=False)
            return True
        except AuthError:
            return False

    def authenticate(self) -> None:
        # 1) Reuse the CAS single-sign-on cookie (kept in the same jar) -> no password needed.
        try:
            self.session = login(None, None, self.entity, session=self.session, sso_only=True)
        except AuthError:
            # 2) CAS session gone: ask for credentials (.env / environment / terminal prompt).
            username, password = self._credentials()
            self.session = login(username, password, self.entity, session=new_session())
        save_session(self.session, self.session_file)

    def ensure_authenticated(self) -> None:
        if not self.is_authenticated():
            self.authenticate()

    # -- low level --------------------------------------------------------------------------
    def _json(self, method: str, path: str, *, params=None, data=None, reauth: bool = True):
        headers = {"X-Requested-With": "XMLHttpRequest", "Referer": f"{self.base}/cal"}
        r = self.session.request(method, f"{self.base}/{path}", params=params, data=data, headers=headers, timeout=60)
        # When unauthenticated Celcat answers 200 with an empty body, or an HTML/redirect page.
        if r.status_code != 200:
            raise ApiError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:200]!r}")
        ok = r.text.strip() and "json" in r.headers.get("content-type", "").lower()
        if not ok:
            if reauth:
                self.authenticate()
                return self._json(method, path, params=params, data=data, reauth=False)
            raise AuthError(f"Not authenticated for {self.entity}")
        return r.json()

    @staticmethod
    def _list_params(term: str, page: int, size: int, res_type: int) -> dict:
        return {"myResources": "false", "searchTerm": term, "pageSize": size, "pageNumber": page, "resType": res_type}

    # -- resources --------------------------------------------------------------------------
    def search_resources(self, res_type: int, term: str = "", page_size: int = 100) -> Iterator[Resource]:
        """Iterate over resources whose name matches `term` (server-side min. length may apply)."""
        if not term:
            # The server rejects an empty term (HTTP 500): enumerate with one search per character.
            seen: set[str] = set()
            for ch in "abcdefghijklmnopqrstuvwxyz0123456789":
                for res in self.search_resources(res_type, ch, page_size):
                    if res.id not in seen:
                        seen.add(res.id)
                        yield res
            return
        page = 1
        while True:
            j = self._json("GET", "Home/ReadResourceListItems", params=self._list_params(term, page, page_size, res_type))
            for x in j["results"]:
                yield Resource(id=x["id"], text=x["text"], department=x.get("dept"))
            if page * page_size >= j["total"]:
                return
            page += 1

    def list_groups(self, term: str = "") -> list[Resource]:
        return list(self.search_resources(GROUP, term))

    def list_modules(self, term: str = "") -> list[Resource]:
        """Catalogue of courses (modules) known to this calendar."""
        return list(self.search_resources(MODULE, term))

    # -- timetable --------------------------------------------------------------------------
    def get_events(self, federation_id: str, start: date, end: date, res_type: int = GROUP) -> list[Event]:
        """Events of one resource (group by default) between `start` and `end`."""
        events: dict[str, Event] = {}
        cur = start
        while cur < end:
            nxt = min(cur + timedelta(days=_CHUNK_DAYS), end)
            j = self._json(
                "POST",
                "Home/GetCalendarData",
                data={
                    "start": cur.isoformat(),
                    "end": nxt.isoformat(),
                    "resType": res_type,
                    "calView": "agendaWeek",
                    "federationIds[]": federation_id,
                    "colourScheme": 3,
                },
            )
            for d in j:
                events[d["id"]] = _parse_event(d)
            cur = nxt
        return sorted(events.values(), key=lambda e: e.start)

    def get_timetable(self, group: str, start: date, end: date, details: bool = False, workers: int = 8) -> list[Event]:
        """Events of a group. With `details=True` also fill rooms/groups/staff/module_names
        (one extra request per event, run in parallel)."""
        events = self.get_events(group, start, end, GROUP)
        if details:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(self.fill_details, events))
        return events

    def get_event_details(self, event_id: str) -> dict:
        """Raw sidebar payload for an event (elements with label/content/federationId/entityType)."""
        return self._json("POST", "Home/GetSideBarEvent", data={"eventId": event_id})

    def fill_details(self, event: Event) -> Event:
        """Populate the named fields of `event` from the sidebar endpoint."""
        by_type: dict[int, list[str]] = {MODULE: [], ROOM: [], GROUP: [], STAFF: []}
        known = set()
        for el in self.get_event_details(event.id).get("elements", []):
            content = (el.get("content") or "").strip()
            if el.get("isNotes"):
                event.notes = content
            elif el.get("entityType") in by_type and content:
                by_type[el["entityType"]].append(content)
            if content:
                known.add(content)
        # Staff is hidden from the sidebar for some accounts but present in the description:
        # whatever description line is neither category, module, room nor group is staff.
        if not by_type[STAFF]:
            by_type[STAFF] = [d for d in event.details if d not in known and d != event.category and d != event.department]
        event.module_names = by_type[MODULE]
        event.rooms = by_type[ROOM]
        event.groups = by_type[GROUP]
        event.staff = by_type[STAFF]
        return event

    def get_courses(self, group: str, start: date, end: date) -> dict[str, str]:
        """Courses a group has between two dates: {module code: module name}."""
        first_event: dict[str, Event] = {}
        for e in self.get_timetable(group, start, end):
            for code in e.modules:
                first_event.setdefault(code, e)
        courses: dict[str, str] = {}
        for code, e in first_event.items():
            self.fill_details(e)
            courses[code] = e.module_names[0] if e.module_names else code
        return courses
