"""Trend statistics: shares, scope and that every count links back to exactly the documents it counts."""
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from rozvedka import db, topics, trends


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A tiny library: 2 agencies, 2023–2024, a few topic tags and full texts."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init()
    topics.init()
    h = topics.taxonomy()["hash"]
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil')")
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(2,'DE/BSI','DE','BSI','cyber')")
        docs = [  # id, source, year, hidden, text, topics
            (1, 1, 2023, 0, "Russian services and drones", ["russia"]),
            (2, 1, 2024, 0, "Russia again, drone sabotage", ["russia", "sabotage"]),
            (3, 2, 2024, 0, "Ransomware and drones", ["ransomware"]),
            (4, 2, 2024, 0, "Ransomware only", ["ransomware"]),
            (5, 2, 2024, 1, "Hidden Russia document", ["russia"]),     # hidden: never counted
            (6, 2, None, 0, "Undated Russia document", ["russia"]),    # undated: reported as excluded
        ]
        for i, s, y, hidden, text, tags in docs:
            con.execute("INSERT INTO documents(id,source_id,url,title,year,hidden,status) VALUES(?,?,?,?,?,?,'downloaded')",
                        (i, s, f"https://x/{i}.pdf", f"Doc {i}", y, hidden))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, f"Doc {i}", text))
            con.execute("INSERT INTO doc_index(doc_id,chars,words,taxonomy_hash) VALUES(?,?,?,?)", (i, len(text), 4, h))
            for t in tags:
                con.execute("INSERT INTO doc_topics(doc_id,topic,score) VALUES(?,?,1)", (i, t))
    return tmp_path


def test_topic_shares_per_year(library):
    d = trends.topic_trends(["russia", "ransomware", "no-such-topic"])
    assert d["years"] == [2023, 2024]
    assert d["denominator"]["docs"] == [1, 3]            # hidden and undated documents are not in scope
    russia, ransomware = d["series"]
    assert [s["key"] for s in d["series"]] == ["russia", "ransomware"]
    assert russia["docs"] == [1, 1] and russia["share_docs"] == [1.0, round(1 / 3, 4)]
    assert russia["share_agencies"] == [1.0, 0.5]         # 1 of 2 agencies publishing in 2024
    assert ransomware["docs"] == [0, 2]
    assert d["provenance"]["excluded"]["undated"] == 1


def test_links_reproduce_the_counted_documents(library):
    d = trends.topic_trends(["russia"], country="CZ")
    q = parse_qs(urlsplit(d["series"][0]["links"][1]).query)
    assert q == {"indexed": ["1"], "country": ["CZ"], "topic": ["russia"], "year": ["2024"]}


def test_term_trends_or_alternatives(library):
    d = trends.term_trends(["drone OR Drohne", "ransomware"])
    drones, ransom = d["series"]
    assert drones["docs"] == [1, 2] and ransom["docs"] == [0, 2]
    assert drones["fts"] == '("drone"*) OR ("Drohne"*)'


def test_or_query_is_safe():
    assert trends.or_query('drop OR "x"; --') == '("drop"*) OR ("x")'
    assert trends.or_query("  OR  ") == ""


def test_matrix_shares(library, monkeypatch):
    assert trends.matrix(2023, 2024, by="agency")["rows"] == []      # both agencies are below the 5-report minimum
    monkeypatch.setattr(trends, "MATRIX_MIN_DOCS", 1)
    m = trends.matrix(2023, 2024, by="agency")
    cells = {(c["row"], c["topic"]): c for c in m["cells"]}
    assert cells[(2, "ransomware")]["share"] == 1.0 and cells[(1, "russia")]["n"] == 2
    assert "year_from=2023" in cells[(1, "russia")]["link"] and "source=1" in cells[(1, "russia")]["link"]


def test_events_are_sourced():
    evs = trends.events()
    assert evs, "sources/events.yaml should list resolved events"
    for e in evs:
        assert re.fullmatch(r"Q\d+", e["wikidata"])
        assert e["wikipedia_url"].startswith("https://en.wikipedia.org/wiki/")
        assert e["wikidata_url"].startswith(f"https://www.wikidata.org/wiki/{e['wikidata']}#P")
        assert re.fullmatch(r"\d{4}(-\d\d){0,2}", e["date"]) and e["retrieved"]
