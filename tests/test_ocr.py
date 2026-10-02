"""OCR: which reports are recognised, how the text is stored and marked, and that it is kept afterwards."""
import json

import pytest

from rozvedka import db, ocr, topics


def test_langs_for():
    assert ocr.langs_for("es", {"spa", "eng"}) == "spa+eng"
    assert ocr.langs_for("en", {"spa", "eng"}) == "eng"
    assert ocr.langs_for("xx", {"eng"}) == "eng"
    assert ocr.langs_for("cs", {"eng"}) == "eng"            # language data missing: English only


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init()
    topics.init()
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'PE/INDECI','PE','INDECI','civil-protection')")
        rows = [(1, 10, 300, "es"),      # scanned: 300 characters on 10 pages
                (2, 10, 90000, "es"),    # a normal text layer
                (3, 2, 1500, "en")]      # short and small
        for i, pages, chars, lang in rows:
            con.execute("""INSERT INTO documents(id,source_id,url,title,lang,status,local_path,pages_count)
                           VALUES(?,1,?,?,?,'downloaded',?,?)""", (i, f"u{i}", f"Doc {i}", lang, f"f{i}.pdf", pages))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", "x" * chars))
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages,extracted_at) VALUES(?,?,?,?,?)",
                        (i, chars, "h", "[0]", "2026-01-01"))
    monkeypatch.setattr(ocr, "OCRMYPDF", "/usr/bin/true")
    monkeypatch.setattr(ocr, "TESSERACT", "/usr/bin/true")
    monkeypatch.setattr(ocr, "installed_langs", lambda: {"eng", "spa"})
    monkeypatch.setattr(ocr, "tesseract_version", lambda: "tesseract 5.5.0")
    monkeypatch.setattr(ocr, "recognise", fake_recognise)
    from rozvedka import actor_sources
    monkeypatch.setattr(actor_sources, "GAZETTEER", tmp_path / "no-gazetteer.json")   # actor matching not part of this test
    return tmp_path


def fake_recognise(doc, langs):
    """Stands in for Tesseract (module level, so the worker processes can import it)."""
    if doc["id"] == 3:
        return {"id": 3, "error": "page too large"}
    return {"id": doc["id"], "text": "Informe de emergencias 2019\n" + "Página dos " * 60 + "\n", "pages": [0, 28], "error": None}


def test_candidates(library):
    with db.session() as con:
        assert [c["id"] for c in ocr.candidates(con)] == [3, 1]       # fewest pages first; 2 has a text layer


def test_run_stores_marked_text_and_keeps_it(library):
    stats = ocr.run(workers=1)
    assert stats["recognised"] == 1 and stats["failed"] == 1
    with db.session() as con:
        body = con.execute("SELECT body FROM doc_text WHERE rowid=1").fetchone()[0]
        ix = con.execute("SELECT * FROM doc_index WHERE doc_id=1").fetchone()
        failed = json.loads(con.execute("SELECT ocr FROM doc_index WHERE doc_id=3").fetchone()[0])
        assert body.startswith("Informe de emergencias 2019")
        meta = json.loads(ix["ocr"])
        assert meta["engine"] == "tesseract 5.5.0" and meta["langs"] == "spa+eng" and json.loads(ix["pages"]) == [0, 28]
        assert ix["taxonomy_hash"] is not None              # re-classified right after (topics.index ran)
        assert failed["error"] == "page too large"
        assert ocr.candidates(con) == []                     # nothing is recognised twice
    # a full re-extraction must not bring back the empty text layer of the recognised report
    with db.session() as con:
        q = con.execute("""SELECT d.id FROM documents d LEFT JOIN doc_index i ON i.doc_id = d.id
                           WHERE d.status = 'downloaded' AND d.local_path IS NOT NULL
                           AND (i.ocr IS NULL OR i.ocr LIKE '%"error"%' OR i.ocr LIKE '%no_gain%')""").fetchall()
    assert 1 not in {r[0] for r in q}
