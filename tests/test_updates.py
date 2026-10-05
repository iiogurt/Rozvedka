"""What's new: updates by day, first-time actors, jumping topics, the Atom feed – each count equal to its list."""
import re
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, collect, db, series, topics, updates


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
        con.execute("INSERT INTO sources(id,key,country,agency,type,name_en,active) VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil','Security Information Service',1)")
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(2,'DE/BSI','DE','BSI','cyber',1)")
        docs = [  # id, source, day, topics, actors, hidden
            (1, 1, "2026-01-10", ["ransomware"], ["Q1"], 0), (2, 1, "2026-01-10", ["ransomware"], [], 0),
            (3, 2, "2026-01-10", ["terrorism"], [], 0), (4, 2, "2026-01-10", ["terrorism"], [], 0),
            (5, 1, "2026-02-20", ["drones-and-new-warfare"], ["Q1", "Q2"], 0), (6, 2, "2026-02-20", ["drones-and-new-warfare"], ["Q2"], 0),
            (7, 2, "2026-02-20", ["drones-and-new-warfare", "ransomware"], ["Q3"], 0), (8, 2, "2026-02-20", [], ["Q4"], 1)]
        for i, src, day, tags, names, hidden in docs:
            con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,hidden,discovered_at,local_path)
                           VALUES(?,?,?,?,'en',2025,'downloaded',?,?,?)""",
                        (i, src, f"https://x/{i}.pdf", f"Report & {i}", hidden, f"{day} 10:00:00", f"f{i}.pdf"))
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash) VALUES(?,?,?)", (i, 5000, h))
            for rank, t in enumerate(tags):
                con.execute("INSERT INTO doc_topics(doc_id,topic,score) VALUES(?,?,?)", (i, t, 10 - rank))
            for a in names:
                con.execute("INSERT INTO doc_actors(doc_id,actor_key,hits) VALUES(?,?,3)", (i, a))
        con.execute("""INSERT INTO actors(key,kind,label) VALUES('Q1','cyber','Fancy Bear'),('Q2','armed','Wagner Group'),
                       ('Q3','country','Russia'),('Q4','cyber','Hidden Group')""")
    return tmp_path


def test_update_by_day(library):
    u = updates.update()
    assert [d["day"] for d in u["days"]] == ["2026-02-20", "2026-01-10"] and u["day"] == "2026-02-20"
    assert u["n"] == 3 and u["n_before"] == 4 and u["prev"] == "2026-01-10"         # hidden report 8 left out
    assert [a["label"] for a in u["first"]] == ["Wagner Group"]       # Fancy Bear was named before; Russia is a country
    assert u["first"][0]["n"] == 2
    jump = {j["key"]: j for j in u["jumps"]}
    assert set(jump) == {"drones-and-new-warfare"} and jump["drones-and-new-warfare"]["pp"] == 100.0    # 3 of 3 now, 0 of 4 before
    assert [g["agency"] for g in u["agencies"]] == ["BIS", "BSI"]
    d5 = next(d for g in u["agencies"] for d in g["docs"] if d["id"] == 5)
    assert d5["topics"] == ["drones-and-new-warfare"] and [a["label"] for a in d5["actors"]] == ["Fancy Bear", "Wagner Group"]
    first = updates.update("2026-01-10")
    assert first["prev"] is None and first["jumps"] == [] and [a["label"] for a in first["first"]] == ["Fancy Bear"]


def test_every_count_matches_its_list(library):
    from rozvedka.app import app
    client = TestClient(app)
    for day in ("2026-02-20", "2026-01-10"):
        figs = updates.figures(updates.update(day))
        assert len(figs) >= 4
        for label, n, url in figs:
            r = client.get(url)
            assert int(re.search(r"<b>(\d+)</b> documents match", r.text).group(1)) == n, (label, url)
    r = client.get("/new?day=2026-02-20")
    assert r.status_code == 200 and "Named for the first time" in r.text and "Wagner Group" in r.text
    assert client.get("/new?day=nonsense").status_code == 200                       # unknown day → latest update


def test_atom_feed(library):
    from rozvedka.app import app
    r = TestClient(app).get("/feed.atom")
    assert r.headers["content-type"].startswith("application/atom+xml")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    feed = ET.fromstring(r.content)                                                  # well-formed, escaped
    entries = feed.findall("a:entry", ns)
    assert len(entries) == 7 and entries[0].find("a:title", ns).text.startswith("BSI: Report & ")
    assert entries[0].find("a:id", ns).text.startswith("tag:rozvedka,2026:doc/")     # same id from any address
    summary = next(e for e in entries if e.find("a:id", ns).text.endswith("/5")).find("a:summary", ns).text
    assert "Fancy Bear" in summary and "Official source: https://x/5.pdf" in summary
