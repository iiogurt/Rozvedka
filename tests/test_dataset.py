"""Datasets: export into parts, verify, compare newer/older, restore into an empty library, merge into an existing
one (by key and address, never by id), catalogue-only and damaged datasets, conflicts and repeat imports."""
import hashlib
import json

import pytest
import yaml

from rozvedka import actor_sources, actors, collect, config, dataset, db, logos, registry, review, series, topics, watch


def use(monkeypatch, root):
    """Point the app at the installation in `root` (its own data folder and sources folder)."""
    data = root / "data"
    for mod, attr, val in ((config, "DATA", data), (config, "FILES", data / "files"), (db, "DB_PATH", data / "rozvedka.db"),
                           (db, "DATA", data), (logos, "LOGOS", data / "logos"),
                           (actor_sources, "GAZETTEER", data / "gazetteer" / "actors.json"),
                           (series, "SERIES_FILE", root / "sources" / "series.yaml"),
                           (watch, "WATCHLIST", root / "sources" / "watchlist.yaml"),
                           (review, "REVIEWS", root / "sources" / "actor_reviews.yaml"),
                           (collect, "INBOX", data / "inbox")):
        monkeypatch.setattr(mod, attr, val)
    monkeypatch.setattr(dataset, "_sources_dir", lambda: root / "sources")
    (root / "sources").mkdir(parents=True, exist_ok=True)
    db.init()
    collect.init()
    topics.init()
    actors.init()


def add_doc(con, files, i, source_id, url, year=2024, body=b"%PDF-1.4 report", status="downloaded", **kw):
    rel = f"cz/{i}.pdf"
    if status == "downloaded":
        (files / "cz").mkdir(parents=True, exist_ok=True)
        (files / rel).write_bytes(body)
    sha = hashlib.sha256(body).hexdigest() if status == "downloaded" else None
    vals = dict(id=i, source_id=source_id, url=url, title=f"Report {url.rsplit('/', 1)[-1]}", lang="en", year=year, status=status,
                local_path=rel if status == "downloaded" else None, sha256=sha, size=len(body),
                discovered_at="2026-09-29 10:00:00", downloaded_at="2026-09-29 11:00:00", **kw)
    con.execute(f"INSERT INTO documents({','.join(vals)}) VALUES({','.join('?' * len(vals))})", list(vals.values()))
    con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", f"text of report {i}"))
    con.execute("INSERT INTO doc_index(doc_id,chars,words,ocr) VALUES(?,?,?,?)", (i, 17, 4, kw.get("_ocr")))


@pytest.fixture
def a(tmp_path, monkeypatch):
    """Installation A: two sources, three reports (one waiting), a logo, a gazetteer and the portal's lists."""
    monkeypatch.setattr(registry, "sync", lambda *x, **k: {"sources": 0, "pages": 0})
    root = tmp_path / "A"
    use(monkeypatch, root)
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,active,logo_path) VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil',1,'1.png')")
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(2,'DE/BfV','DE','BfV','intelligence-civil',1)")
        con.execute("INSERT INTO pages(id,source_id,url,last_crawled) VALUES(1,1,'https://bis.cz/reports','2026-09-30 10:00:00')")
        con.execute("INSERT INTO pages(id,source_id,url,last_crawled) VALUES(2,2,'https://bfv.de/reports','2026-09-30 10:00:00')")
        files = config.FILES
        add_doc(con, files, 1, 1, "https://bis.cz/2024.pdf", body=b"%PDF bis 2024", page_id=1)
        add_doc(con, files, 2, 2, "https://bfv.de/2023.pdf", year=None, body=b"%PDF bfv 2023", page_id=2)
        add_doc(con, files, 3, 2, "https://bfv.de/2025.pdf", status="new", page_id=2)
    (config.DATA / "logos").mkdir(parents=True)
    (config.DATA / "logos" / "1.png").write_bytes(b"PNGLOGO")
    (config.DATA / "gazetteer").mkdir(parents=True)
    (config.DATA / "gazetteer" / "actors.json").write_text(json.dumps({"retrieved": "2026-09-28", "actors": []}))
    watch.save([{"query": "topic:ransomware", "added": "2026-10-01"}])
    return root


def export(tmp_path, name="ds", **kw):
    return dataset.export(tmp_path / name, part_size=6_000, **kw)    # tiny parts: several of them


def test_export_writes_verified_parts(a, tmp_path):
    m = export(tmp_path)
    assert len(m["parts"]) >= 2 and m["scope"]["files_included"] == 2 and sorted(m["files"]) == ["cz/1.pdf", "cz/2.pdf"]
    mpath = dataset.find_manifest(tmp_path / "ds")
    assert dataset.find_manifest(mpath.with_name(m["parts"][1]["name"])) == mpath          # from any part
    assert dataset.verify(mpath)["problems"] == []
    assert m["freshness"]["sources"]["CZ/BIS"]["documents"] == 1 and m["installation"]["id"]


