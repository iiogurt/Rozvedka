"""Links between subjects stated in the text of their Wikipedia articles: sentences, the relation words, the network layer."""
import json

import pytest

from rozvedka import actors, collect, db, sanctions, series, techniques, ties, wikitext

ARTICLE = """{{Infobox organization|name=X|leader=[[Bob]]}}
'''Group A''' is an armed group.<ref>{{cite web|url=x}}</ref> It was founded in 1982 with money from [[Service B|the service]].
It is a member of the [[Alliance C]]. Its spokesman met [[Person D]] in 2001.
== History ==
In 2006 it fought [[Group E]]. A [[Somewhere|country]] hosted it. Mr. [[Person D]] led it after 2010.
== Members ==
* [[Person F]]
== See also ==
* [[Group G]]
"""


def test_sentences_and_relations():
    found = [(sec, s, t) for sec, s, t in wikitext.sentences(ARTICLE)]
    texts = [s for _, s, _ in found]
    assert "It was founded in 1982 with money from the service." in texts         # the link's label, refs and templates gone
    assert not any("Group G" in t for _, _, t in found)                         # See also is skipped
    assert ("Members", "Person F", [("Person F", "Person F")]) in found
    rel = {t[0][0]: wikitext.relation(s, sec, t[0][1]) for sec, s, t in found}
    assert rel["Service B"] == ("founding", "founded") and rel["Alliance C"] == ("membership", "member")
    assert rel["Group E"][0] == "conflict" and rel["Person F"] == ("membership", "members")
    assert wikitext.relation("Its spokesman met someone.") == (wikitext.GENERIC, "")
    far = ("He spent years in Geneva as an envoy of Group A, a professor and a human rights advocate before he was shot, and he "
           "was the elder brother of the organisation's leader Massoud Rajavi.")
    assert wikitext.relation(far, "", "Group A")[0] == wikitext.GENERIC             # "leader" belongs to someone else
    assert wikitext.relation(far, "", "Massoud Rajavi")[0] == "leadership"
    assert wikitext.norm_title("hezbollah#History") == "Hezbollah"


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(sanctions, "DIR", tmp_path / "s")
    monkeypatch.setattr(sanctions, "MATCHES", tmp_path / "s" / "m.json")
    monkeypatch.setattr(techniques, "FILE", tmp_path / "attack.json")
    monkeypatch.setattr(wikitext, "FILE", tmp_path / "wikitext.json")
    techniques._stored.cache_clear()
    sanctions._load.cache_clear()
    (tmp_path / "wikitext.json").write_text(json.dumps({"meta": {"retrieved": "2026-10-14"}, "articles": {
        "Q1": {"title": "Group A", "revision": 123, "links": [
            {"to": "Q2", "relation": "founding", "word": "founded", "section": "", "sentence": "It was founded with money from the service."},
            {"to": "Q9", "relation": "membership", "word": "members", "section": "Members", "sentence": "Person F"},
            {"to": "Q5", "relation": "named in the article", "word": "", "section": "History", "sentence": "A country hosted it."}]}}}))
    db.init()
    collect.init()
    actors.init()
    with db.session() as con:
        for k, kind, label in (("Q1", "armed", "Group A"), ("Q2", "state", "Service B"), ("Q5", "country", "Somewhere")):
            con.execute("INSERT INTO actors(key,kind,label,data) VALUES(?,?,?,'{}')", (k, kind, label))
        con.execute("INSERT INTO link_entities VALUES('Q9','Person F','a member',NULL,1,0)")
    ties.build()
    return tmp_path


def test_layer(library):
    with db.session() as con:
        rows = {(r["a"], r["b"]): dict(r) for r in con.execute("SELECT * FROM ties WHERE layer='wikitext'")}
    assert set(rows) == {("Q1", "Q2"), ("Q1", "Q9")}                         # never to a country
    ev = json.loads(rows[("Q1", "Q2")]["evidence"])
    assert rows[("Q1", "Q2")]["rel"] == "its article names (founding)" and rows[("Q1", "Q2")]["back"] == "named in the article of (founding)" and ev["word"] == "founded" and "oldid=123" in ev["url"]
    assert ties.entity("Q9")["kind"] == "person"
