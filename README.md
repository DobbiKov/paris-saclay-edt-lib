# saclay-edt

Python client for the Université Paris-Saclay timetables (<https://edt.universite-paris-saclay.fr>,
a CELCAT Calendar deployment). Search groups/courses and fetch timetables with plain HTTP — no browser.

```python
from datetime import date, timedelta
from saclay_edt import CelcatClient

c = CelcatClient("sciences")          # iut_sceaux | iut_cachan | medecine | sciences
c.ensure_authenticated()              # reuses .session.json, logs in only if needed

group = c.list_groups("L3 CHI")[0].id
today = date.today()
for e in c.get_timetable(group, today, today + timedelta(days=7), details=True):
    print(e.start, e.category, e.module_names, e.rooms, e.staff)

print(c.get_courses(group, today, today + timedelta(days=120)))   # {code: name}
```

## Web UI

```bash
python3 example.py            # once: logs in (prompt or SACLAY_USERNAME/SACLAY_PASSWORD in .env) and saves .session.json
python3 -m saclay_edt.web     # then open http://127.0.0.1:8000  (--port N to change)
```

Pick a faculty, search a group, browse week by week; click a session for room, teacher, groups and notes.
"Hide sub-group sessions" keeps only sessions of the selected group itself. The server listens on localhost
only, reuses the saved cookies and never prompts: when the session expires it answers 401 and you log in again from a terminal.

## Tests

```bash
python3 -m pytest tests
```

Offline only (fake HTTP sessions with synthetic data): auth flow, client parsing/pagination/re-login, and the web API.

## Authentication

There is no bearer token. Celcat uses SAML SSO against the university CAS:

1. `GET /<Entity>/Login` → 302 `/<Entity>/Saml/SingleSignOn` → 302 CAS (`sso.universite-paris-saclay.fr/cas/login`)
2. `POST` the CAS form (`username`, `password`, hidden `execution`, `_eventId=submit`, hidden `rememberMe=false`)
3. CAS returns an auto-submitting SAML form; posting it back to Celcat sets the session cookies.

The whole cookie jar (including the CAS single-sign-on cookie) is saved in `.session.json` (mode 0600, gitignored).
Other entities reuse the CAS cookie, so one password login covers all four. A new login is attempted in this order:

1. CAS cookie (no password), 2. `SACLAY_USERNAME` / `SACLAY_PASSWORD` from the environment or a local `.env`, 3. terminal prompt.

An expired Celcat session shows up as an **HTTP 200 with an empty body** on the JSON endpoints.

## Endpoints (under `/Calendar_<ENTITY>/`)

| Endpoint | Notes |
|---|---|
| `GET Home/ReadResourceListItems` | `resType` 100 module, 101 staff, 102 room, 103 group, 104 student; `searchTerm` (≥1 char, empty → 500), `pageSize`, `pageNumber`, `myResources=false`. Returns `{total, results:[{id,text,dept}]}`. |
| `POST Home/GetCalendarData` | `start`, `end` (YYYY-MM-DD), `resType`, `calView`, `federationIds[]`, `colourScheme`. Returns a JSON array of events; all-day events have `end: null`. |
| `POST Home/GetSideBarEvent` | `eventId` → elements with `label`, `content`, `federationId`, `entityType`. |
| `POST Home/GetSideBarResources` | `resType`, `federationIds[]` → resource details. |

Staff/student searches return an empty body for student accounts (not allowed). Entities:
`Calendar_DEG_FSO_F2S` (sciences, STAPS, pharmacie, UFR Sceaux), `Calendar_IutSceaux`, `Calendar_IutCachan`, `Calendar_UfrKB`.

## Notes

- A parent group (e.g. `L3 CHI Chimie [O3XCHI-910]`) returns the events of its sub-groups too; filter with `group in e.groups` after `details=True`.
- The order of `Event.details` differs between entities; use the named fields (`rooms`, `groups`, `staff`, `module_names`).
