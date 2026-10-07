import pytest
import requests

from saclay_edt import AuthError, login
from saclay_edt.auth import _hidden_inputs, load_session, save_session

CAS_FORM = """<html><form method="post" id="fm1" action="login">
<input type="text" name="username" value=""/><input type="password" name="password" value=""/>
<input type="hidden" name="rememberMe" value="false"/><input type="checkbox" name="rememberMe"/>
<input type="hidden" name="execution" value="EX&amp;1"/><input type="hidden" name="_eventId" value="submit"/>
<input type="hidden" name="geolocation"/><input type="hidden" name="deviceFingerprint"/></form></html>"""
SAML_FORM = '<form method="post" action="https://edt.universite-paris-saclay.fr/Calendar_X/Saml/AssertionConsumerService"><input type="hidden" name="SAMLResponse" value="abc"/><input type="hidden" name="RelayState" value="r"/></form>'
CAS_URL = "https://sso.universite-paris-saclay.fr/cas/login?service=x"
HOME = "https://edt.universite-paris-saclay.fr/Calendar_X/cal"


class Resp:
    def __init__(self, text, url):
        self.text, self.url, self.status_code = text, url, 200

    def raise_for_status(self):
        pass


class Flow:
    """Scripted CAS+SAML conversation recording what the client posts."""

    def __init__(self, sso_cookie=False, password_ok=True):
        self.sso_cookie, self.password_ok, self.posts = sso_cookie, password_ok, []
        self.cookies = requests.cookies.RequestsCookieJar()
        self.headers = {}

    def get(self, url, timeout=None):
        return Resp(SAML_FORM, CAS_URL) if self.sso_cookie else Resp(CAS_FORM, CAS_URL)

    def post(self, url, data=None, timeout=None):
        self.posts.append((url, dict(data)))
        if "SAMLResponse" in data:
            return Resp("<html>calendar</html>", HOME)
        return Resp(SAML_FORM, CAS_URL) if self.password_ok else Resp(CAS_FORM, CAS_URL)


def test_hidden_inputs_ignores_checkbox_twin():
    d = _hidden_inputs(CAS_FORM)
    assert d["rememberMe"] == "false"  # the checkbox (empty value) must not override the hidden input -> CAS typeMismatch
    assert d["execution"] == "EX&1" and "deviceFingerprint" in d


def test_login_posts_form_then_saml():
    s = Flow()
    assert login("bob", "pw", "Calendar_X", session=s) is s
    (cas_url, cas_data), (saml_url, saml_data) = s.posts
    assert cas_url == "https://sso.universite-paris-saclay.fr/cas/login"
    assert cas_data["username"] == "bob" and cas_data["password"] == "pw" and cas_data["_eventId"] == "submit"
    assert saml_url.endswith("/Saml/AssertionConsumerService") and saml_data == {"SAMLResponse": "abc", "RelayState": "r"}


def test_login_wrong_password_raises():
    with pytest.raises(AuthError, match="CAS login failed"):
        login("bob", "bad", "Calendar_X", session=Flow(password_ok=False))


def test_sso_only_never_submits_credentials():
    s = Flow()
    with pytest.raises(AuthError):
        login(None, None, "Calendar_X", session=s, sso_only=True)
    assert s.posts == []


def test_blank_credentials_are_not_submitted():
    s = Flow()
    with pytest.raises(AuthError):
        login("", "", "Calendar_X", session=s)  # avoids burning failed attempts on a CAS account
    assert s.posts == []


def test_sso_cookie_logs_in_without_password():
    s = Flow(sso_cookie=True)
    login(None, None, "Calendar_X", session=s, sso_only=True)
    assert [list(d) for _, d in s.posts] == [["SAMLResponse", "RelayState"]]


def test_session_roundtrip_and_permissions(tmp_path):
    s = requests.Session()
    s.cookies.set("k", "v", domain="edt.universite-paris-saclay.fr", path="/")
    p = tmp_path / "s.json"
    save_session(s, p)
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert load_session(p).cookies.get("k") == "v"
    assert load_session(tmp_path / "none.json") is None
