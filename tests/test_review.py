"""Precision review: verdicts kept with their passage, "wrong" applied at once and on every rebuild; names whose
symbol is part of the name are not matched as a bare word."""
import json

import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, collect, db, review, series


def test_symbol_names_are_not_matched_as_bare_words():
    gaz = {"actors": [{"key": "Q1", "kind": "armed", "label": "Three Percenters", "reasons": [{"via": "class"}],
                       "names": [{"name": n, "lang": "en", "origin": "Wikidata alias"}
                                 for n in ("III %", "Three Percenters", "III Percenters")]},
                      {"key": "Q2", "kind": "party", "label": "Die Heimat", "reasons": [{"via": "seed"}],
                       "names": [{"name": "Heimat!", "lang": "de", "origin": "Wikidata alias"}]}]}
    rows = {r["name"]: r for r in actors.prepare_names(gaz, {})}
    assert rows["III %"]["status"] == "ignored" and "numeral III" in rows["III %"]["reason"]
    assert rows["Heimat!"]["status"] == "ignored" and "“!”" in rows["Heimat!"]["reason"]
    assert rows["Three Percenters"]["status"] == rows["III Percenters"]["status"] == "used"   # several words: kept


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(review, "REVIEWS", tmp_path / "actor_reviews.yaml")
    db.init()
    collect.init()
    actors.init()
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(1,'BR/ABIN','BR','ABIN','intelligence-civil',1)")
        texts = {1: "Wagner fighters in Mali.", 2: "Diretor Wagner Silva de Araújo assinou.", 3: "Wagner again in Libya."}
        for i, t in texts.items():
            con.execute("INSERT INTO documents(id,source_id,url,title,lang,year,status) VALUES(?,1,?,?,'pt',2025,'downloaded')",
                        (i, f"https://abin/{i}.pdf", f"R{i}"))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", t))
            s = t.index("Wagner")
            con.execute("INSERT INTO actor_hits(doc_id,name_id,n,spans) VALUES(?,1,1,?)", (i, json.dumps([[s, s + 6]])))
        con.execute("INSERT INTO actors(key,kind,label) VALUES('Q36597284','armed','Wagner Group')")
        con.execute("""INSERT INTO actor_names(id,actor_key,name,tokens,status,origins) VALUES
                       (1,'Q36597284','Wagner','["Wagner"]','used','["added by hand in sources/actors.yaml"]')""")
        actors.derive(con, {})
    return tmp_path


def test_queue_and_verdicts(library):
    q = review.queue()
    assert [n["name"] for n in q["names"]] == ["Wagner"] and q["names"][0]["docs"] == 3
    assert len(q["names"][0]["samples"]) == 3 and q["names"][0]["samples"] == review.queue()["names"][0]["samples"]  # stable
    assert review.record("Q36597284", 2, "wrong", "Wagner", "Diretor Wagner Silva de Araújo") == {"recorded": "wrong"}
    review.record("Q36597284", 1, "right", "Wagner", "Wagner fighters in Mali.")
    with db.session() as con:                                               # applied at once …
        assert [r[0] for r in con.execute("SELECT doc_id FROM doc_actors ORDER BY doc_id")] == [1, 3]
        actors.derive(con, {})                                              # … and by every rebuild
        assert [r[0] for r in con.execute("SELECT doc_id FROM doc_actors ORDER BY doc_id")] == [1, 3]
    rows = review.load()
    assert {(r["url"], r["verdict"]) for r in rows} == {("https://abin/2.pdf", "wrong"), ("https://abin/1.pdf", "right")}
    assert (library / "actor_reviews.yaml").read_text(encoding="utf-8").startswith("# Actor match reviews")
    q = review.queue()
    assert q["right"] == 1 and q["wrong"] == 1 and [s["doc_id"] for s in q["names"][0]["samples"]] == [3]  # reviewed ones gone
    assert q["done"][0]["checked"] == 2
    review.record("Q36597284", 2, "right", "Wagner", "changed my mind")     # a later verdict replaces the earlier one
    assert len(review.load()) == 2 and review.of_actor("Q36597284") == []
    assert "error" in review.record("Q36597284", 2, "maybe") and "error" in review.record("Qnope", 2, "wrong")


def test_pages(library):
    from rozvedka.app import app
    client = TestClient(app)
    assert "Review actor matches" in client.get("/actors/review").text
    r = client.post("/actors/review", data={"actor": "Q36597284", "doc_id": 2, "verdict": "wrong", "name": "Wagner",
                                            "says": "Wagner Silva", "back": "https://evil.example/"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/actors/review"        # no redirect off the portal
    out = review.of_actor("Q36597284")                                   # what the actor page lists as not counted
    assert [(r["url"], r["says"]) for r in out] == [("https://abin/2.pdf", "Wagner Silva")]


def test_measured_precision_on_the_actors_page(library):
    from rozvedka.app import app
    assert review.summary()["passages"] == 0
    assert "Measured precision" not in TestClient(app).get("/actors?min_docs=1").text     # nothing reviewed: no figure
    review.record("Q36597284", 1, "right", "Wagner", "Wagner fighters in Mali.")
    review.record("Q36597284", 3, "right", "Wagner", "Wagner again in Libya.")
    review.record("Q36597284", 2, "wrong", "Wagner", "Diretor Wagner Silva")
    s = review.summary()
    assert (s["passages"], s["right"], s["wrong"], s["precision"]) == (3, 2, 1, 66.7)
    assert (s["names_reviewed"], s["names_covered"], s["names_in_use"], s["links"], s["share"]) == (1, 1, 1, 2, 100.0)
    html = TestClient(app).get("/actors?min_docs=1").text
    assert "Measured precision" in html and "<b>66.7 %</b>" in html and 'href="/actors/review#reviewed"' in html
    assert "Only reviewed names are measured" in html
    # the reviewed list keeps a name that no longer counts, so its verdicts still add up to the totals
    review.record("Q36597284", 1, "wrong", "Wagner", "x")
    review.record("Q36597284", 3, "wrong", "Wagner", "x")
    done = review.queue()["done"]
    assert [(n["name"], n["right"], n["wrong"], n["docs"]) for n in done] == [("Wagner", 0, 3, 0)] and done[0]["gone"]
    assert 'id="reviewed"' in TestClient(app).get("/actors/review").text


def test_several_verdicts_at_once(library):
    r = review.record_many([("Q36597284", 1, "right", "Wagner", "Wagner fighters in Mali."),
                            ("Q36597284", 2, "wrong", "Wagner", "Diretor Wagner Silva de Araújo")], reviewer="Claude")
    assert r == {"recorded": 2}
    rows = review.load()
    assert {(x["url"], x["verdict"], x.get("reviewer")) for x in rows} == {("https://abin/1.pdf", "right", "Claude"), ("https://abin/2.pdf", "wrong", "Claude")}
    assert ("Q36597284", "https://abin/2.pdf") in review.wrong_pairs()
    assert "error" in review.record_many([("Q36597284", 1, "maybe", "Wagner", "x")])
    assert len(review.load()) == 2          # nothing is written when one verdict is invalid
