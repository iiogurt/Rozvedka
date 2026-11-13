"""The kept scope (static/scope.js): every page it names exists, takes the fields the script sends it, and has the
form the script looks for – so a renamed filter cannot silently stop being carried."""
import inspect
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, collect, db, series, topics

JS = (Path(__file__).parent.parent / "rozvedka" / "static" / "scope.js").read_text()
FIELDS = json.loads(re.search(r"FIELDS = (\[.*?\]);", JS).group(1))
GET = json.loads(re.search(r"const GET = (\{.*?\});", JS).group(1).replace("FIELDS", json.dumps(FIELDS))
                 .replace('{"', '{"').replace("'", '"'))
LIVE = json.loads(re.search(r"const LIVE = (\[.*?\]);", JS).group(1))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    db.init()
    collect.init()
    actors.init()
    topics.init()
    with db.session() as con:
        con.execute("""INSERT INTO sources(id,key,country,agency,type,name_en,active)
                       VALUES(1,'EE/KAPO','EE','KAPO','intelligence-civil','Estonian Internal Security Service',1)""")
        con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status)
                       VALUES(1,1,'https://kapo.ee/a.pdf','Annual Review 2024','en',2024,'downloaded')""")
    from rozvedka.app import app
    return TestClient(app)


def test_the_script_names_real_filters():
    from rozvedka.app import app

    def routes(rs):
        for r in rs:
            if hasattr(r, "original_router"):
                yield from routes(r.original_router.routes)
            elif "GET" in (getattr(r, "methods", None) or ()):
                yield r.path, r.endpoint
    by_path = dict(routes(app.routes))
    assert FIELDS == ["type", "year_from", "year_to", "country", "coalition"]
    assert set(GET) == {"/documents", "/compare", "/events", "/series"} and len(LIVE) == 6
    for path, fields in GET.items():                     # the server reads each field the script puts in the address
        assert set(fields) <= set(inspect.signature(by_path[path]).parameters), path
    for path in LIVE:
        assert path in by_path, path


def test_pages_carry_the_line_and_the_forms(client):
    t = client.get("/actors").text
    assert 'id="kept"' in t and "scope.js" in t and t.index("jump.js") < t.index("scope.js")
    for path in GET:                                     # the form the script reads the names of the choices from
        assert f'method="get" action="{path}"' in client.get(path).text, path
    for path in LIVE:                                    # the form that asks for the data, with at least one kept field
        t = client.get(path).text
        form = re.search(r'<form[^>]*id="scope".*?</form>', t, re.S)
        assert form and any(f'name="{f}"' in form.group(0) for f in FIELDS), path
    # the filters are applied by the server when they come in the address
    t = client.get("/documents?type=official&year_from=2024&year_to=2024&country=EE").text
    assert "Annual Review 2024" in t and "Annual Review 2024" not in client.get("/documents?country=EE&year_from=2025").text
