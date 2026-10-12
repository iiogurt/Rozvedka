"""Dated events of an actor: every fact has a date and a source."""
import json

import pytest
from fastapi.testclient import TestClient

from rozvedka import actor_events, actors, attributions, collect, db, sanctions, series, threat_levels, topics


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    f = tmp_path / "attributions.yaml"
    f.write_text("""attributions:
  - {date: 2025-05-21, by: NCSC, country: GB, kind: cyber, actors: [Q1], title: T1, url: "https://x/1", quote: q1, says: s1}
""", encoding="utf-8")
    monkeypatch.setattr(attributions, "FILE", f)
    monkeypatch.setattr(attributions, "CHECKS", tmp_path / "checks.json")
    attributions._checks.cache_clear()
    monkeypatch.setattr(sanctions, "of_actor", lambda key: [
        {"list": "EU", "ref": "EU.1", "entry": "Group X", "via": "name", "matched": "Group X", "programme": "Cyber", "date": "2020-10-22",
         "url": "https://eur-lex.example/1"}] if key == "Q1" else [])
    monkeypatch.setattr(threat_levels, "load", lambda: [
        {"kind": "announcement", "country": "GB", "as_of": "2026-05-01", "label": "severe", "change": "from substantial", "system": "UK national",
         "says": "Raised.", "agency": "MI5", "url": "https://mi5.example/", "quote": "raised"},
        {"kind": "report", "country": "GB", "as_of": "2025", "label": "x", "change": None, "system": "s", "says": "s", "agency": "a", "url": "u", "quote": "q"}])
    db.init()
    collect.init()
    topics.init()
    actors.init()
    data1 = {"inception": "2004", "dissolved": None, "wikidata": {"url": "https://wikidata.example/Q1"},
             "designations": [{"by": "Q30", "by_label": "United States", "start": "1997-10-08", "end": None}, {"by": "Q801", "by_label": "Israel", "start": None, "end": None}]}
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'CZ/X','CZ','X','cyber')")
        con.execute("INSERT INTO actors(key,kind,label,data,since_year) VALUES('Q1','cyber','Group X',?,2004)", (json.dumps(data1),))
        con.execute("INSERT INTO actors(key,kind,label,data,iso) VALUES('Q145','country','United Kingdom','{}','GB')")
        for i, y in ((1, 2010), (2, 2024)):
            con.execute("INSERT INTO documents(id,source_id,url,title,year,lang,status) VALUES(?,1,?,?,?,'en','downloaded')", (i, f"https://x/{i}.pdf", f"R{i}", y))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", "Group X"))
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages) VALUES(?,?,?,?)", (i, 7, "x", "[0]"))
            con.execute("INSERT INTO doc_actors(doc_id,actor_key,hits,spans,names) VALUES(?, 'Q1', 1, '[[0,7]]', '{}')", (i,))
    return tmp_path


def test_events_are_dated_sourced_and_sorted(library):
    ev = actor_events.of_actor("Q1")
    assert [(e["date"], e["kind"]) for e in ev] == [("1997-10-08", "designated"), ("2004", "founded"), ("2010", "first"),
                                                    ("2020-10-22", "listed"), ("2024", "last"), ("2025-05-21", "attributed")]
    assert all(e["source"] and e["source_url"] for e in ev)          # undated designations (Israel) are not listed
    assert ev[0]["source_url"] == "https://wikidata.example/Q1" and "United States" in ev[0]["title"]
    assert ev[3]["source_url"].startswith("https://eur-lex") and ev[5]["quote"] == "q1"
    uk = actor_events.of_actor("Q145")
    assert [(e["date"], e["kind"]) for e in uk] == [("2026-05-01", "threat-level")]       # only announcements, not report statements
    assert actor_events.of_actor("nope") == []


def test_page_shows_the_events(library):
    from rozvedka.app import app
    t = TestClient(app).get("/actors/Q1/timeline").text
    assert 'id="events"' in t and "Designated as terrorist by United States" in t and "1997-10-08" in t and "Listed on the" in t
