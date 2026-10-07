"""Official agencies and independent publishers (think tanks) are told apart in every view, and can be filtered."""
import re

import pytest
from fastapi.testclient import TestClient

from rozvedka import app as app_module
from rozvedka import collect, crawler, db, doclist, series, topics, trends


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    app_module._independent["at"] = 0.0                       # forget the cached list of independent sources
    db.init()
    collect.init()
    topics.init()
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil',1)")
        con.execute("""INSERT INTO sources(id,key,country,agency,type,publisher,active)
                       VALUES(2,'US/Freedom House','US','Freedom House','think-tank','independent',1)""")
        for i, src in ((1, 1), (2, 1), (3, 2)):
            con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,local_path)
                           VALUES(?,?,?,?,'en',2025,'downloaded',?)""", (i, src, f"https://x/{i}.pdf", f"Report {i}", f"f{i}.pdf"))
    yield tmp_path
    app_module._independent["at"] = 0.0


def test_official_filter_and_counts(library):
    assert doclist.count() == 3 and doclist.count(type="official") == 2 and doclist.count(type="think-tank") == 1
    where, args, params = trends.scope(type="official")
    with db.session() as con:
        assert con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {where}", args).fetchone()[0] == 2
    assert params == {"type": "official"}


def test_marked_in_views(library):
    client = TestClient(app_module.app)
    docs = client.get("/documents").text
    assert docs.count('class="pub-ind"') == 1                  # one think-tank row, official rows unmarked
    assert re.search(r"◆ 1 from think tanks", docs)
    assert re.search(r"<b>2</b> documents match", client.get("/documents?type=official").text)
    report = client.get("/report/3").text
    assert "pub-banner" in report and "not a\n  state agency" in report
    assert "pub-banner" not in client.get("/report/1").text


def test_follow_pattern_opens_only_publication_pages():
    html = """<a href="/publication/a-report/">A report</a> <a href="/about/">About</a>
              <a href="/publication/b/">B</a> <a href="https://other.org/publication/c/">C</a>"""
    docs, subs = crawler.extract(html, "https://tt.org/publications", r"tt\.org/publication/[^/]+/?$")
    assert [u for u, _ in subs] == ["https://tt.org/publication/a-report/", "https://tt.org/publication/b/"]


def test_sources_page_keeps_think_tanks_apart(library):
    client = TestClient(app_module.app)
    t = client.get("/sources").text
    assert 'id="independent"' in t and "<b>1</b> independent think tanks" in t
    assert t.index('id="c-CZ"') < t.index('id="independent"') < t.index('id="ci-US"')
    assert 'class="card card-ind" id="s-2"' in t and 'class="card" id="s-1"' in t
