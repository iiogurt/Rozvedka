"""Threat levels with their passages: quotes are checked against the library or the official page."""
import json

import pytest
from fastapi.testclient import TestClient

from rozvedka import db, threat_levels as tl


def test_scale_and_offsets():
    assert tl.scale_max("1–5") == 5 and tl.scale_max("1-4") == 4 and tl.scale_max("1–5 (low, moderate)") == 5
    assert tl.scale_max("qualitative") is None
    text = "Line one.\n\nThe  level “remains”  at 4 –  on a scale."
    norm, mapping = tl._normalised_with_map(text)
    assert norm == "line one. the level \"remains\" at 4 - on a scale."
    pos = norm.find("remains")
    assert text[mapping[pos]:mapping[pos] + 7] == "remains"


def test_the_curated_file_is_well_formed():
    rows = tl.load()
    assert len(rows) >= 20
    for e in rows:
        assert e["kind"] in ("report", "announcement") and e["quote"].strip() and e["says"].strip() and len(e["country"]) == 2
        assert str(e["as_of"])[:4].isdigit() and e["url"].startswith("https://") and e["agency"]
        if e["rank"] is not None:
            assert 1 <= e["rank"] <= tl.scale_max(e["scale"]), e
        if e["kind"] == "announcement":
            assert len(str(e["as_of"])) == 10 and e["change"]
    assert {e["country"] for e in rows} >= {"GB", "NL", "BE", "SE"}


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(tl, "CHECKS", tmp_path / "checks.json")
    tl._checks.cache_clear()
    f = tmp_path / "threat_levels.yaml"
    f.write_text('''threat_levels:
  - {country: BE, system: General level, scale: "1–4", rank: 3, label: serious, as_of: "2025", kind: report,
     url: "https://x/r.pdf", agency: OCAM, quote: "the general threat level was set at level 3", says: "Level 3 in 2025."}
  - {country: BE, system: General level, scale: "1–4", rank: 2, label: medium, as_of: "2019", kind: report,
     url: "https://x/missing.pdf", agency: OCAM, quote: "never said", says: "Level 2."}
  - {country: GB, system: National, scale: "1–5", rank: 4, label: severe, as_of: "2026-05-01", kind: announcement, change: from substantial,
     url: "https://x/page", agency: MI5, quote: "raised the level", says: "Raised."}
''', encoding="utf-8")
    monkeypatch.setattr(tl, "FILE", f)
    db.init()
    from rozvedka import collect, series
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    collect.init()
    from rozvedka import topics
    topics.init()
    body = "Page one text. In 2025, the  general threat level was set at level 3 (serious)."
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'BE/OCAM','BE','OCAM','intelligence-civil')")
        con.execute("INSERT INTO documents(id,source_id,url,title,year,lang,status) VALUES(1,1,'https://x/r.pdf','Annual 2025',2025,'en','downloaded')")
        con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(1,'',?)", (body,))
        con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages) VALUES(1,?,?,?)", (len(body), "x", json.dumps([0, 20])))
    tl._located.cache_clear()
    return tmp_path


def test_reports_are_checked_against_the_library(library):
    loc = tl._located()
    assert loc["https://x/r.pdf"]["found"] and loc["https://x/r.pdf"]["page"] == 2      # the quote is on the second page
    assert loc["https://x/r.pdf"]["open"] == "https://x/r.pdf"      # no downloaded file in the test: the official address
    assert loc["https://x/missing.pdf"]["found"] is False


def test_overview_and_page(library):
    (library / "checks.json").write_text(json.dumps({"https://x/page#2026-05-01#National": {"ok": True, "checked": "2026-10-12"}}))
    tl._checks.cache_clear()
    o = tl.overview()
    assert (o["n"], o["confirmed"]) == (3, 2)
    be = next(c for c in o["countries"] if c["country"] == "BE")["systems"][0]
    assert be["latest"]["as_of"] == "2025" and [e["evidence"]["confirmed"] for e in be["entries"]] == [True, False]
    from rozvedka.app import app
    t = TestClient(app).get("/threat-levels").text
    assert "level 3" in t and "quote not found" in t and "quote confirmed on the page, checked 2026-10-12" in t
    assert "3/4" in t and "4/5" in t


def test_small_multiples_place_marks_on_a_shared_axis():
    import datetime as dt
    from rozvedka import threat_levels
    assert threat_levels.when("2024") == 2024.5 and round(threat_levels.when("2023-10-17"), 2) == 2023.79
    entries = [{"as_of": "2017-05-23", "rank": 5, "label": "critical", "kind": "announcement"},
               {"as_of": "2014-08-29", "rank": 4, "label": "severe", "kind": "announcement"},
               {"as_of": "2024", "rank": 3, "label": "substantial", "kind": "report"}]
    countries = [{"country": "GB", "systems": [{"system": "x", "max": 5, "entries": entries}]}]
    axis = threat_levels.charts(countries, today=dt.date(2026, 1, 1))
    s = countries[0]["systems"][0]
    assert axis["y0"] == 2014 and axis["y1"] == 2027
    assert [m["y"] for m in s["marks"]] == [0, 25, 50] and all(0 <= m["x"] <= 100 for m in s["marks"])
    assert s["path"].count("M") == 1 and s["path"].count("L") == 3      # two announced changes: steps; the report is only a dot
    assert [st["rank"] for st in s["steps"]] == [5, 4, 3, 2, 1]
