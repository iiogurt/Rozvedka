"""Update page: which sources a check visits, progress per page and download, cancelling between pages, the plan,
and the page itself with the header's Update button."""
import datetime as dt
import json
import time

import pytest
from fastapi.testclient import TestClient

from rozvedka import collect, crawler, db, downloader, jobs, progress, series, updater


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(jobs, "logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(crawler.registry, "sync", lambda *a, **k: {})
    monkeypatch.setattr(crawler, "add_patterns", lambda con, src: 0)
    db.init()
    collect.init()
    old = (dt.datetime.now() - dt.timedelta(days=20)).isoformat(timespec="seconds")
    fresh = (dt.datetime.now() - dt.timedelta(days=1)).isoformat(timespec="seconds")
    with db.session() as con:
        for sid, key, cc, agency, access in ((1, "CZ/BIS", "CZ", "BIS", "auto"), (2, "DE/BfV", "DE", "BfV", "auto"),
                                             (3, "SE/Sapo", "SE", "Säpo", "manual")):
            con.execute("INSERT INTO sources(id,key,country,agency,type,access,active) VALUES(?,?,?,?,'intelligence-civil',?,1)",
                        (sid, key, cc, agency, access))
        pages = [(1, 1, "https://bis/a", old, "ok (3 docs, 0 sub-pages)"), (2, 1, "https://bis/b", old, "ok (1 docs, 0 sub-pages)"),
                 (3, 2, "https://bfv/a", fresh, "error: Timeout"), (4, 3, "https://sapo/a", None, None)]
        for pid, sid, url, when, st in pages:
            con.execute("INSERT INTO pages(id,source_id,url,lang,verified,last_crawled,last_status,active) VALUES(?,?,?,'en',1,?,?,1)",
                        (pid, sid, url, when, st))
        for i, sid, status in ((1, 1, "downloaded"), (2, 2, "new"), (3, 2, "new"), (4, 1, "failed")):
            con.execute("INSERT INTO documents(id,source_id,url,title,status,discovered_at) VALUES(?,?,?,?,?,'2026-01-01 10:00:00')",
                        (i, sid, f"https://x/{i}", f"R{i}", status))
    return tmp_path


def fake_crawl_page(con, src, page, langs):
    time.sleep(0.01)
    if "bfv" in page["url"]:
        raise RuntimeError("Timeout")
    con.execute("INSERT OR IGNORE INTO documents(source_id,url,title,status) VALUES(?,?,?,'new')",
                (src["id"], page["url"] + "/new.pdf", "New report"))
    return "ok (1 docs, 0 sub-pages)", 1


def test_selection(library):
    with db.session() as con:
        assert [s["key"] for s, _ in crawler.selection(con)] == ["CZ/BIS", "DE/BfV", "SE/Sapo"]
        assert [s["key"] for s, _ in crawler.selection(con, stale_days=7)] == ["CZ/BIS", "SE/Sapo"]   # BfV checked yesterday
        assert [s["key"] for s, _ in crawler.selection(con, source_ids=[2])] == ["DE/BfV"]
        assert [s["key"] for s, _ in crawler.selection(con, country="cz")] == ["CZ/BIS"]


def test_crawl_reports_progress_and_per_source_results(library, monkeypatch):
    monkeypatch.setattr(crawler, "crawl_page", fake_crawl_page)
    seen = []
    monkeypatch.setattr(progress, "hook", lambda phase, done, total, final, note="": seen.append((phase, done, total, note)))
    stats = crawler.crawl()
    assert stats["pages"] == 4 and stats["new_docs"] == 2 and stats["errors"] == 1 and stats["skipped"] == 1
    assert stats["sources"] == {"CZ/BIS": {"pages": 2, "new": 2, "errors": 0, "skipped": 0},
                                "DE/BfV": {"pages": 1, "new": 0, "errors": 1, "skipped": 0}}
    assert seen[0] == ("Checking report pages", 0, 4, "CZ BIS") and seen[-1][1:3] == (4, 4)
    with db.session() as con:
        run = con.execute("SELECT started_at, finished_at, summary FROM runs WHERE kind='crawl'").fetchone()
    assert run[0] <= run[1] and json.loads(run[2])["new_docs"] == 2


def test_cancelled_crawl_stops_between_pages_and_keeps_what_it_found(library, monkeypatch):
    monkeypatch.setattr(crawler, "crawl_page", fake_crawl_page)

    def hook(phase, done, total, final, note=""):
        if done >= 1:
            raise progress.Cancelled()
    monkeypatch.setattr(progress, "hook", hook)
    with pytest.raises(progress.Cancelled):
        crawler.crawl()
    with db.session() as con:
        assert con.execute("SELECT COUNT(*) FROM documents WHERE title='New report'").fetchone()[0] == 1
        assert con.execute("SELECT last_status FROM pages WHERE id=1").fetchone()[0].startswith("ok (1 docs")


def test_download_progress_and_cancel(library, monkeypatch):
    monkeypatch.setattr(downloader, "download_one", lambda i: (time.sleep(0.01), "downloaded")[1])
    seen = []
    monkeypatch.setattr(progress, "hook", lambda phase, done, total, final, note="": seen.append((done, total)))
    assert downloader.download() == {"downloaded": 2}
    assert seen[-1] == (2, 2)
    assert downloader.download(retry_failed=True, source_ids=[1]) == {"downloaded": 1}       # BIS: the failed one
    monkeypatch.setattr(progress, "hook", lambda *a, **k: (_ for _ in ()).throw(progress.Cancelled()))
    with pytest.raises(progress.Cancelled):
        downloader.download()


def test_plan_and_run(library, monkeypatch):
    p = updater.plan("full", "all")
    assert p["pages"] == 4 and p["sources"] == 3 and p["manual"] == 1 and p["waiting"] == 2
    assert p["seconds"] == round(3 * updater.SECONDS_PER_PAGE + 2 * updater.SECONDS_PER_DOWNLOAD / 4)   # manual pages not counted
    assert updater.plan("check", "stale", stale_days=7)["pages"] == 3
    assert updater.plan("download", "sources", sources=[2])["waiting"] == 2
    monkeypatch.setattr(crawler, "crawl_page", fake_crawl_page)
    out = updater.run("check", "country", country="CZ")
    assert out["crawl"]["new_docs"] == 2 and "download" not in out and "CZ/BIS: 2 new" in out["text"]
    assert out["new_today"] == 2


def test_rows_and_page(library, monkeypatch):
    rows = {r["key"]: r for r in updater.sources_status()}
    assert rows["CZ/BIS"]["state"] == "ok" and rows["CZ/BIS"]["stale"] and rows["DE/BfV"]["state"] == "error"
    assert rows["SE/Sapo"]["state"] == "manual" and rows["DE/BfV"]["waiting"] == 2
    assert [r["key"] for r in updater.sources_status(state="stale")] == ["CZ/BIS"]
    from rozvedka import app as app_module
    app_module._age_cache.clear()
    client = TestClient(app_module.app)
    page = client.get("/update").text
    assert "check the agencies for new reports" in page and "Check now" in page and 'class="upd-btn' in page
    assert "20 d ago" in page                                                     # BIS: last checked 20 days ago
    assert client.get("/api/update/plan", params={"action": "check", "scope": "sources", "sources": "1"}).json()["pages"] == 2
    assert client.post("/api/update", data={"action": "check", "scope": "sources", "sources": ""}).status_code == 400
    monkeypatch.setattr(crawler, "crawl_page", fake_crawl_page)                     # no network in tests
    r = client.post("/jobs/crawl", data={"source_id": "1"}, follow_redirects=False)        # old buttons lead to the page
    assert r.status_code == 303 and r.headers["location"] == "/update"
    end = time.time() + 20
    while jobs.running() and time.time() < end:
        time.sleep(0.05)
    j = jobs.state()
    assert j["kind"] == "update" and j["status"] == "done" and j["result"]["crawl"]["pages"] == 2


from rozvedka.jobs import index_steps as REAL_INDEX_STEPS   # taken before conftest replaces it for every test


def test_index_steps_run_against_the_library_in_use(library, monkeypatch):
    lines = []
    monkeypatch.setattr(jobs.logging.getLogger("rozvedka.jobs"), "info", lambda fmt, *a: lines.append(fmt % a))
    assert REAL_INDEX_STEPS([("Counting", "stats")]) == {"stats": "ok"}
    out = "\n".join(lines)
    assert "CZ         2 found" in out and "DE         2 found" in out and "AR" not in out   # the temporary library, not the real one


def test_data_age_is_the_oldest_source_check(library):
    with db.session() as con:
        since = updater.all_checked_since(con)                 # BIS (20 days) – not BfV (yesterday), not Säpo (by hand)
        assert since == con.execute("SELECT MAX(last_crawled) FROM pages WHERE source_id=1").fetchone()[0]
    from rozvedka import app as app_module
    app_module._age_cache.clear()                                # the header caches the age for 30 s
    assert "20 d ago" in TestClient(app_module.app).get("/").text   # the header's Update button
