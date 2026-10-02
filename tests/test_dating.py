"""Dates for undated reports: the evidence rules, and that no year is ever overwritten."""
import datetime as dt

import pytest

from rozvedka import dating, db


@pytest.mark.parametrize("text,year,kind", [
    ("SECURITY INFORMATION SERVICE\nAnnual Report 2023\nContents", 2023, "heading"),
    ("Verfassungsschutzbericht 2022\nBundesministerium des Innern", 2022, "heading"),
    ("Výroční zpráva Bezpečnostní informační služby za rok 2021", 2021, "heading"),
    ("Informe Anual de Seguridad Nacional 2020", 2020, "heading"),
    ("2021-2022 Intelligence report of the State Security", 2022, "heading"),       # a range: its end year
    ("防衛白書 2023年版", 2023, "heading"),
    ("Brussels, 12 February 2022\nThreat landscape note", 2022, "date"),
    ("The report was published in December 2013.", 2013, "date"),                  # a date, not a heading
    ("© 2019 Europol", 2019, "date"),
])
def test_from_text(text, year, kind):
    y, source = dating.from_text(text, [0])
    assert y == year
    assert ("publication date" in source) == (kind == "date")
    assert source.startswith("text: “")


def test_cover_page_wins_and_future_years_are_ignored():
    body = "Annual Report 2019\n" + "x " * 600 + "\nAnnual Report 2017 Annual Report 2017 Strategy 2035"
    assert dating.from_text(body, [0, 30, len(body)])[0] == 2019
    assert dating.from_text(f"Outlook {dt.date.today().year + 3}", [0]) is None
    assert dating.from_text("no years here", [0]) is None


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init()
    from rozvedka import topics
    topics.init()
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil')")
        for i, (year, text) in enumerate([(None, "Annual Report 2018"), (2015, "Annual Report 2018"), (None, "nothing")], 1):
            con.execute("INSERT INTO documents(id,source_id,url,title,year,status) VALUES(?,1,?,?,?,'downloaded')",
                        (i, f"u{i}", "Download PDF", year))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", text))
            con.execute("INSERT INTO doc_index(doc_id,chars,pages) VALUES(?,?,?)", (i, len(text), "[0]"))
    return tmp_path


def test_date_documents_only_fills_gaps(library):
    stats = dating.date_documents()
    assert stats["undated_before"] == 2 and stats["from a report heading"] == 1 and stats["no evidence"] == 1
    with db.session() as con:
        rows = {r["id"]: (r["year"], r["year_source"]) for r in con.execute("SELECT id, year, year_source FROM documents")}
    assert rows[1][0] == 2018 and rows[1][1].startswith("text: “Annual Report 2018”")
    assert rows[2] == (2015, None)                     # a year from the title is never replaced
    assert rows[3] == (None, None)


def test_hand_edit_is_marked(library):
    from fastapi.testclient import TestClient

    from rozvedka.app import app
    dating.date_documents()
    with TestClient(app) as client:
        client.post("/doc/1/edit", data={"title": "Annual Report", "lang": "en", "year": "2017"})
        client.post("/doc/2/edit", data={"title": "Annual Report", "lang": "en", "year": "2015"})
    with db.session() as con:
        assert con.execute("SELECT year, year_source FROM documents WHERE id=1").fetchone()[:] == (2017, "set by hand")
        assert con.execute("SELECT year, year_source FROM documents WHERE id=2").fetchone()[:] == (2015, None)
