"""Research notebooks: passages found in a report's text, widened to sentences, cited, exported, merged from backups."""
import json
import re

import pytest
import yaml
from fastapi.testclient import TestClient

from rozvedka import actors, collect, dataset, db, notebooks, series, topics

BODY = ("Introduction page one. " * 3 + "\f"
        "The service observed Russian cyber-espionage against ministries in 2024. Its targets included "
        "infra-\nstructure operators. A new sentence follows here.\f"
        "Page three closes the report.")


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(notebooks, "path", lambda: tmp_path / "notebooks.yaml")
    db.init()
    collect.init()
    topics.init()
    actors.init()
    pages = [0] + [i + 1 for i, ch in enumerate(BODY) if ch == "\f"]
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,name_en,type,active) VALUES(1,'CZ/BIS','CZ','BIS','Security Information Service','intelligence-civil',1)")
        con.execute("INSERT INTO sources(id,key,country,agency,type,active,publisher) VALUES(2,'XX/TT','XX','Think','think-tank',1,'independent')")
        for i, src, url in ((1, 1, "https://www.bis.cz/ar2024.pdf"), (2, 2, "https://think.example/r.pdf"), (3, 1, "https://mirror.example/x.pdf")):
            con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,local_path,sha256,downloaded_at)
                           VALUES(?,?,?,?,'en',2024,'downloaded',?,?,'2026-10-01T10:00:00')""",
                        (i, src, url, f"Annual Report {i}", f"f{i}.pdf", f"sha{i}"))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", BODY))
            con.execute("INSERT INTO doc_index(doc_id,chars,words,pages) VALUES(?,?,?,?)", (i, len(BODY), 40, json.dumps(pages)))
        con.execute("INSERT INTO uploads(doc_id,added_at,via,official) VALUES(3,'2026-10-02','hand',0)")
    return tmp_path


def test_find_tolerates_how_a_pdf_copy_differs():
    at = notebooks.find(BODY, "THE SERVICE observed\nRussian  cyber espionage")
    assert at and BODY[at[0]:at[1]].startswith("The service") and BODY[at[0]:at[1]].endswith("espionage")
    assert notebooks.find(BODY, "operators. A new") and notebooks.find(BODY, "included infra- structure")
    assert notebooks.find(BODY, "not in the report at all") is None and notebooks.find(BODY, "…") is None


def test_quote_widen_cite_and_export(library):
    r = notebooks.add_text(1, "Its targets included infra- structure operators.", note="key finding")
    assert r["notebook"] == "Notes" and "added" in r                    # the first passage makes a notebook "Notes"
    assert notebooks.add_text(1, "Its targets included infra- structure operators.")["exists"] == r["added"]
    assert "error" in notebooks.add_text(1, "words that are not there")
    s = BODY.index("Russian")
    notebooks.add(2, s, s + len("Russian"), widen=True)                 # a name → its whole sentence
    notebooks.add(3, s, s + 7, widen=True)
    nb = notebooks.notebook("notes")
    q = [x["quote"] for x in nb["notes"]]
    assert q[0] == "Its targets included infra- structure operators."   # kept as worded in the text (line break → space)
    assert q[1] == "The service observed Russian cyber-espionage against ministries in 2024."
    assert [x["page"] for x in nb["notes"]] == [2, 2, 2]
    c0, c1, c2 = (x["cite"] for x in nb["notes"])
    assert c0["text"] == "BIS – Security Information Service (CZ), “Annual Report 1”, 2024, p. 2. Retrieved 2026-10-01."
    assert c0["url"] == "https://www.bis.cz/ar2024.pdf" and c0["kind"] == "official" and not c0["warn"]
    assert c1["kind"] == "think tank" and "outside the agency's official domains" in c2["warn"]
    md = notebooks.markdown("notes", "http://pi:8080")
    assert "> Its targets included infra- structure operators. [1]" in md and "key finding" in md
    assert "1. BIS – Security Information Service (CZ)" in md and "<https://www.bis.cz/ar2024.pdf>" in md
    assert "– think tank" in md and "http://pi:8080/report/1" in md
    # notes can be edited, moved and removed
    ids = [x["id"] for x in nb["notes"]]
    notebooks.set_note("notes", ids[1], "think tank's view")
    notebooks.move("notes", ids[2], -1)
    notebooks.remove("notes", ids[0])
    nb = notebooks.notebook("notes")
    assert [x["id"] for x in nb["notes"]] == [ids[2], ids[1]] and nb["notes"][1]["note"] == "think tank's view"


def test_notebooks_and_current(library):
    assert notebooks.create("Sabotage 2024")["added"] == "sabotage-2024"
    assert notebooks.create("sabotage 2024")["exists"] == "sabotage-2024"
    notebooks.create("Second")
    assert notebooks.overview()["current"] == "second"
    notebooks.add_text(1, "Page three closes the report.")
    assert [b["n"] for b in notebooks.overview()["notebooks"]] == [0, 1]   # went to the current one
    notebooks.set_current("sabotage-2024")
    notebooks.delete("sabotage-2024")
    assert notebooks.overview()["current"] == "second" and "never committed" in notebooks.path().read_text()


def test_merge_from_a_backup_ties_passages_to_this_library(library):
    notebooks.add_text(1, "Page three closes the report.")
    theirs = yaml.safe_load(notebooks.path().read_text())
    theirs["notebooks"][0]["notes"][0]["doc"] = 999                      # another library's report id
    theirs["notebooks"].append({"name": "From elsewhere", "slug": "../../etc", "notes": [
        {"id": "aaaa1111", "doc": 5, "sha256": "sha2", "quote": "<script>x</script>", "start": 1, "end": 5, "page": 1},
        {"id": "bbbb2222", "doc": 1, "url": "https://gone.example/x.pdf", "quote": "q"},       # not in this library
        {"id": "bad id!", "doc": 1, "quote": "q"}, "junk"]})
    notebooks.path().unlink()
    r = notebooks.merge(theirs)
    assert r == {"added": 2, "missing": 1}
    o = {b["slug"]: b for b in notebooks.load()["notebooks"]}
    assert o["notes"]["notes"][0]["doc"] == 1                             # found again by its file's checksum
    assert "etc" in o and o["etc"]["notes"][0]["doc"] == 2                # slug made safe; tied by sha256
    assert notebooks.merge(theirs)["added"] == 0                          # merging twice adds nothing
    with db.session() as con:
        assert any("notebooks (2 notebooks, 2 quoted passages)" in x for x in dataset.personal_holdings(con))


def test_pages(library):
    from rozvedka.app import app
    client = TestClient(app)
    t = client.get("/report/1").text
    assert 'action="/notebooks/add-text"' in t and 'href="#quote"' in t and "a new notebook “Notes”" in t
    r = client.post("/notebooks/add-text", data={"doc": 1, "text": "The service observed Russian", "back": "/report/1#quote"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/report/1?nb=Added") and r.headers["location"].endswith("#quote")
    assert "open the notebooks" in client.get(r.headers["location"]).text
    r = client.post("/notebooks/add-text", data={"doc": 1, "text": "x", "back": "https://evil.example/"}, follow_redirects=False)
    assert r.headers["location"].startswith("/report/1?nb=Not+added")     # never redirected off the site
    t = client.get("/notebooks").text
    assert "Notes" in t and "current" in t
    t = client.get("/notebooks/notes").text
    assert "The service observed Russian" in t and "official address" in t and "open the PDF at p. 2" in t
    md = client.get("/notebooks/notes/export.md")
    assert md.headers["content-disposition"] == 'attachment; filename="notes.md"' and "## Sources" in md.text
    p = client.get("/notebooks/notes/print").text
    assert "window.print()" in p and "https://www.bis.cz/ar2024.pdf" in p
    assert client.get("/notebooks/nope").status_code == 404
    nid = notebooks.notebook("notes")["notes"][0]["id"]
    client.post("/notebooks/note", data={"slug": "notes", "id": nid, "note": "<b>mine</b>"})
    assert "&lt;b&gt;mine&lt;/b&gt;" in client.get("/notebooks/notes").text
    assert re.search(r"Notebooks", client.get("/views").text)


def test_slugs():
    assert notebooks.slugify("Sabotage in Europe 2024–2025") == "sabotage-in-europe-2024-2025"
    assert notebooks.slugify("Диверсии в Европе") == "диверсии-в-европе" and notebooks.slugify("Šifrování & co.") == "sifrovani-co"
    assert notebooks.slugify("***") == "notebook" and notebooks.slugify("../../etc") == "etc"
