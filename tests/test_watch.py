"""Watchlist: one shared list of search-console queries, counted update by update – every count equal to its list."""
import re
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, collect, db, series, topics, watch


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(watch, "WATCHLIST", tmp_path / "watchlist.yaml")
    db.init()
    collect.init()
    actors.init()
    h = topics.taxonomy()["hash"]
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil',1)")
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(2,'DE/BfV','DE','BfV','intelligence-civil',1)")
        for i, src, day, text in [(1, 1, "2026-01-10", "Wagner fighters in Africa."), (2, 2, "2026-01-10", "Ransomware and Wagner."),
                                  (3, 2, "2026-02-20", "Wagner recruits online; critical infrastructure at risk."),
                                  (4, 1, "2026-02-20", "Nothing relevant."), (5, 2, "2026-03-05", "critical infrastructure again")]:
            con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,discovered_at,local_path)
                           VALUES(?,?,?,?,'en',2025,'downloaded',?,?)""", (i, src, f"https://x/{i}.pdf", f"Report {i}", f"{day} 09:00:00", f"f{i}.pdf"))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", text))
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages) VALUES(?,?,?,'[0]')", (i, len(text), h))
            if "Wagner" in text:
                s = text.index("Wagner")
                con.execute("INSERT INTO doc_actors(doc_id,actor_key,hits,spans,names) VALUES(?,'Q1',1,?,'[]')", (i, f"[[{s},{s + 6}]]"))
        con.execute("INSERT INTO actors(key,kind,label) VALUES('Q1','armed','Wagner Group')")
        con.execute("INSERT INTO actor_names(actor_key,name,status) VALUES('Q1','Wagner Group','used')")
    return tmp_path


def test_add_remove_and_yaml(library):
    assert watch.add('actor:"Wagner Group"') == {"added": 'actor:"Wagner Group"'}
    assert "exists" in watch.add('actor:"Wagner  Group"'.replace("  ", " "))
    assert "error" in watch.add("actor:Nobody") and "error" in watch.add("  ")
    watch.add('"critical infrastructure" country:DE')
    text = (library / "watchlist.yaml").read_text(encoding="utf-8")
    assert text.startswith("# Watchlist") and [i["query"] for i in watch.load()] == ['actor:"Wagner Group"', '"critical infrastructure" country:DE']
    watch.remove('actor:"Wagner Group"')
    assert [i["query"] for i in watch.load()] == ['"critical infrastructure" country:DE']


def test_to_query(library):
    assert watch.to_query({"actor": "Q1", "source": 2, "year_from": "2020", "year_to": "", "q": "drones"}) == \
        'country:DE agency:BfV actor:"Wagner Group" year:2020..' + str(__import__("datetime").date.today().year) + " drones"
    assert watch.to_query({"topic": ["ransomware"], "coalition": "NATO"}) == "coalition:NATO topic:Ransomware & extortion".replace(
        "topic:Ransomware & extortion", 'topic:"' + topics.taxonomy()["topics"]["ransomware"]["name"] + '"')
    assert watch.to_query({"cluster": "Q1,Q2"}) is None and watch.to_query({}) is None


def test_overview_counts_match_lists(library):
    from rozvedka.app import app
    watch.add('actor:"Wagner Group"')
    watch.add('"critical infrastructure"')
    o = watch.overview()
    w, ci = o["entries"]
    assert o["columns"] == ["2026-03-05", "2026-02-20", "2026-01-10"]
    assert w["total"] == 3 and [c["n"] for c in w["cells"]] == [0, 1, 2] and w["last_day"] == "2026-02-20"
    assert ci["total"] == 2 and [c["n"] for c in ci["cells"]] == [1, 1, 0]
    assert [[h["query"] for h in t["hits"]] for t in o["timeline"]] == [['"critical infrastructure"'],
                                                                        ['actor:"Wagner Group"', '"critical infrastructure"'],
                                                                        ['actor:"Wagner Group"']]
    client = TestClient(app)
    for label, n, url in watch.figures(o):
        assert int(re.search(r"<b>(\d+)</b> documents match", client.get(url).text).group(1)) == n, (label, url)
    latest = watch.latest('actor:"Wagner Group"')
    assert [p["id"] for p in latest] == [3, 2, 1] and [s["text"] for s in latest[0]["segments"] if s["mark"]] == ["Wagner"]
    ci_latest = watch.latest('"critical infrastructure"')
    assert [s["text"] for s in ci_latest[0]["segments"] if s["mark"]] == ["critical infrastructure"]


def test_pages_and_feed(library):
    from rozvedka.app import app
    client = TestClient(app)
    r = client.post("/watch/add", data={"query": 'actor:"Wagner Group"'}, follow_redirects=False)
    assert r.status_code == 303 and "Now+watching" in r.headers["location"]
    page = client.get("/watch").text
    assert "Reports per update" in page and "actor:&#34;Wagner Group&#34;" in page
    feed = ET.fromstring(client.get("/feed.atom", params={"watch": 'actor:"Wagner Group"'}).content)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    assert len(feed.findall("a:entry", ns)) == 3 and "watchlist" in feed.find("a:title", ns).text
    docs = client.get("/documents", params={"actor": "Q1"}).text
    assert "Watch this search" in docs and 'value="actor:&#34;Wagner Group&#34;"' in docs
    client.post("/watch/remove", data={"query": 'actor:"Wagner Group"'})
    assert watch.load() == []