def test_damaged_or_missing_parts_are_refused(a, tmp_path):
    m = export(tmp_path)
    folder = tmp_path / "ds"
    (folder / m["parts"][-1]["name"]).write_bytes(b"x")
    (folder / m["parts"][0]["name"]).unlink()
    r = dataset.import_dataset(folder, check=True)
    assert r["error"].startswith("the dataset is incomplete") and len(r["problems"]) == 2
    assert "missing" in r["problems"][0] and "incomplete" in r["problems"][1]


def test_restore_into_a_new_installation(a, tmp_path, monkeypatch):
    m = export(tmp_path)
    use(monkeypatch, tmp_path / "B")
    check = dataset.import_dataset(tmp_path / "ds", check=True)
    assert check["compare"]["empty_here"] and check["compare"]["documents"]["only_in_dataset"] == 3
    with db.session() as con:
        assert con.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0              # check changed nothing
    r = dataset.import_dataset(tmp_path / "ds", index=False)
    assert r["mode"] == "restore" and r["files"]["written"] == 2 and r["files"]["bad_checksum"] == 0
    assert (config.FILES / "cz" / "1.pdf").read_bytes() == b"%PDF bis 2024"
    with db.session() as con:
        rows = {d["url"]: dict(d) for d in con.execute("SELECT * FROM documents")}
        assert len(rows) == 3 and all(d["dataset"] == m["dataset_id"] for d in rows.values())
        assert rows["https://bfv.de/2025.pdf"]["status"] == "new"                          # still waiting: crawl continues
        logo = con.execute("SELECT logo_path FROM sources WHERE key='CZ/BIS'").fetchone()[0]
        assert (config.DATA / "logos" / logo).read_bytes() == b"PNGLOGO"
        assert con.execute("SELECT body FROM doc_text WHERE rowid=1").fetchone()[0] == "text of report 1"
    assert [i["query"] for i in watch.load()] == ["topic:ransomware"]
    assert (config.DATA / "gazetteer" / "actors.json").exists()
    assert dataset.installation()["id"] != m["installation"]["id"]                      # B keeps its own identity
    assert list((config.DATA / "backups").glob("pre-import-*.db"))
    again = dataset.import_dataset(tmp_path / "ds", index=False)                         # importing twice changes nothing
    assert again["mode"] == "merge" and again["applied"]["documents_added"] == 0 and again["applied"]["documents_updated"] == 0
    assert again["compare"]["verdict"] == "same"
    with db.session() as con:                                                       # B loses a report …
        con.execute("DELETE FROM documents WHERE url='https://bis.cz/2024.pdf'")
    assert dataset.import_dataset(tmp_path / "ds", check=True)["compare"]["verdict"] == "complements"   # … the dataset has it


def test_merge_into_an_existing_library(a, tmp_path, monkeypatch):
    # A keeps working: a new report, a year filled, a hand-corrected year, the logo; then exports
    with db.session() as con:
        add_doc(con, config.FILES, 4, 1, "https://bis.cz/2025.pdf", year=2025, body=b"%PDF bis 2025", page_id=1)
        con.execute("UPDATE documents SET year=2023, year_source='text: “Bericht 2023”' WHERE id=2")
        con.execute("UPDATE pages SET last_crawled='2026-10-04 09:00:00' WHERE id=1")
        con.execute("UPDATE documents SET hidden=1 WHERE id=1")                     # A hid report 1
    m = export(tmp_path)
    # B: built on its own, sources in another order (other ids), report 1 and 2 without files, an own report,
    # and the same file as A's report 4 under another address
    use(monkeypatch, tmp_path / "B")
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(7,'DE/BfV','DE','BfV','intelligence-civil',1)")
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(9,'CZ/BIS','CZ','BIS','intelligence-civil',1)")
        con.execute("INSERT INTO pages(id,source_id,url,last_crawled) VALUES(5,9,'https://bis.cz/reports','2026-09-20 10:00:00')")
        add_doc(con, config.FILES, 31, 9, "https://bis.cz/2024.pdf", status="new", page_id=5)
        add_doc(con, config.FILES, 32, 7, "https://bfv.de/2023.pdf", year=None, status="failed")
        add_doc(con, config.FILES, 33, 7, "https://bfv.de/own.pdf", body=b"%PDF only in B")
        add_doc(con, config.FILES, 34, 9, "https://bis.cz/mirror-2025.pdf", body=b"%PDF bis 2025")
        con.execute("DELETE FROM doc_index WHERE doc_id=32")
    check = dataset.import_dataset(tmp_path / "ds", check=True)
    c = check["compare"]
    assert c["documents"]["only_in_dataset"] == 2 and c["documents"]["only_here"] == 2
    assert c["documents"]["files_to_add"] == 2 and c["documents"]["years_to_fill"] == 1
    assert c["sources"]["dataset newer"] == 2 and c["verdict"] in ("newer", "mixed")
    r = dataset.import_dataset(tmp_path / "ds", index=False)
    assert r["mode"] == "merge"
    with db.session() as con:
        rows = {d["url"]: dict(d) for d in con.execute("SELECT d.*, s.key FROM documents d JOIN sources s ON s.id=d.source_id")}
        assert rows["https://bis.cz/2024.pdf"]["status"] == "downloaded" and rows["https://bis.cz/2024.pdf"]["key"] == "CZ/BIS"
        assert (config.FILES / rows["https://bis.cz/2024.pdf"]["local_path"]).read_bytes() == b"%PDF bis 2024"
        assert rows["https://bfv.de/2023.pdf"]["year"] == 2023 and rows["https://bfv.de/2023.pdf"]["status"] == "downloaded"
        assert rows["https://bis.cz/2025.pdf"]["status"] == "duplicate"                 # same file as B's mirror
        assert rows["https://bfv.de/2025.pdf"]["key"] == "DE/BfV" and rows["https://bfv.de/2025.pdf"]["status"] == "new"
        assert rows["https://bfv.de/own.pdf"]["status"] == "downloaded"                   # B's own report untouched
        assert rows["https://bis.cz/2024.pdf"]["hidden"] == 0                             # conflict: B's state kept
        assert con.execute("SELECT last_crawled FROM pages WHERE id=5").fetchone()[0] == "2026-10-04 09:00:00"
        assert con.execute("SELECT body FROM doc_text WHERE rowid=?", (rows["https://bfv.de/2023.pdf"]["id"],)).fetchone()[0] \
            == "text of report 2"                                                         # text (and OCR) came along
    assert [x["field"] for x in r["applied"]["conflicts"]] == ["hidden"]
    assert "hidden" in dataset.describe(r) or "conflicting" in dataset.describe(r)
    # the same dataset again, preferring its edits: the hidden flag follows the dataset now
    r2 = dataset.import_dataset(tmp_path / "ds", index=False, prefer="dataset")
    with db.session() as con:
        assert con.execute("SELECT hidden FROM documents WHERE url='https://bis.cz/2024.pdf'").fetchone()[0] == 1
    assert r2["applied"]["documents_added"] == 0


