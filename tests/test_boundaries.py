"""The library is only a Celcat API client: it must stay free of caching, storage, servers and the app on top of it."""
import ast
import sys
from pathlib import Path

import saclay_edt

LIB = Path(saclay_edt.__file__).parent
FORBIDDEN = {"app", "bot", "timetable_service", "sqlite3", "shelve", "dbm", "http", "socketserver", "flask", "fastapi", "telegram"}


def imported_modules():
    found = {}
    for path in LIB.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module]
            else:
                continue
            for n in names:
                found.setdefault(n.split(".")[0], set()).add(path.name)
    return found


def test_library_does_not_import_app_storage_or_server_code():
    bad = {m: f for m, f in imported_modules().items() if m in FORBIDDEN}
    assert not bad, f"library must not depend on: {bad}"


def test_library_only_third_party_dependency_is_requests():
    third_party = {m for m in imported_modules() if m not in sys.stdlib_module_names and m != "saclay_edt"}
    assert third_party == {"requests"}


def test_library_has_only_auth_and_client_modules():
    assert sorted(p.name for p in LIB.iterdir() if p.suffix == ".py") == ["__init__.py", "auth.py", "client.py"]
