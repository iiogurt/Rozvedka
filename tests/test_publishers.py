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
    app_module._independent["at"] = None                       # forget the cached list of independent sources
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
    app_module._independent["at"] = None


def test_official_filter_and_counts(library):
    assert doclist.count() == 3 and doclist.count(type="official") == 2 and doclist.count(type="think-tank") == 1
    where, args, params = trends.scope(type="official")
    with db.session() as con:
        assert con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {where}", args).fetchone()[0] == 2
    assert params == {"type": "official"}


def test_marked_in_views(library):
    client = TestClient(app_module.app)
    docs = client.get("/documents").text
    assert docs.count('class="pub-ind pub-lv-') == 1          # one think-tank row, official rows unmarked
    assert re.search(r"◆ 1 from think tanks", docs)
    assert re.search(r"<b>2</b> documents match", client.get("/documents?type=official").text)
    report = client.get("/report/3").text
    assert "pub-banner" in report and "is a think tank, not a state agency" in report
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


# ── credibility profiles (rozvedka/publishers.py) ──
PROFILES = {
    "US/Freedom House": {"wikipedia": "Freedom House",
                         "funding": {"disclosure": "brackets", "evidence": "https://fh.org/funding", "checked": "2026-10-07",
                                     "governments": ["USA", "ARE"]}},
}
CHECKS = {"retrieved": "2026-10-07", "fara": {}, "identity": {},
          "eu_register": {"US/Freedom House": {"id": "007667198226-29", "name": "Freedom House, Inc.", "category": "NGO",
                                                "registered": "2016-01-01", "updated": "2026-01-01", "year": None,
                                                "eu_grants": [], "eu_grants_total": 0.0, "lobbying_cost": None, "url": "https://x"}},
          "sanctions": {"lists": {"US OFAC SDN": {"url": "https://ofac", "names": 10}}, "hits": {}}}
RATINGS = {"retrieved": "2026-10-07", "iso3": {}, "measures": {}, "names": {"ARE": "United Arab Emirates", "USA": "United States"},
           "values": {"ARE": {"vdem_regime": {"2025": 0}}, "USA": {"vdem_regime": {"2025": 2}}}}


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    import json as _json
    import yaml as _yaml
    from rozvedka import publishers, ratings
    (tmp_path / "publishers.yaml").write_text(_yaml.safe_dump(PROFILES))
    (tmp_path / "publishers.json").write_text(_json.dumps(CHECKS))
    (tmp_path / "ratings.json").write_text(_json.dumps(RATINGS))
    monkeypatch.setattr(publishers, "PROFILES", tmp_path / "publishers.yaml")
    monkeypatch.setattr(publishers, "STORE", tmp_path / "publishers.json")
    monkeypatch.setattr(ratings, "STORE", tmp_path / "ratings.json")
    publishers.load.cache_clear(); ratings.load.cache_clear()
    app_module._independent["at"] = None
    yield publishers
    publishers.load.cache_clear(); ratings.load.cache_clear()
    app_module._independent["at"] = None


def test_rating_rule(profiles):
    p = profiles.profile("US/Freedom House")
    assert p["level"] == "concerns"                                       # brackets would be transparent, but…
    assert p["reasons"] == ["Government donors: from autocracies: United Arab Emirates (closed autocracy, V-Dem 2025); "
                            "named: United States, United Arab Emirates"]
    assert {c["key"]: c["status"] for c in p["checks"]} == {"sanctions": "ok", "fara": "ok", "funding": "ok",
                                                           "governments": "concern", "eu_register": "ok"}
    PROFILES["US/Freedom House"]["funding"]["governments"] = ["USA"]
    try:
        (profiles.PROFILES).write_text(__import__("yaml").safe_dump(PROFILES))
        assert profiles.profile("US/Freedom House")["level"] == "transparent"
        CHECKS["sanctions"]["hits"] = {"US/Freedom House": ["US OFAC SDN"]}
        profiles.STORE.write_text(__import__("json").dumps(CHECKS)); profiles.load.cache_clear()
        assert profiles.profile("US/Freedom House")["level"] == "redflag"
    finally:
        PROFILES["US/Freedom House"]["funding"]["governments"] = ["USA", "ARE"]
        CHECKS["sanctions"]["hits"] = {}
    assert profiles.profile("XX/Unknown")["level"] == "unassessed"


def test_sanction_list_formats():
    from rozvedka import publishers as P
    assert "strategic culture foundation" in P._sanction_names("US OFAC SDN", b'36,"STRATEGIC CULTURE FOUNDATION","-0-",CYBER2\n')
    uk = b"Last Updated,07/10/2026\nName 6,Name 1,Group Type\nInfoRos,,Entity\n"
    assert "inforos" in P._sanction_names("UK sanctions list", uk)
    eu = "NameAlias_WholeName;Entity_SubjectType\nSouth Front;enterprise\n".encode()
    assert "south front" in P._sanction_names("EU financial sanctions", eu)
    un = b"<CONSOLIDATED_LIST><ENTITIES><ENTITY><FIRST_NAME>Example Front</FIRST_NAME><ENTITY_ALIAS><ALIAS_NAME>EF</ALIAS_NAME></ENTITY_ALIAS></ENTITY></ENTITIES></CONSOLIDATED_LIST>"
    assert {"example front", "ef"} <= P._sanction_names("UN Security Council", un)


def test_badge_and_pages(library, profiles):
    client = TestClient(app_module.app)
    docs = client.get("/documents").text
    assert 'class="pub-ind pub-lv-concerns" href="/publisher/2"' in docs and "think tank · concerns" in docs
    page = client.get("/publisher/2").text
    assert "United Arab Emirates (closed autocracy" in page and "007667198226-29" in page and "fh.org/funding" in page
    assert client.get("/publisher/1").status_code == 404                    # an official agency has no think-tank profile
    t = client.get("/publishers").text
    assert 'href="/publisher/2"' in t and "pub-lv-concerns" in t
