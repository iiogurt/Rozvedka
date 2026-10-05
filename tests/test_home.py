"""Home page: the search console's operators and suggestions, and that every dashboard count matches its list."""
import datetime as dt
import re

import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, collect, db, home, series, topics

NOW = dt.date.today().year


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
        for sid, key, cc, agency, typ in ((1, "CZ/BIS", "CZ", "BIS", "intelligence-civil"), (2, "DE/BSI", "DE", "BSI", "cyber"),
                                          (3, "SK/BIS", "SK", "BIS", "cyber"), (4, "NATO/HQ", "NATO", "NATO HQ", "nato")):
            con.execute("INSERT INTO sources(id,key,country,agency,type,name_en,active) VALUES(?,?,?,?,?,?,1)",
                        (sid, key, cc, agency, typ, f"{agency} agency"))
        today = dt.datetime.now()
        docs = [  # id, source, year, status, lang, added days ago, hidden, title
            (1, 1, NOW - 1, "downloaded", "cs", 2, 0, "Výroční zpráva"), (2, 1, NOW - 2, "downloaded", "en", 40, 0, "Annual report"),
            (3, 2, NOW - 1, "downloaded", "de", 3, 0, "Die Lage der IT-Sicherheit"), (4, 2, NOW - 4, "new", "de", 100, 0, "Lagebericht"),
            (5, 3, None, "failed", "sk", 10, 0, "Správa"), (6, 4, NOW, "browser-only", "en", 1, 0, "NATO annual report"),
            (7, 1, NOW - 20, "downloaded", "cs", 200, 0, "Old report"), (8, 1, NOW - 1, "downloaded", "cs", 1, 1, "Hidden"),
            (9, 2, NOW - 3, "duplicate", "de", 1, 0, "Copy"), (10, 2, NOW - 4, "downloaded", "en", 5, 0, "Ransomware report")]
        for i, src, year, status, lang, ago, hidden, title in docs:
            con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,hidden,discovered_at)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (i, src, f"https://x/{i}.pdf", title, lang, year, status, hidden,
                         (today - dt.timedelta(days=ago)).strftime("%Y-%m-%d %H:%M:%S")))
        for i, tags in {1: ["ransomware"], 2: ["ransomware", "drones"], 3: ["ransomware"], 10: ["drones"], 4: []}.items():
            con.execute("INSERT INTO doc_index(doc_id,chars,words,taxonomy_hash) VALUES(?,?,?,?)", (i, 1000, 150, h))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", "Kritische Infrastruktur und Drohnen"))
            for t in tags:
                con.execute("INSERT INTO doc_topics(doc_id,topic,score) VALUES(?,?,1)", (i, t))
        con.execute("INSERT INTO actors(key,kind,label) VALUES('Q1','cyber','Fancy Bear'),('Q2','country','Russia')")
        con.execute("INSERT INTO actor_names(actor_key,name,status) VALUES('Q1','Fancy Bear','used'),('Q1','APT28','used'),"
                    "('Q2','Russia','used')")
        for doc in (1, 3, 8):
            con.execute("INSERT INTO doc_actors(doc_id,actor_key,hits) VALUES(?,'Q1',2),(?,'Q2',5)", (doc, doc))
    return tmp_path


def total(client, url):
    r = client.get(url)
    assert r.status_code == 200, url
    return int(re.search(r"<b>(\d+)</b> documents match", r.text).group(1))


def test_parse_operators(library):
    p = home.parse('"critical infrastructure" country:Germany type:cyber actor:APT28 year:2020..2018 topic:ransomware lang:DE')
    assert p["problems"] == []
    assert p["params"] == {"q": '"critical infrastructure"', "country": "DE", "type": "cyber", "actor": "Q1",
                           "year_from": 2018, "year_to": 2020, "topic": ["ransomware"], "lang": "de"}
    assert home.parse("agency:BSI")["params"]["source"] == 2
    assert home.parse("country:SK agency:bis")["params"]["source"] == 3          # country narrows an ambiguous name


