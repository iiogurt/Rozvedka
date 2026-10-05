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
    ("Strasbourg 18. juuli 2024", 2024, "date"),                                   # Estonian month
    ("Strasbūrā 2024. gada 18. jūlijā", 2024, "date"),                             # Latvian: year first
    ("Strasbūras 2024 m. liepos 18 d.", 2024, "date"),                             # Lithuanian: year first
    ("НАРЪЧНИК НА RAN ЮНИ 2017 г.", 2017, "date"),                                 # Bulgarian month
    ("Utgitt av Direktoratet for samfunnssikkerhet og beredskap (DSB) 2025", 2025, "date"),
    ("Traficomin julkaisuja 11/2025", 2025, "date"),
    ("平成29年版 防災白書", 2017, "heading"),                                          # Japanese era years
    ("令和３年版防災白書", 2021, "heading"),
])
def test_from_text(text, year, kind):
    y, source = dating.from_text(text, [0])
    assert y == year
    assert ("publication date" in source) == (kind == "date")
    assert source.startswith("text: “")


def test_law_numbers_are_not_dates():
    assert dating.from_text("Act No. 153/1994 Coll. on the Protection of Classified Information " * 3, [0], cover=False) is None


def test_lone_year_on_a_title_page_only():
    cover = "Krisescenarioer 2016 – analyser av alvorlige hendelser"
    y, source = dating.from_text(cover + "\n" + "tekst " * 400, [0, len(cover) + 1])
    assert y == 2016 and "only year on the cover" in source
    prose = "Since Europol first looked at these networks in 2024, much has changed. " * 12   # a page of prose
    assert dating.from_text(prose + "\nmore", [0, len(prose)]) is None


@pytest.mark.parametrize("title,url,year,evidence", [
    ("平成28年版防災白書（ html 、 PDF ）", "https://www.bousai.go.jp/kaigirep/hakusho/pdf/H28_honbun.pdf", 2016, "Japanese era"),
    ("Read online", "https://stratcomcoe.org/pdfjs/?file=/publications/download/Defence-StratCom-Spring-2026.pdf?zoom=page-fit",
     2026, "file name"),
    ("More about our priorities", "https://commission.europa.eu/document/download/x_bg?filename=Political%20Guidelines%202024-2029_BG.pdf",
     2024, "file name"),
    ("Télécharger", "https://www.sgdsn.gouv.fr/files/20260611_SGDSN_VIGINUM_Rapport.pdf", 2026, "date stamp"),
    ("Checkliste", "https://www.dsn.gv.at/files/456_checkliste_dsn_a4_v20241008_bf.pdf", 2024, "date stamp"),
])
def test_from_address(title, url, year, evidence):
    y, source = dating.from_address(title, url)
    assert y == year and evidence in source


def test_from_address_ignores_ids_and_impossible_dates():
    assert dating.from_address("Report", "https://x.org/files/20251399_report.pdf") is None      # month 13
    assert dating.from_address("Report", "https://x.org/document/42?id=2019") is None             # not a file name


def test_folder_of_viewer_links():
    assert dating.folder_of("https://stratcomcoe.org/pdfjs/?file=/publications/download/A.pdf?zoom=1") == \
        "stratcomcoe.org/publications/download/"
    assert dating.folder_of("https://www.ipcc.ch/report/ar6/wg1/downloads/report/IPCC_AR6_WGI_TS.pdf") == \
        "www.ipcc.ch/report/ar6/wg1/downloads/report/"


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


def test_folder_rule(library):
    with db.session() as con:
        for i, (url, year, src) in enumerate([("https://a.org/r/2021/x1.pdf", 2021, None), ("https://a.org/r/2021/x2.pdf", 2021, None),
                                               ("https://a.org/r/2021/x3.pdf", 2021, "text: “x”"),
                                               ("https://a.org/r/2021/x4.pdf", 2023, "folder: …"),       # from this rule: ignored
                                               ("https://a.org/r/2021/new.pdf", None, None), ("https://a.org/r/2021/own.pdf", None, None),
                                               ("https://b.org/s/y1.pdf", 2020, None), ("https://b.org/s/y2.pdf", 2021, None),
                                               ("https://b.org/s/y3.pdf", 2021, None), ("https://b.org/s/new.pdf", None, None)], 10):
            con.execute("INSERT INTO documents(id,source_id,url,title,year,year_source,status) VALUES(?,1,?,'x',?,?,'downloaded')",
                        (i, url, year, src))
        y, source = dating.from_folder(con, 14, "https://a.org/r/2021/new.pdf")
        assert y == 2021 and source == "folder: all 3 dated reports in a.org/r/2021/ are from 2021"
        assert dating.from_folder(con, 15, "https://a.org/r/2021/own.pdf", "Strategy 2025–2030") is None   # own year differs
        assert dating.from_folder(con, 19, "https://b.org/s/new.pdf") is None                                # siblings disagree


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
