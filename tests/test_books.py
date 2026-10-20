"""The local book library (rozvedka/books.py): PDFs and EPUBs read into the library as documents of the type "book" –
metadata with its origin, searched and matched like reports, never counted as reports, never exported."""
import json
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

from rozvedka import app as app_module
from rozvedka import books, collect, dataset, db, doctypes, registry, series, topics, web


def make_epub(path, title="The Shadow War", creator="Jane Doe", isbn="978-0-306-40615-7", chapters=None):
    chapters = chapters or [("Chapter 1", "In 2014 the GRU began a campaign in Crimea."), ("Chapter 2", "Sandworm attacked the grid.")]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", """<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
          <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>""")
        items = "".join(f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(len(chapters)))
        spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
        z.writestr("OEBPS/content.opf", f"""<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">
          <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title><dc:creator>{creator}</dc:creator>
          <dc:publisher>Penguin</dc:publisher><dc:date>2019-05-02</dc:date><dc:language>en</dc:language>
          <dc:identifier>urn:isbn:{isbn}</dc:identifier></metadata><manifest>{items}</manifest><spine>{spine}</spine></package>""")
        for i, (head, text) in enumerate(chapters):
            z.writestr(f"OEBPS/c{i}.xhtml", f"<html><body><h1>{head}</h1><p>{text}</p></body></html>")


def make_pdf(path, pages):
    """A small PDF with one line of text per page (Helvetica), with a correct cross-reference table."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(books, "BOOKS", tmp_path / "books")
    monkeypatch.setattr(books, "STORE", tmp_path / "files" / "books")
    monkeypatch.setattr(books, "CACHE", tmp_path / "books-meta")
    monkeypatch.setattr(topics, "FILES", tmp_path / "files")
    app_module._independent["at"] = None
    db.init()
    collect.init()
    topics.init()
    (tmp_path / "books").mkdir()
    yield tmp_path
    app_module._independent["at"] = None


def test_isbn():
    assert books.to_isbn13("0-306-40615-2") == "9780306406157"           # ISBN-10 → 13
    assert books.to_isbn13("978-0-306-40615-7") == "9780306406157"
    assert books.to_isbn13("978-0-306-40615-8") is None                  # wrong check digit
    assert books.isbns_in("Printed in Poland. ISBN 978-0-306-40615-7 (hardback) ISBN-10: 0306406152") == ["9780306406157"]


def test_epub_and_pdf_are_read(tmp_path):
    make_epub(tmp_path / "a.epub")
    r = books.epub_read(tmp_path / "a.epub")
    assert r["meta"]["title"] == "The Shadow War" and r["meta"]["creators"] == ["Jane Doe"] and r["meta"]["isbn"] == "9780306406157"
    assert [s["heading"] for s in r["sections"]] == ["Chapter 1", "Chapter 2"]
    text, offsets = books.epub_pages(tmp_path / "a.epub")
    assert len(offsets) == 2 and "Sandworm attacked" in text[offsets[1]:]
    make_pdf(tmp_path / "b.pdf", ["Copyright 2021. ISBN 978-0-306-40615-7", "Chapter one about Wagner."])
    p = books.pdf_read(tmp_path / "b.pdf")
    assert p["pages"] == 2 and p["meta"]["isbn"] == "9780306406157"


def test_metadata_precedence():
    hand = {"title": "Corrected title"}
    ol = {"title": "OL title", "authors": [{"name": "J. Doe", "ol": "https://openlibrary.org/authors/OL1A", "wikidata": "Q1"}],
          "publisher": "Penguin Books", "year": 2019, "lang": "en", "url": "https://openlibrary.org/books/OL2M"}
    own = {"title": "File title", "creators": ["Jane Doe"], "date": "2018", "isbn": "9780306406157"}
    m = books.merge(hand, ol, own)
    assert m["title"] == {"value": "Corrected title", "from": "books.yaml"}
    assert m["authors"]["from"] == "Open Library" and m["authors"]["value"][0]["wikidata"] == "Q1"
    assert m["year"] == {"value": 2019, "from": "Open Library"} and m["isbn"]["from"] == "the file"
    assert books.merge({}, None, own)["authors"] == {"value": [{"name": "Jane Doe"}], "from": "the file"}


