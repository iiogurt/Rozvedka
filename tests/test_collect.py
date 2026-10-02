"""To collect: hand uploads with provenance, the inbox, missing editions and the page itself."""
import datetime as dt
import io

import pytest

from rozvedka import collect, db, downloader, series

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(downloader, "FILES", tmp_path / "files")
    monkeypatch.setattr(collect, "DATA", tmp_path)
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    db.init()
    collect.init()
    with db.session() as con:
        con.execute("""INSERT INTO sources(id,key,country,agency,type,access,homepage)
                       VALUES(1,'SE/Säpo','SE','Säpo','intelligence-civil','manual','https://www.sakerhetspolisen.se/')""")
        con.execute("INSERT INTO pages(id,source_id,url,lang,kind) VALUES(1,1,'https://www.sakerhetspolisen.se/publikationer','sv','archive')")
        con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,error)
                       VALUES(1,1,'https://www.sakerhetspolisen.se/lagesbild-2024.pdf','Lägesbild 2024','sv',2024,'browser-only','web page')""")
        for i, y in enumerate((2020, 2021, 2023), start=2):
            con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,local_path)
                           VALUES(?,1,?,?,'sv',?,'downloaded',?)""", (i, f"https://www.sakerhetspolisen.se/l{y}.pdf",
                                                                      f"Säkerhetspolisens lägesbild {y}", y, f"x{i}.pdf"))
        con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,local_path)
                       VALUES(9,1,'https://www.sakerhetspolisen.se/other2022.pdf','Säpo yearbook 2022','sv',2022,'downloaded','x9.pdf')""")
    return tmp_path


def pdf_file(tmp_path, name="r.pdf", data=PDF):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_upload_new_report_with_provenance(library):
    r = collect.add_file(1, "https://www.sakerhetspolisen.se/lagesbild-2025.pdf", pdf_file(library), title="Lägesbild 2025",
                         lang="sv", year="2025", original_name="lagesbild.pdf")
    assert r["status"] == "downloaded" and r["official"]
    with db.session() as con:
        d = con.execute("SELECT * FROM documents WHERE id=?", (r["doc_id"],)).fetchone()
        u = con.execute("SELECT * FROM uploads WHERE doc_id=?", (r["doc_id"],)).fetchone()
    assert d["origin"] == "upload" and d["year"] == 2025 and (library / "files" / d["local_path"]).exists()
    assert u["via"] == "upload" and u["official"] == 1 and u["original_name"] == "lagesbild.pdf"


def test_upload_attaches_to_blocked_report_and_flags_unofficial_url(library):
    r = collect.add_file(1, "https://www.sakerhetspolisen.se/lagesbild-2024.pdf", pdf_file(library))
    assert r["doc_id"] == 1 and r["status"] == "downloaded"
    assert collect.blocked() == []
    other = collect.add_file(1, "https://mirror.example.org/x.pdf", pdf_file(library, data=PDF + b"%x"))
    assert other["status"] == "downloaded" and not other["official"]
    dup = collect.add_file(1, "https://www.sakerhetspolisen.se/copy.pdf", pdf_file(library))
    assert dup["status"] == "duplicate"


def test_refuses_non_pdf_and_bad_url(library):
    with pytest.raises(ValueError, match="not a PDF"):
        collect.add_file(1, "https://www.sakerhetspolisen.se/a.pdf", pdf_file(library, "a.pdf", b"<html>"))
    with pytest.raises(ValueError, match="official URL"):
        collect.add_file(1, "ftp://x", pdf_file(library))


def test_inbox_import_moves_the_file(library):
    (library / "inbox" / "Säpo").mkdir(parents=True)
    pdf_file(library / "inbox" / "Säpo", "lagesbild_2019.pdf")
    (f,) = collect.inbox()
    assert f["source_id"] == 1 and f["year"] == 2019 and f["path"] == "Säpo/lagesbild_2019.pdf"
    r = collect.import_inbox(f["path"], 1, "https://www.sakerhetspolisen.se/l2019.pdf", year="2019", lang="sv")
    assert r["status"] == "downloaded" and collect.inbox() == []
    with pytest.raises(ValueError):
        collect.import_inbox("../t.db", 1, "https://x.se/a.pdf")


def test_missing_editions_with_candidates_and_attach(library):
    with db.session() as con:
        series.confirm(series.propose(con)[0], name="Lägesbild")
    miss = collect.missing_editions(today=dt.date(2026, 3, 1))
    by_year = {m["year"]: m for m in miss}
    assert by_year[2022]["state"] == "missing" and [c["id"] for c in by_year[2022]["candidates"]] == [9]
    # 2024: the next expected edition; the blocked "Lägesbild 2024" (other title) is offered as the candidate
    assert by_year[2024]["state"] == "expected" and [c["id"] for c in by_year[2024]["candidates"]] == [1]
    assert 2025 not in by_year and by_year[2022]["pages"][0]["kind"] == "archive"
    series.attach_url("SE/Säpo", "Lägesbild", "https://www.sakerhetspolisen.se/other2022.pdf")
    assert 2022 not in {m["year"] for m in collect.missing_editions(today=dt.date(2026, 3, 1))}


def test_manual_sources_and_checked(library):
    (m,) = collect.manual_sources()
    assert m["why"].startswith("bot-protected") and m["check"] is None
    collect.checked(1, "nothing new on the site")
    (m,) = collect.manual_sources()
    assert m["check"]["note"] == "nothing new on the site"


def test_collect_pages_and_upload_form(library):
    from fastapi.testclient import TestClient

    from rozvedka.app import app
    with db.session() as con:
        series.confirm(series.propose(con)[0], name="Lägesbild")
    with TestClient(app) as client:
        for tab in ("missing", "blocked", "manual", "inbox"):
            assert client.get(f"/collect?tab={tab}").status_code == 200, tab
        r = client.post("/collect/upload", data={"source_id": "1", "url": "https://www.sakerhetspolisen.se/lagesbild-2024.pdf"},
                        files={"file": ("l.pdf", io.BytesIO(PDF), "application/pdf")},
                        headers={"referer": "http://testserver/collect?tab=blocked"}, follow_redirects=False)
        assert r.status_code == 303 and "added=1" in r.headers["location"] and "official=1" in r.headers["location"]
        bad = client.post("/collect/upload", data={"source_id": "1", "url": "https://www.sakerhetspolisen.se/z.pdf"},
                          files={"file": ("z.pdf", io.BytesIO(b"nope"), "text/plain")}, follow_redirects=False)
        assert "error=" in bad.headers["location"]