def test_older_dataset_adds_nothing(a, tmp_path, monkeypatch):
    export(tmp_path, "old")
    with db.session() as con:                         # A crawls on after the export
        add_doc(con, config.FILES, 5, 2, "https://bfv.de/2026.pdf", body=b"%PDF new", page_id=2)
        con.execute("UPDATE pages SET last_crawled='2026-10-05 08:00:00'")
        con.execute("UPDATE documents SET discovered_at='2026-10-05 08:00:00' WHERE id=5")
    r = dataset.import_dataset(tmp_path / "old", index=False)
    assert r["compare"]["verdict"] == "older" and r["applied"]["documents_added"] == 0
    assert "OLDER" in dataset.describe(r)


def test_catalogue_only_and_since(a, tmp_path, monkeypatch):
    cat = export(tmp_path, "cat", files=False)
    assert cat["scope"]["files_included"] == 0 and cat["bytes"] < 100_000
    with db.session() as con:
        con.execute("UPDATE documents SET downloaded_at='2026-10-03 10:00:00', discovered_at='2026-10-03 10:00:00' WHERE id=2")
    inc = export(tmp_path, "inc", since="2026-10-01")
    assert inc["files"] == ["cz/2.pdf"]
    use(monkeypatch, tmp_path / "C")
    r = dataset.import_dataset(tmp_path / "cat", index=False)
    assert r["mode"] == "restore" and r["files"]["written"] == 0 and r["to_download"] == 2
    with db.session() as con:
        assert {s for (s,) in con.execute("SELECT status FROM documents")} == {"new"}  # to download from the agencies
    r = dataset.import_dataset(tmp_path / "inc", index=False)                         # the newer files arrive
    assert r["files"]["written"] == 1
    with db.session() as con:
        assert con.execute("SELECT status FROM documents WHERE url='https://bfv.de/2023.pdf'").fetchone()[0] == "downloaded"


def test_lists_are_merged(a, tmp_path, monkeypatch):
    review.save([{"actor": "Q1", "url": "https://bis.cz/2024.pdf", "name": "X", "says": "…", "verdict": "wrong", "checked": "2026-10-02"}])
    export(tmp_path)
    use(monkeypatch, tmp_path / "B")
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil',1)")
        add_doc(con, config.FILES, 9, 1, "https://bis.cz/other.pdf", body=b"%PDF other")
    watch.save([{"query": "actor:Wagner", "added": "2026-10-01"}])
    review.save([{"actor": "Q1", "url": "https://bis.cz/2024.pdf", "name": "X", "says": "…", "verdict": "right", "checked": "2026-10-01"}])
    series.save({"series": [], "rejected": ["x"]})
    r = dataset.import_dataset(tmp_path / "ds", index=False)
    assert [i["query"] for i in watch.load()] == ["actor:Wagner", "topic:ransomware"]
    assert [x["verdict"] for x in review.load()] == ["wrong"]                         # the later verdict wins
    assert r["lists"]["watchlist.yaml"] == "1 searches added"
    assert yaml.safe_load((tmp_path / "B" / "sources" / "watchlist.yaml").read_text(encoding="utf-8"))