def test_import_index_and_keep_apart(library, monkeypatch):
    folder = library / "books"
    make_epub(folder / "shadow.epub")
    make_pdf(folder / "wagner.pdf", ["A history. ISBN 0-306-40615-2", "Wagner fought in Syria."])
    (folder / "books.yaml").write_text("- {file: wagner.pdf, title: The Wagner Files, authors: [A. Writer], publisher: Small Press, year: 2023}\n")
    monkeypatch.setattr(books, "open_library", lambda isbn: None)
    st = books.import_books(index=False)
    assert st["files"] == 2 and st["added"] == 2 and not st["unreadable"]
    with db.session() as con:
        rows = {r["file"]: dict(r) for r in con.execute(
            "SELECT b.*, d.doc_type, d.url, d.local_path, s.publisher kind, s.agency FROM books b JOIN documents d ON d.id=b.doc_id JOIN sources s ON s.id=d.source_id")}
    w, e = rows["wagner.pdf"], rows["shadow.epub"]
    assert w["title"] == "The Wagner Files" and json.loads(w["meta"])["title"]["from"] == "books.yaml" and w["agency"] == "Small Press"
    assert e["title"] == "The Shadow War" and e["publisher"] == "Penguin" and e["year"] == 2019 and e["isbn"] == "9780306406157"
    assert {w["doc_type"], e["doc_type"]} == {"book"} and {w["kind"], e["kind"]} == {"book"} and w["url"].startswith("book:")
    assert (library / "files" / w["local_path"]).exists()
    # importing again changes nothing but the metadata
    assert books.import_books(index=False)["added"] == 0
    # the text is read whole, an EPUB section by section
    text, offsets = topics.extract_document(e["local_path"])
    assert "GRU began a campaign" in text and len(offsets) == 2
    # never a report: typed "book", not counted, not a think tank, kept when the registry is synced
    assert doctypes.classify("The Shadow War", "book:978", 300) == ("book", "a book of the local library")
    with db.session() as con:
        sid = con.execute("SELECT id FROM sources WHERE agency='Penguin'").fetchone()[0]
        assert con.execute(f"SELECT COUNT(*) FROM documents d WHERE {doctypes.COUNTED}").fetchone()[0] == 0
    registry.sync()
    with db.session() as con:
        assert con.execute("SELECT active FROM sources WHERE id=?", (sid,)).fetchone()[0] == 1
    assert sid not in web.independent_ids() and 'class="pub-book' in web.pub_mark(sid)
    t = TestClient(app_module.app).get("/books").text
    assert "The Wagner Files" in t and "title from books.yaml" in t and "2 books" in t
    assert "Shadow War" in TestClient(app_module.app).get("/documents?doc_type=book").text
    # a dataset never carries book text
    copy = library / "copy.db"
    src, dst = db.connect(), sqlite3.connect(copy)
    src.backup(dst)
    src.close()
    dataset._drop_books(dst)
    assert dst.execute("SELECT COUNT(*) FROM documents WHERE url LIKE 'book:%'").fetchone()[0] == 0
    assert dst.execute("SELECT COUNT(*) FROM sources WHERE publisher='book'").fetchone()[0] == 0
    assert dst.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0
    dst.close()


