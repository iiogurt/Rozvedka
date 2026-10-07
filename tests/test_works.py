"""Reports, not files: language versions and summaries are grouped into one work and counted once."""
import re

import pytest
import yaml
from fastapi.testclient import TestClient

from rozvedka import collect, db, doclist, series, topics, trends, works


@pytest.mark.parametrize("a, b, same", [
    ("https://valisluureamet.ee/doc/raport/2019-en.pdf", "https://valisluureamet.ee/doc/raport/2019-et.pdf", True),
    ("https://www.ncsc.admin.ch/dam/de/sd-web/x/NCSC_2023-1_HJB_DE.pdf", "https://ncsc.admin.ch/dam/en/sd-web/x/NCSC_2023-1_HJB_EN.pdf", True),
    ("https://vbs.admin.ch/dam/de/sd-web/k/NDB-Flyer-de.pdf", "https://vbs.admin.ch/dam/en/sd-web/k/NDB-Flyer-e.pdf", True),
    ("https://x.org/r.pdf?lang=fr", "https://x.org/r.pdf?lang=en", True),
    ("https://x.org/report-2019.pdf", "https://x.org/report-2020.pdf", False),
])
def test_address_key(a, b, same):
    assert (works.address_key(a) == works.address_key(b)) is same


def test_title_key_and_address_lang():
    assert works.title_key("TE-SAT 2025 - Zusammenfassung") == works.title_key("TE-SAT 2025 - Santrauka") == "te-sat 2025"
    assert works.title_key("VLA 2021 (et)") == works.title_key("VLA 2021 (en)")
    assert works.title_key("Annual Report 2024 (PDF, 2.3 MB)") == "annual report 2024"
    assert works.address_lang("https://europol.europa.eu/documents/es_euorganisedcrimesitrep04-es.pdf") == "es"
    assert works.address_lang("https://x.org/report.pdf") is None


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(works, "WORKS_FILE", tmp_path / "works.yaml")
    db.init()
    collect.init()
    topics.init()
    files = [   # id, source, url, title, lang, year, chars
        (1, 1, "https://bis.cz/vz2023.pdf", "Výroční zpráva BIS 2023", "cs", 2023, 60000),
        (2, 1, "https://bis.cz/ar2023.pdf", "BIS Annual Report 2023", "en", 2023, 58000),       # series: same edition
        (3, 1, "https://bis.cz/vz2022.pdf", "Výroční zpráva BIS 2022", "cs", 2022, 50000),
        (4, 1, "https://bis.cz/ar2022.pdf", "BIS Annual Report 2022", "en", 2022, 49000),
        (5, 2, "https://europol.europa.eu/tesat-2025.pdf", "TE-SAT 2025", "en", 2025, 110000),
        (6, 2, "https://europol.europa.eu/tesat-2025-de.pdf", "TE-SAT 2025 - Zusammenfassung", "de", 2025, 5000),
        (7, 2, "https://europol.europa.eu/s/tesat-2025-lt.pdf", "TE-SAT 2025 - Santrauka", "lt", 2025, 5100),
        (8, 2, "https://europol.europa.eu/f/a.pdf", "More about our priorities", "en", 2025, 90000),  # generic title,
        (9, 2, "https://europol.europa.eu/f/b.pdf", "More about our priorities", "en", 2025, 80000),  # different documents
        (10, 2, "https://europol.europa.eu/iocta-2025.pdf", "IOCTA 2025", "en", 2025, 70000),
        (11, 1, "https://bis.cz/vz2021.pdf", "Výroční zpráva BIS 2021", "cs", 2021, 50000),
        (12, 1, "https://bis.cz/ar2021.pdf", "BIS Annual Report 2021", "en", 2021, 49000),
    ]
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil',1)")
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(2,'EU/Europol','EU','Europol','police-ct',1)")
        for i, src, url, title, lang, year, chars in files:
            con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,local_path)
                           VALUES(?,?,?,?,?,?,'downloaded',?)""", (i, src, url, title, lang, year, f"f{i}.pdf"))
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash) VALUES(?,?,'x')", (i, chars))
    with db.session() as con:
        series.confirm(series.propose(con)[0], name="Annual Report")
    return tmp_path


def _work(i):
    with db.session() as con:
        return con.execute("SELECT work_id, work_why FROM documents WHERE id=?", (i,)).fetchone()[:]


def test_grouping_rules(library):
    assert works.group() == {"works_with_several_files": 4, "files_not_counted_again": 5}
    assert _work(1)[0] == _work(2)[0] == 2                        # series edition; English unless 30 % shorter
    assert "series" in _work(1)[1]
    assert _work(3)[0] == _work(4)[0] == 4
    assert _work(5)[0] == _work(6)[0] == _work(7)[0] == 5         # the full report represents its summaries
    assert _work(8) == (None, None) and _work(9) == (None, None)  # same generic title, no year: not grouped
    assert _work(10) == (None, None)


def test_counts_are_per_report(library):
    works.group()
    with db.session() as con:
        n = con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {trends.LISTED}").fetchone()[0]
    assert n == 7                                                  # 12 files, 7 reports
    assert doclist.count() == 7 and doclist.count(all_files=1) == 12
    assert doclist.count(lang="cs") == 3                           # asking for a language lists its files
    from rozvedka.app import app
    client = TestClient(app)
    t = client.get("/documents").text
    assert re.search(r"<b>7</b> documents match", t) and "+ 5 other language versions and summaries" in t
    assert re.search(r'also\s+<a href="/report/1"', t)            # the Czech file next to the English one
    assert re.search(r"<b>12</b> documents match", client.get("/documents?all_files=1").text)
    page = client.get("/report/6").text
    assert "Files of this report" in page and 'href="/report/5"' in page and "this one is not counted again" in page


def test_separate_by_hand(library):
    (library / "works.yaml").write_text(yaml.safe_dump({"separate": ["https://europol.europa.eu/tesat-2025-de.pdf"]}))
    works.group()
    assert _work(6) == (None, None) and _work(7)[0] == 5
