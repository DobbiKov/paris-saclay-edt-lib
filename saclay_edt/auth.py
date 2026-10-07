"""CAS/SAML authentication for the Paris-Saclay Celcat Calendar (edt.universite-paris-saclay.fr).

Flow: GET {entity}/Login -> 302 {entity}/Saml/SingleSignOn -> 302 CAS login page ->
POST credentials (username, password, execution, _eventId=submit) -> CAS answers with an
auto-submitting SAML form -> POST SAMLResponse back to Celcat -> Celcat sets its session cookies.
The resulting cookie jar is the "token": it is persisted to a JSON file and replayed.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

BASE_URL = "https://edt.universite-paris-saclay.fr"
DEFAULT_SESSION_FILE = Path(".session.json")
USER_AGENT = "Mozilla/5.0 (compatible; saclay-edt/0.1)"


class AuthError(Exception):
    pass


def new_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def save_session(session: requests.Session, path: Path = DEFAULT_SESSION_FILE) -> None:
    cookies = [
        {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
        for c in session.cookies
    ]
    data = {"cookies": cookies, "saved_at": datetime.now(timezone.utc).isoformat()}
    path = Path(path)
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)


def load_session(path: Path = DEFAULT_SESSION_FILE) -> requests.Session | None:
    path = Path(path)
    if not path.exists():
        return None
    s = new_session()
    for c in json.loads(path.read_text()).get("cookies", []):
        s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
    return s


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}\s*=\s*"([^"]*)"', tag)
    return html.unescape(m.group(1)) if m else None


def _hidden_inputs(form_html: str) -> dict[str, str]:
    out = {}
    for tag in re.findall(r"<input[^>]*>", form_html):
        name = _attr(tag, "name")
        if not name or _attr(tag, "type") in ("checkbox", "radio", "submit"):
            continue  # e.g. the rememberMe checkbox would otherwise override its hidden "false" twin
        out[name] = _attr(tag, "value") or ""
    return out


def _cas_error(page: str) -> str:
    """Best-effort extraction of the CAS failure message (e.g. 'Authentication Failure ...')."""
    for m in re.findall(r'<(?:div|span|p)[^>]*(?:id="msg"|class="[^"]*alert[^"]*")[^>]*>(.*?)</(?:div|span|p)>', page, re.S):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(m))).strip()
        if "ailure" in text or "nvalid" in text or "rror" in text:
            return text
    return "no message found"


def _find_form(page: str, needle: str | None = None) -> tuple[str, str] | None:
    for m in re.finditer(r"(<form[^>]*>)(.*?)</form>", page, re.S):
        if needle is None or needle in m.group(2):
            return m.group(1), m.group(2)
    return None


def login(
    username: str | None,
    password: str | None,
    entity: str,
    *,
    session: requests.Session | None = None,
    sso_only: bool = False,
) -> requests.Session:
    """Authenticate against `entity` (e.g. 'Calendar_DEG_FSO_F2S') and return the session.

    With `sso_only=True` no credentials are submitted: this only succeeds if the session already
    holds a valid CAS cookie (e.g. logged in to another entity), otherwise AuthError is raised.
    """
    s = session or new_session()
    r = s.get(f"{BASE_URL}/{entity}/Login", timeout=30)
    r.raise_for_status()

    form = _find_form(r.text, 'name="execution"')
    if form is not None:
        if sso_only or not (username and password):
            raise AuthError("CAS session expired: credentials required")
        tag, body = form
        data = _hidden_inputs(body)
        data.update({"username": username, "password": password, "_eventId": "submit"})
        action = urljoin(r.url, _attr(tag, "action") or "")
        r = s.post(action, data=data, timeout=30)
    # Without a login form an existing CAS (SSO) cookie may already have authenticated us.
    r = _follow_saml(s, r)

    if _find_form(r.text, 'name="execution"') is not None:
        raise AuthError(f"CAS login failed: {_cas_error(r.text)}")
    if "sso.universite-paris-saclay.fr" in r.url:
        raise AuthError(f"Unexpected CAS page (MFA or consent step?): {r.url}")
    if not r.url.startswith(BASE_URL):
        raise AuthError(f"Login did not return to Celcat: {r.url}")
    return s


def _follow_saml(s: requests.Session, r: requests.Response) -> requests.Response:
    """Submit auto-posting SAML forms (SAMLResponse / RelayState) until none remain."""
    for _ in range(5):
        form = _find_form(r.text, "SAMLResponse") or _find_form(r.text, "SAMLRequest")
        if form is None:
            return r
        tag, body = form
        action = urljoin(r.url, _attr(tag, "action") or "")
        r = s.post(action, data=_hidden_inputs(body), timeout=30)
    return r
