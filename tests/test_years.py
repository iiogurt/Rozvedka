"""Year conflicts: stored years contradicted by strong evidence are listed for review, never changed silently;
verdicts go to year_reviews.yaml and are re-applied on every rebuild."""
import pytest
import yaml
from fastapi.testclient import TestClient

from rozvedka import collect, dating, db, topics


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(dating, "YEAR_REVIEWS", tmp_path / "year_reviews.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    db.init()
    collect.init()
    topics.init()
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'UK/ISC','GB','ISC','other')")
        for i, (title, url, year, src, text) in enumerate([
                ("Press release", "https://isc.gov.uk/20170426_press_release.pdf", 2021, None, "Statement."),   # stamp 2017
                ("Annual Report", "https://isc.gov.uk/20220110_report.pdf", 2021, None, "Report."),             # published next year: fine
                ("Download PDF", "https://x.jp/a.pdf", 2000, None, "Annual Report 2018 of the agency"),         # cover heading 2018
                ("Annual Report 2015", "https://x.jp/b.pdf", 2015, None, "Annual Report 2018"),                 # title carries the year
                ("平成24年版防災白書", "https://x.jp/c.pdf", 2000, None, "text"),                                   # era year 2012
                ("Download PDF", "https://x.jp/d.pdf", 2010, "set by hand", "Annual Report 2018"),              # set by hand: left out
        ], 1):
            con.execute("INSERT INTO documents(id,source_id,url,title,year,year_source,status,local_path) VALUES(?,1,?,?,?,?,'downloaded',?)",
                        (i, url, title, year, src, f"f{i}.pdf"))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", text))
            con.execute("INSERT INTO doc_index(doc_id,chars,pages) VALUES(?,?,?)", (i, len(text), "[0]"))
    return tmp_path


def test_rules(library):
    assert dating.find_conflicts() == 3
    found = {c["doc_id"]: (c["stored"], c["found"], c["kind"]) for c in dating.conflicts()}
    assert found == {1: (2021, 2017, "stamp"), 3: (2000, 2018, "heading"), 5: (2000, 2012, "era")}
    assert [c["doc_id"] for c in dating.conflicts(kind="era")] == [5]
    assert dating.conflict_of(3)["evidence"].startswith("text: “Annual Report 2018”")
    assert dating.conflict_of(2) is None


def test_verdicts_are_written_and_reapplied(library):
    dating.find_conflicts()
    assert dating.resolve([1], use_found=True) == 1
    assert dating.resolve([3], use_found=False) == 1
    with db.session() as con:
        assert con.execute("SELECT year, year_source FROM documents WHERE id=1").fetchone()[:] == (2017, "set by hand")
        assert con.execute("SELECT year, year_source FROM documents WHERE id=3").fetchone()[:] == (2000, None)
    rows = yaml.safe_load((library / "year_reviews.yaml").read_text(encoding="utf-8"))
    assert [(r["url"], r["stored"], r["found"], r["verdict"]) for r in rows] == [
        ("https://isc.gov.uk/20170426_press_release.pdf", 2021, 2017, "use"), ("https://x.jp/a.pdf", 2000, 2018, "keep")]
    assert dating.find_conflicts() == 1 and [c["doc_id"] for c in dating.conflicts()] == [5]      # kept one stays out
    # a fresh library (e.g. after a dataset import) gets the "use" verdict applied by the rebuild
    with db.session() as con:
        con.execute("UPDATE documents SET year=2021, year_source=NULL WHERE id=1")
    dating.find_conflicts()
    with db.session() as con:
        assert con.execute("SELECT year, year_source FROM documents WHERE id=1").fetchone()[:] == (2017, "set by hand")


def test_page_and_resolve(library):
    from rozvedka.app import app
    dating.find_conflicts()
    client = TestClient(app)
    t = client.get("/years").text
    assert "3 open conflicts" in t and 'href="/report/1"' in t and "20170426" in t
    assert 'href="/years?kind=stamp">1</a>' in t
    assert "1 year conflict" not in client.get("/documents").text and "3 year conflicts" in client.get("/documents").text
    assert "date stamp in the file name says <b>2017</b>" in client.get("/report/1").text
    # a row's own button acts on that row only, even with other rows ticked
    client.post("/years/resolve?doc=5", data={"action": "keep", "doc": ["1", "3"]})
    assert sorted(c["doc_id"] for c in dating.conflicts()) == [1, 3]
    client.post("/years/resolve", data={"action": "use", "doc": ["1", "3"]})
    assert dating.conflicts() == []
    assert "No open conflict" in client.get("/years").text
