"""Compare agencies: ranking per agency, the densest passage (not a reference list), exact positions, counts = lists."""
import datetime as dt
import json
import re

import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, collect, compare, db, series, topics

NOW = dt.date.today().year
PROSE = "Ransomware gangs extorted hospitals; the ransomware affiliates also leaked data and used ransomware builders. "


def test_densest_skips_reference_lists():
    refs = "See https://x.org ransomware report, accessed 2024; ransomware 2021, 2022, 2023, 2019 ransomware ransomware."
    body = refs + " filler " * 200 + PROSE
    spans = [(m.start(), m.end()) for m in re.finditer("(?i)ransomware", body)]
    s, e, inside = compare._densest(spans, body)
    assert s > len(refs) and len(inside) == 3                    # the prose, though the reference list has more
    assert compare._densest(spans)[0] < len(refs)                # without the text: simply the densest
    assert compare.looks_like_references(refs) and not compare.looks_like_references(PROSE)


def test_passage_segments():
    body = "a " * 200 + "Wagner fighters and Wagner commanders" + " b" * 200
    s = body.index("Wagner")
    segs = compare._passage(body, [(s, s + 6), (s + 20, s + 26)])
    assert segs[0]["text"] == "…" and segs[-1]["text"] == "…"
    assert [x["text"] for x in segs if x["mark"]] == ["Wagner", "Wagner"]


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    db.init()
    collect.init()
    actors.init()
    h = topics.taxonomy()["hash"]
    with db.session() as con:
        for sid, cc, agency in ((1, "CZ", "BIS"), (2, "DE", "BSI"), (3, "EE", "Ransomware")):   # 3: named like the term
            con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(?,?,?,?,'cyber',1)",
                        (sid, f"{cc}/{agency}", cc, agency))
        docs = [(1, 1, NOW - 1, 9), (2, 1, NOW - 2, 5), (3, 2, NOW - 1, 7), (4, 1, NOW - 10, 9),   # 4: out of range
                (5, 2, NOW, 1), (6, 3, NOW - 1, 3)]
        for i, src, year, score in docs:
            body = "Intro. " * 50 + "Straße " + PROSE * 2 + "Ransomware. " + "End. " * 50
            con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,local_path)
                           VALUES(?,?,?,?,'en',?,'downloaded',?)""", (i, src, f"https://x/{i}.pdf", f"Report {i}", year, f"f{i}.pdf"))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", body))
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages) VALUES(?,?,?,?)", (i, len(body), h, json.dumps([0, 200])))
            if i != 5:
                con.execute("INSERT INTO doc_topics(doc_id,topic,score,terms) VALUES(?,'ransomware',?,?)",
                            (i, score, json.dumps(["ransomware"])))
            w = body.index("Ransomware gangs")
            con.execute("INSERT INTO doc_actors(doc_id,actor_key,hits,spans,names) VALUES(?,'Q1',2,?,'[]')",
                        (i, json.dumps([[w, w + 10], [w + 40, w + 50]])))
        con.execute("INSERT INTO actors(key,kind,label) VALUES('Q1','cyber','LockBit')")
    return tmp_path


def test_fts_spans_are_positions_in_the_original_text(library):
    with db.session() as con:
        body = con.execute("SELECT body FROM doc_text WHERE rowid=1").fetchone()[0]
        spans = compare.fts_spans(con, 1, ["ransomware"])
    assert len(spans) == 7 and all(body[s:e].lower() == "ransomware" for s, e in spans)   # after "Straße"


def test_compare_topic(library):
    c = compare.compare(topic="ransomware", year_from=NOW - 3, year_to=NOW)
    assert [a["agency"] for a in c["agencies"]] == ["BIS", "BSI", "Ransomware"] and c["total"] == 4
    bis = c["agencies"][0]
    assert bis["n"] == 2 and bis["of"] == 2 and [p["id"] for p in bis["passages"]] == [1, 2]     # highest score first
    p = bis["passages"][0]
    assert p["page"] == 2 and p["mentions"] == 7 and [s["text"] for s in p["segments"] if s["mark"]][0] == "Ransomware"
    own = c["agencies"][2]["passages"][0]
    assert own["mentions"] == 0 and "segments" not in own        # the agency's own name does not count


def test_compare_counts_match_lists(library):
    from rozvedka.app import app
    client = TestClient(app)
    for kw in ({"topic": "ransomware"}, {"actor": "Q1"}):
        c = compare.compare(**kw, year_from=NOW - 3, year_to=NOW)
        for label, n, url in compare.figures(c):
            r = client.get(url)
            assert int(re.search(r"<b>(\d+)</b> documents match", r.text).group(1)) == n, (label, url)
    assert compare.compare(actor="Q1", year_from=NOW - 3, year_to=NOW)["total"] == 5
    r = client.get("/compare", params={"q": "LockBit", "year_from": NOW - 3})
    assert r.status_code == 200 and "Compare agencies on" in r.text and "LockBit" in r.text
    assert "No topic or actor" in client.get("/compare", params={"q": "nobody at all"}).text
