from datetime import date, datetime

import pytest

from saclay_edt import ApiError, AuthError, GROUP
from saclay_edt.client import _parse_event, _read_dotenv

from conftest import EVENT, HOLIDAY, SIDEBAR, FakeResponse

CAL = ("POST", "Home/GetCalendarData")
SIDE = ("POST", "Home/GetSideBarEvent")
LIST = ("GET", "Home/ReadResourceListItems")


def test_parse_event_basic():
    e = _parse_event(EVENT)
    assert e.start == datetime(2026, 10, 5, 8, 0) and e.end == datetime(2026, 10, 5, 9, 30)
    assert e.modules == ["MATH1"]
    assert e.details == ["Cours Magistral (CM)", "Algèbre", "Salle A", "G1", "Jane Doe"]  # HTML entities decoded


def test_parse_event_all_day_without_end():
    e = _parse_event(HOLIDAY)
    assert e.end is None and e.all_day and e.modules == [] and e.sites == []


def test_dotenv(tmp_path):
    p = tmp_path / ".env"
    p.write_text('# c\nSACLAY_USERNAME="bob"\nSACLAY_PASSWORD = p=w\n\nbad line\n')
    assert _read_dotenv(p) == {"SACLAY_USERNAME": "bob", "SACLAY_PASSWORD": "p=w"}
    assert _read_dotenv(tmp_path / "missing") == {}


def test_expired_session_empty_200_triggers_reauth_once(make_client):
    state = {"authed": False}
    c = make_client({LIST: lambda p, d: FakeResponse({"total": 0, "results": []}) if state["authed"] else FakeResponse("", ctype="")})
    c.authenticate = lambda: state.update(authed=True)
    assert list(c.search_resources(GROUP, "x")) == [] and state["authed"]


def test_unauthenticated_raises_when_reauth_disabled(make_client):
    c = make_client({LIST: FakeResponse("", ctype="")})
    assert c.is_authenticated() is False
    with pytest.raises(AuthError):
        c._json("GET", "Home/ReadResourceListItems", reauth=False)


def test_http_error_is_api_error_and_does_not_reauth(make_client):
    c = make_client({LIST: FakeResponse("boom", status=500, ctype="text/html")})
    c.authenticate = lambda: pytest.fail("must not re-login on HTTP 500")
    with pytest.raises(ApiError):
        list(c.search_resources(GROUP, "x"))


def test_search_pagination(make_client):
    pages = {1: [{"id": "a", "text": "a", "dept": "D"}, {"id": "b", "text": "b"}], 2: [{"id": "c", "text": "c"}]}
    c = make_client({LIST: lambda p, d: FakeResponse({"total": 3, "results": pages[p["pageNumber"]]})})
    assert [r.id for r in c.search_resources(GROUP, "x", page_size=2)] == ["a", "b", "c"]


def test_empty_term_enumerates_per_character_and_dedupes(make_client):
    def handler(p, d):
        assert p["searchTerm"]  # never send an empty term: the server answers HTTP 500
        return FakeResponse({"total": 1, "results": [{"id": "same", "text": "same"}]})

    c = make_client({LIST: handler})
    assert [r.id for r in c.list_groups()] == ["same"]


def test_get_events_chunks_and_dedupes(make_client):
    c = make_client({CAL: lambda p, d: FakeResponse([EVENT, HOLIDAY])})
    ev = c.get_events("G1", date(2026, 10, 1), date(2026, 12, 15))
    assert len(c.session.calls) == 3  # 31-day chunks
    assert sorted(e.id for e in ev) == ["e1", "h1"]
    first = c.session.calls[0][3]
    assert first["federationIds[]"] == "G1" and first["resType"] == GROUP and first["start"] == "2026-10-01"


def test_timetable_details_fill_named_fields(make_client):
    c = make_client({CAL: FakeResponse([EVENT]), SIDE: FakeResponse(SIDEBAR)})
    [e] = c.get_timetable("G1", date(2026, 10, 1), date(2026, 10, 8), details=True)
    assert (e.module_names, e.rooms, e.groups, e.notes) == (["Algèbre"], ["Salle A"], ["G1"], "(30)")
    assert e.staff == ["Jane Doe"]  # not in sidebar -> leftover description line


def test_get_courses(make_client):
    c = make_client({CAL: FakeResponse([EVENT, dict(EVENT, id="e2")]), SIDE: FakeResponse(SIDEBAR)})
    assert c.get_courses("G1", date(2026, 10, 1), date(2026, 10, 8)) == {"MATH1": "Algèbre"}
    assert sum(1 for call in c.session.calls if call[1].endswith("GetSideBarEvent")) == 1  # one lookup per course