def test_parse_problems_offer_choices(library):
    p = home.parse("agency:BIS year:last topic:nonsense-topic actor:Nobody")
    msgs = {x["token"]: x for x in p["problems"]}
    assert "2 agencies" in msgs["agency:BIS"]["message"]
    assert [q for _, q in msgs["agency:BIS"]["options"]] == ["country:CZ agency:BIS", "country:SK agency:BIS"]
    assert {"year:last", "topic:nonsense-topic", "actor:Nobody"} <= set(msgs)


def test_suggest_counts_match_their_lists(library):
    client = TestClient(app())
    s = home.suggest("ransom")
    topic = next(g for g in s["groups"] if g["name"] == "Topics")["items"][0]
    assert topic["label"] and topic["n"] == total(client, topic["url"]) == 3
    s = home.suggest("apt2")
    actor = next(g for g in s["groups"] if g["name"] == "Actors")["items"][0]
    assert actor["label"] == "Fancy Bear" and actor["n"] == total(client, actor["url"]) == 2   # hidden report 8 not counted
    assert "APT28" in actor["sub"]
    assert not any(g["name"] == "Actors" and any(i["label"] == "Russia" for i in g["items"])
                   for g in home.suggest("russ")["groups"])                                    # countries are not actors here
    s = home.suggest("country:DE actor:fan")                                                   # completing an operator
    assert s["op"] == "actor" and s["prefix"] == "country:DE"
    it = s["groups"][0]["items"][0]
    assert it["n"] is None and it["url"] == "/search?q=country%3ADE+actor%3A%22Fancy+Bear%22"
    assert [i["label"] for i in home.suggest("type:")["groups"][0]["items"]][:1] == ["Civil intelligence"]


def test_every_dashboard_count_matches_its_list(library):
    client = TestClient(app())
    d = home.dashboard()
    figs = home.figures(d)
    assert len(figs) > 20
    for label, n, url in figs:
        assert total(client, url) == n, (label, url)
    years = sum(y["n"] for y in d["years"]) + d["older"]["n"] + d["undated"]["n"] + d["later"]
    assert years == d["totals"]["reports"]["n"] == 8           # every listed report is in exactly one row
    assert [a["n"] for a in d["added"]] == [4, 5, 6]
    assert [a["label"] for a in d["top_actors"]] == ["Fancy Bear"]
    assert d["rising"]["rising"]                                # drones/ransomware shares differ between periods


def test_pages_and_redirects(library):
    client = TestClient(app())
    r = client.get("/")
    assert r.status_code == 200 and "OPEN-SOURCE INTELLIGENCE" in r.text and 'action="/search"' in r.text
    r = client.get("/?country=CZ&topic=drones", follow_redirects=False)        # old Documents links keep working
    assert r.status_code == 307 and r.headers["location"] == "/documents?country=CZ&topic=drones"
    r = client.get("/search", params={"q": "country:CZ Annual"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/documents?country=CZ&q=Annual"
    r = client.get("/search", params={"q": "agency:BIS"})
    assert r.status_code == 200 and "is the name of 2 agencies" in r.text and "country%3ACZ%20agency%3ABIS" in r.text
    assert total(client, "/documents?undated=1") == 1
    assert client.get("/api/suggest", params={"q": "cz"}).json()["groups"][0]["items"][0]["flag"].endswith("cz.svg")


def app():
    from rozvedka.app import app as fastapi_app
    return fastapi_app


def test_static_files_are_stamped_and_revalidated(library):
    client = TestClient(app())
    page = client.get("/").text
    css = re.search(r'href="(/static/style\.css\?v=[0-9a-f]{8})"', page).group(1)
    assert re.search(r'src="/static/home\.js\?v=[0-9a-f]{8}"', page)
    assert "immutable" in client.get(css).headers["cache-control"]
    assert client.get("/static/style.css").headers["cache-control"] == "no-cache"
