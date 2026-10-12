"""Who cites whom: addresses in the report texts resolved against the library."""
import pytest
from fastapi.testclient import TestClient

from rozvedka import citations, collect, db, doclist, series, topics


def test_addresses_are_compared_loosely():
    assert citations.norm("https://www.Example.org/Path/Report.PDF/.") == ("example.org", "example.org/path/report.pdf")
    assert citations.norm("http://example.org/a/") == citations.norm("https://www.example.org/a")
    assert citations.norm("https://localhost/x") == ("", "") and citations.norm("http://[bad") == ("", "")
    found = citations.addresses("See (https://a.org/x), https://a.org/x. and https://b.org/y;")
    assert found["a.org/x"]["n"] == 2 and set(found) == {"a.org/x", "b.org/y"} and found["a.org/x"]["raw"] == "https://a.org/x"


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    db.init()
    collect.init()
    topics.init()
    docs = {
        1: (1, "https://ncsc.example/r1.pdf", "NCSC annual 2024", "Text without links."),
        2: (2, "https://bsi.example/r2.pdf", "BSI report 2025",
            "Cites https://www.ncsc.example/r1.pdf and the agency https://ncsc.example/news/x and https://shared.gov/a "
            "and news https://news.example/story and its own https://bsi.example/other and https://shared.gov/b"),
        3: (3, "https://cert.example/r3.pdf", "CERT 2025", "Also https://news.example/story and https://ncsc.example/r1.pdf"),
    }
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,homepage) VALUES(1,'GB/NCSC','GB','NCSC','cyber','https://ncsc.example/')")
        con.execute("INSERT INTO sources(id,key,country,agency,type,homepage) VALUES(2,'DE/BSI','DE','BSI','cyber','https://bsi.example/')")
        con.execute("INSERT INTO sources(id,key,country,agency,type,homepage) VALUES(3,'XX/CERT','XX','CERT','cyber','https://shared.gov/')")
        con.execute("INSERT INTO sources(id,key,country,agency,type,homepage) VALUES(4,'YY/OTHER','YY','OTHER','cyber','https://shared.gov/')")
        for i, (sid, url, title, text) in docs.items():
            con.execute("INSERT INTO documents(id,source_id,url,title,year,lang,status) VALUES(?,?,?,?,2025,'en','downloaded')", (i, sid, url, title))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", text))
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages) VALUES(?,?,?,?)", (i, len(text), "x", "[0]"))
    return tmp_path


def test_index_resolves_reports_agencies_and_outside_hosts(library):
    r = citations.index()
    assert r["to_library_reports"] == 2 and r["to_other_agencies"] == 1
    with db.session() as con:
        rows = {(x["doc_id"], x["url"]): (x["target_doc"], x["target_source"], x["host"]) for x in con.execute("SELECT * FROM doc_links")}
    assert rows[(2, "ncsc.example/r1.pdf")][:2] == (1, 1)                  # a report of the library, found despite "www."
    assert rows[(2, "ncsc.example/news/x")][:2] == (None, 1)               # another agency's site
    assert (2, "bsi.example/other") not in rows                            # its own agency's site: left out
    assert rows[(2, "shared.gov/a")][:2] == (None, None)                   # a host two sources share is not guessed at
    assert rows[(2, "news.example/story")][:2] == (None, None) and rows[(3, "news.example/story")][2] == "news.example"


def test_overview_and_every_count_links_to_its_reports(library):
    citations.index()
    o = citations.overview()
    assert [(s["agency"], s["reports"], s["agencies"]) for s in o["cited_sources"]] == [("NCSC", 2, 2)]
    assert [(d["id"], d["reports"]) for d in o["cited_docs"]] == [(1, 2)]
    assert ("news.example", 2, 2) in [(h["host"], h["reports"], h["agencies"]) for h in o["hosts"]]
    assert doclist.count(cite="src:1") == 2 and doclist.count(cite="doc:1") == 2 and doclist.count(cite="by:2") == 1
    assert doclist.count(cite="host:news.example") == 2 and doclist.count(cite="host:nothing.example") == 0
    d = citations.of_doc(2)
    assert [c["id"] for c in d["cited"]] == [1] and d["agencies"] == [{"id": 1, "agency": "NCSC", "links": 1}]
    assert {c["id"] for c in citations.of_doc(1)["cited_by"]} == {2, 3}


def test_pages(library):
    citations.index()
    from rozvedka.app import app
    c = TestClient(app)
    t = c.get("/citations").text
    assert "/documents?cite=src:1&indexed=1" in t and "news.example" in t and "Who cites whom" in t
    r2 = c.get("/report/2").text
    assert 'id="citations"' in r2 and "NCSC annual 2024" in r2 and "cite=by:2" in r2
    assert 'id="cited-by"' in c.get("/report/1").text
    assert "citing report 1" in c.get("/documents?cite=doc:1").text


def test_a_home_page_deep_in_a_shared_portal_is_matched_by_its_path(library):
    with db.session() as con:
        con.execute("UPDATE sources SET homepage='https://portal.example/government/organisations/ncsc' WHERE id=1")
        con.execute("INSERT INTO sources(id,key,country,agency,type,homepage) VALUES(5,'GB/OTHER2','GB','Other2','cyber','https://portal.example/government/organisations/other2')")
        con.execute("UPDATE doc_text SET body=? WHERE rowid=3", ("https://portal.example/government/organisations/ncsc/about and https://portal.example/other-page",))
    citations.index()
    with db.session() as con:
        rows = {x["url"]: x["target_source"] for x in con.execute("SELECT url, target_source FROM doc_links WHERE doc_id=3")}
    assert rows["portal.example/government/organisations/ncsc/about"] == 1       # on that source's path
    assert rows["portal.example/other-page"] is None                              # elsewhere on the portal: nobody's
