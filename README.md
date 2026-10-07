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
python3 example.py            # once: logs in (prompt, or credentials from .env, see "Credentials") and saves .session.json
python3 -m saclay_edt.web     # then open http://127.0.0.1:8000  (--port N to change)
```

Pick a faculty, search a group, browse week by week; click a session for room, teacher, groups and notes.
"Only sessions naming this group" keeps sessions that list the selected group itself (useful on a parent group such as
`L3 CHI Chimie`; at the IUTs sessions are listed under the parent, so leave it off there).
Your choices (faculty, one group per faculty, the filter) are remembered in `.prefs.json` (gitignored), so they survive
restarts, other ports and other browsers. Emptying the group box forgets that faculty's group.
The server listens on localhost only, reuses the saved cookies and never prompts: when the session expires it answers 401
and you log in again from a terminal.

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

### Credentials in `.env` (optional)

Without a `.env` you type your login and password in the terminal whenever the saved session has expired.
To skip the prompt, create a `.env` file **in the directory you run Python from** (normally the project root):

```ini
# .env
SACLAY_USERNAME=your_login
SACLAY_PASSWORD=your_password
```

- Format: one `KEY=VALUE` per line; blank lines and lines starting with `#` are ignored; surrounding quotes are
  stripped (optional). There are no inline comments: everything after the first `=` is the value, so `#` or spaces
  inside a password are kept as typed.
- Real environment variables take precedence over `.env`, so `SACLAY_PASSWORD=... python3 example.py` also works.
- The file is only read when a new password login is actually needed (the CAS cookie is tried first), and it is the
  only place the password is ever stored. `.env` is gitignored; also run `chmod 600 .env`, since it is plain text.
- The web UI (`python3 -m saclay_edt.web`) never prompts. Without a `.env` it answers 401 when the session expires and
  you re-login from a terminal; with a `.env` it renews the session by itself.
- Only provide credentials in a `.env` you control, on a machine you trust. They are sent solely to the university CAS.

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
