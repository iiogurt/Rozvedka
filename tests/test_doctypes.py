"""Document types: rules on title and file name, series and page count; hand corrections win; statements, finance
tables and forms are left out of every count but stay on Documents behind the type filter."""
import re

import pytest
import yaml
from fastapi.testclient import TestClient

from rozvedka import collect, db, doclist, doctypes, series, topics, trends


@pytest.mark.parametrize("title, url, pages, per_year, expected", [
    ("Výroční zpráva BIS 2023", "https://bis.cz/vz2023.pdf", 40, None, "annual"),
    ("Annual Threat Assessment 2024", "https://odni.gov/ata.pdf", 30, None, "assessment"),     # assessment before annual
    ("'Annual Report 2016-2017' Press release.", "https://isc.gov.uk/pr.pdf", 3, None, "statement"),
    ("Download", "https://isc.gov.uk/20171220_ISC_Press_Release.pdf", 3, None, "statement"),  # from the file name
    ("Správa k návrhu záverečného účtu za rok 2018", "https://sis.gov.sk/x.pdf", 14, None, "finance"),
    ("Impact report form (.pdf 32kb)", "https://civildefence.govt.nz/f.pdf", 2, None, "form"),
    ("Was macht der NDB gegen Spionage?", "https://vbs.admin.ch/Spionage-Faktenblatt-de.pdf", 3, None, "guide"),
    ("Stratégie nationale en matière de cybersécurité", "https://hcpn.lu/s.pdf", 23, None, "strategy"),
    ("Der strategische Wert von Übungen", "https://babs.admin.ch/w.pdf", 36, None, "report"),     # adjective: not a strategy
    ("平成25年版防災白書", "https://bousai.go.jp/h25.pdf", 200, None, "annual"),
    ("Trends and challenges 3rd Quarter 2022", "https://ria.ee/q3.pdf", 2, None, "bulletin"),
    ("Krajobraz bezpieczeństwa polskiego Internetu", "https://cert.pl/k.pdf", 149, 1, "annual"),  # series edition
    ("MELANI 2019/2", "https://ncsc.admin.ch/m.pdf", 50, 2, "annual"),
    ("Annual", "https://x.org/a.pdf", 2, None, "report"),            # "annual" alone on 2 pages: not the report itself
    ("Something", "https://x.org/s.pdf", 60, None, "report"),
])
def test_rules(title, url, pages, per_year, expected):
    t, why = doctypes.classify(title, url, pages, per_year)
    assert t == expected, why
    assert why


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(doctypes, "TYPES_FILE", tmp_path / "doc_types.yaml")
    db.init()
    collect.init()
    topics.init()
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(1,'UK/ISC','GB','ISC','other',1)")
        for i, title in enumerate(["Annual Report 2023", "'Iran' Press release", "Budget 2023", "Iran report"], 1):
            con.execute("""INSERT INTO documents(id,source_id,url,title,year,status,pages_count)
                           VALUES(?,1,?,?,2023,'downloaded',40)""", (i, f"https://isc.gov.uk/{i}.pdf", title))
    return tmp_path


def test_counts_leave_out_non_reports(library):
    assert doctypes.type_documents() == {"annual": 1, "statement": 1, "finance": 1, "report": 1}
    with db.session() as con:
        n = con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {trends.LISTED}").fetchone()[0]
    assert n == 2
    assert doclist.count() == 2 and doclist.count(all_types=1) == 4 and doclist.count(doc_type="statement") == 1
    from rozvedka.app import app
    client = TestClient(app)
    t = client.get("/documents").text
    assert re.search(r"<b>2</b> documents match", t) and "+ 2 statements, finance tables and forms not counted" in t
    assert re.search(r"<b>4</b> documents match", client.get("/documents?doc_type=all").text)
    t = client.get("/documents?doc_type=statement").text
    assert re.search(r"<b>1</b> documents match", t) and "watch-btn" not in t      # no query form for a type filter
    assert "“press release” in the title or file name" in client.get("/report/2").text


def test_hand_correction_wins_and_is_kept(library):
    from rozvedka.app import app
    doctypes.type_documents()
    TestClient(app).post("/doc/2/type", data={"doc_type": "report"})
    rows = yaml.safe_load((library / "doc_types.yaml").read_text(encoding="utf-8"))
    assert [(r["url"], r["type"]) for r in rows] == [("https://isc.gov.uk/2.pdf", "report")]
    doctypes.type_documents()                                     # the rules run again: the hand type stays
    with db.session() as con:
        assert con.execute("SELECT doc_type, doc_type_why FROM documents WHERE id=2").fetchone()[:] == ("report", "set by hand")
    assert doclist.count() == 3
    assert not doctypes.set_by_hand(2, "nonsense")
