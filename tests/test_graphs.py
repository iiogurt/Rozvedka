"""Network, geography and topic tree: counts, exclusions and links back to the documents."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from rozvedka import actors, db, graphs, topics


def test_pairs_within_window():
    spans = {"A": [[0, 5], [5000, 5005]], "B": [[100, 105]], "C": [[900, 905]]}
    assert actors.pairs_in(spans) == {("A", "B"): 1}            # C is more than WINDOW characters from A and B


def entry(key, kind, label, names, iso=None):
    return {"key": key, "qid": key, "kind": kind, "label": label, "description": "", "iso": iso,
            "reasons": [{"via": "class", "kind": kind, "text": ""}],
            "names": [{"name": n, "lang": "en", "origin": "Wikidata label"} for n in names]}


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    g = tmp_path / "actors.json"
    g.write_text(json.dumps({"retrieved": "2026-10-01", "actors": [
        entry("Q5", "armed", "Wagner Group", ["Wagner Group"]),
        entry("Q9", "cyber", "Sandworm", ["Sandworm"]),
        entry("Q159", "country", "Russia", ["Russia", "Russian"], "RU"),
        entry("Q213", "country", "Czech Republic", ["Czech Republic", "Czechia"], "CZ")]}))
    c = tmp_path / "actors.yaml"
    c.write_text("{}")
    monkeypatch.setattr(actors, "GAZETTEER", g)
    monkeypatch.setattr(actors, "CONFIG", c)
    db.init()
    actors.init()
    h = topics.taxonomy()["hash"]
    docs = {  # id: (source, year, text, topics)
        1: (1, 2024, "The Wagner Group and Sandworm serve Russia.", ["russia"]),
        2: (1, 2024, "Czechia and the Czech Republic. Sandworm.", ["ransomware"]),
        3: (2, 2024, "Russian services. Wagner Group." + " x" * 400 + " Sandworm far away.", ["russia"]),
        4: (2, 2023, "Nothing relevant.", []),
    }
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil')")
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(2,'DE/BfV','DE','BfV','intelligence-civil')")
        for i, (src, y, text, tags) in docs.items():
            con.execute("INSERT INTO documents(id,source_id,url,year,status) VALUES(?,?,?,?,'downloaded')", (i, src, f"u{i}", y))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", text))
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages) VALUES(?,?,?,?)", (i, len(text), h, "[0]"))
            for t in tags:
                con.execute("INSERT INTO doc_topics(doc_id,topic,score) VALUES(?,?,1)", (i, t))
    actors.index(workers=1)
    return tmp_path


def test_network_nodes_links_and_their_links(library):
    n = graphs.network(min_link=1)
    nodes = {x["key"]: x["docs"] for x in n["nodes"]}
    assert nodes == {"Q5": 2, "Q9": 3}                            # countries are left out by default
    links = {(x["a"], x["b"]): x for x in n["links"]}
    assert links[("Q5", "Q9")]["docs"] == 1                       # doc 3: too far apart to count
    assert links[("Q5", "Q9")]["link"] == "/actors/Q5/with/Q9"
    with_countries = {x["key"] for x in graphs.network(min_link=1, include_countries=True)["nodes"]}
    assert "Q159" in with_countries


def test_pair_detail_passages(library):
    d = actors.pair_detail("Q9", "Q5")
    assert d["docs"] == 1 and d["passages"][0]["doc_id"] == 1
    assert {d["passages"][0]["first"], d["passages"][0]["second"]} == {"Wagner Group", "Sandworm"}


def test_geography_about_and_from(library):
    about = graphs.geography("about", "Q159")
    rows = {r["iso"]: r for r in about["rows"]}
    assert rows["CZ"]["docs"] == 1 and rows["CZ"]["of"] == 2      # docs 1 and 2 are Czech
    assert rows["DE"]["docs"] == 1 and rows["DE"]["share"] == 0.5
    q = parse_qs(urlsplit(rows["DE"]["link"]).query)
    assert q == {"indexed": ["1"], "country": ["DE"], "actor": ["Q159"]}
    own = graphs.geography("about", "Q213")
    assert "CZ" not in {r["iso"] for r in own["rows"]}            # a country's own reports are left out
    frm = {r["iso"]: r["docs"] for r in graphs.geography("from", "CZ")["rows"]}
    assert frm == {"RU": 1}                                       # Czech reports naming Czechia are left out


def test_topic_tree(library):
    t = graphs.topic_tree(per_topic=3, min_reports=1)
    topic = {k["key"]: k for c in t["tree"]["children"] for k in c["children"]}
    assert topic["russia"]["value"] == 2
    kids = {a["key"]: a for a in topic["russia"]["children"]}
    assert kids["Q5"]["value"] == 2 and kids["Q5"]["share"] == 1.0     # both of Wagner's reports are on Russia
    assert kids["Q9"]["value"] == 2 and kids["Q9"]["of"] == 3           # Sandworm: 2 of its 3 reports
    assert list(kids) == ["Q5", "Q9"]                                   # 2×1.0 before 2×0.67
    assert parse_qs(urlsplit(kids["Q5"]["link"]).query) == {"indexed": ["1"], "topic": ["russia"], "actor": ["Q5"],
                                                           "main": ["1"]}