def test_chapters_page_labels_and_the_index(library, tmp_path):
    from pypdf import PdfReader, PdfWriter
    from pypdf.constants import PageLabelStyle
    # a PDF with bookmarks and printed page numbers that start at 'i'
    make_pdf(tmp_path / "plain.pdf", ["Front matter", "Chapter one: Wagner", "Chapter two: Sandworm", "Index"])
    w = PdfWriter(clone_from=str(tmp_path / "plain.pdf"))
    w.add_outline_item("One", 1)
    w.add_outline_item("Two", 2)
    w.set_page_label(0, 0, style=PageLabelStyle.LOWERCASE_ROMAN)
    w.set_page_label(1, 3, style=PageLabelStyle.DECIMAL, start=1)
    w.write(tmp_path / "book.pdf")
    chapters, labels = books.pdf_outline(tmp_path / "book.pdf")
    assert chapters == [{"level": 0, "title": "One", "page": 2}, {"level": 0, "title": "Two", "page": 3}]
    assert labels == ["i", "1", "2", "3"]
    # an EPUB's table of contents (EPUB 2 NCX, written by make_epub's spine) → sections
    make_epub(tmp_path / "a.epub")
    with zipfile.ZipFile(tmp_path / "a.epub", "a") as z:
        z.writestr("OEBPS/toc.ncx", """<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>
          <navPoint id="n1"><navLabel><text>Crimea</text></navLabel><content src="c0.xhtml"/></navPoint>
          <navPoint id="n2"><navLabel><text>The grid</text></navLabel><content src="c1.xhtml#x"/></navPoint></navMap></ncx>""")
    opf = zipfile.ZipFile(tmp_path / "a.epub").read("OEBPS/content.opf").decode().replace(
        "<manifest>", '<manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    rebuilt = tmp_path / "b.epub"
    with zipfile.ZipFile(tmp_path / "a.epub") as src, zipfile.ZipFile(rebuilt, "w") as dst:
        for n in dict.fromkeys(src.namelist()):
            dst.writestr(n, opf if n == "OEBPS/content.opf" else src.read(n))
    assert books.epub_toc(rebuilt) == [{"level": 0, "title": "Crimea", "page": 1}, {"level": 0, "title": "The grid", "page": 2}]
    # a printed table of contents, through the page labels
    pages = ["Contents\nIntroduction .......... 1\nThe war ........ 2\nThe peace .... 3\n", "x", "y", "z"]
    assert [c["page"] for c in books.printed_contents(pages, ["i", "1", "2", "3"])] == [2, 3, 4]
    # the book's own index: with or without a comma, wrapped page lists, and it ends where the book goes on
    index = ["INDEX\nA\nEspionage 504, 518\nPutin, Vladimir, 12, 45–47, 210n3\nWagner Group, 7,\n9, 11, 7\n",
             "This page goes on with the text of a judgment of 10 March.\nIt has sentences.\nAnd more sentences.\n"]
    entries = books.parse_index(index, 1)
    assert entries == [{"headword": "Espionage", "pages": ["504", "518"]},
                       {"headword": "Putin, Vladimir", "pages": ["12", "45–47", "210n3"]},
                       {"headword": "Wagner Group", "pages": ["7", "9", "11"]}]
    names = {"vladimir putin": [("Q7747", "person", "Vladimir Putin")]}
    assert books._actor_for("Putin, Vladimir", names) == ("Q7747", None)
    assert books._actor_for("Espionage", names) == (None, "no actor of this name")
    # citations name the printed page
    with db.session() as con:
        books.init_structure()
        con.execute("INSERT INTO sources(id,key,country,agency,type,publisher,active) VALUES(9,'BOOK/X','OTHER','X','book','book',1)")
        con.execute("INSERT INTO documents(id,source_id,url,title,status) VALUES(90,9,'book:x','B','downloaded')")
        con.execute("INSERT INTO books(doc_id,file,format,page_labels) VALUES(90,'b.pdf','pdf','[\"i\", \"1\", \"2\"]')")
        con.execute("INSERT INTO documents(id,source_id,url,title,status) VALUES(91,9,'book:y','E','downloaded')")
        con.execute("INSERT INTO books(doc_id,file,format) VALUES(91,'e.epub','epub')")
    assert books.page_name(90, 2) == "p. 1" and books.page_name(91, 4) == "section 4" and books.page_name(5, 7) == "p. 7"
