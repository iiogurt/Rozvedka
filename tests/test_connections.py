"""Connections: infobox parsing, grouping from both sides, connected people by full name, passage hints."""
import json

import pytest

from rozvedka import actors, connections, db, topics


def test_infobox_inline_params_nested_templates_and_notes():
    w = ("{{Infobox company | name = X | founder = {{ubl|[[Nigel Oakes]]|[[Alexander Nix]]}} "
         "| key_people = [[Alexander Nix]] ([[Chief executive officer|CEO]])<ref>{{cite web|url=u}}</ref> "
         "| parent = [[SCL Group]] | image = [[File:x.png]] }} rest")
    got = [(l["field"], l["relation"], l["title"], l["note"]) for l in connections.infobox_links(w)]
    assert ("founder", "founded by", "Nigel Oakes", "") in got
    assert ("key_people", "key people", "Alexander Nix", "CEO") in got
    assert ("parent", "parent organisation", "SCL Group", "") in got
    assert not any(t.startswith("File:") for _, _, t, _ in got)


def test_person_infobox_uses_person_fields():
    w = "{{Infobox officeholder | party = [[Alternative for Germany]] | predecessor = [[Andreas Kalbitz]] }}"
    assert [l["title"] for l in connections.infobox_links(w, person=True)] == ["Alternative for Germany"]
    assert [l["title"] for l in connections.infobox_links(w)] == ["Andreas Kalbitz"]     # organisation fields


def entry(key, kind, label, names, **kw):
    return {"key": key, "qid": key, "kind": kind, "label": label, "description": "", "reasons": [{"via": "seed", "kind": kind, "text": ""}],
            "names": [{"name": n, "lang": "en", "origin": "Wikidata label"} for n in names], **kw}


SRC_WP = {"type": "wikipedia", "article": "Alternative for Germany", "field": "leader_name", "revision": 1,
          "url": "https://en.wikipedia.org/wiki/Alternative_for_Germany", "revision_url": "u", "retrieved": "2026-10-01"}
SRC_WD = {"type": "wikidata", "property": "P102", "statement": "s", "url": "https://www.wikidata.org/wiki/Q2#P102",
          "ref": None, "stated_in": None, "retrieved": "2026-10-01"}


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    gaz = {"retrieved": "2026-10-01", "actors": [
        entry("Q1", "party", "Alternative for Germany", ["Alternative für Deutschland", "AfD"]),
        entry("Q2", "person", "Björn Höcke", ["Björn Höcke", "Höcke"], connected=True),
        entry("Q3", "person", "Alice Weidel", ["Alice Weidel"], connected=True)],
        "links": [
            {"a": "Q2", "b": "Q1", "a_says": "member of the party", "b_says": "party members", "start": "2013-01-01",
             "end": None, "role": None, "note": "", "source": SRC_WD},
            {"a": "Q1", "b": "Q3", "a_says": "led by", "b_says": "leader of", "start": None, "end": None, "role": None,
             "note": "", "source": SRC_WP},
            {"a": "Q1", "b": "Q9", "a_says": "subsidiaries and units", "b_says": "parent organisation", "start": None,
             "end": None, "role": None, "note": "", "source": SRC_WP}],
        "entities": {"Q9": {"label": "Generation Germany", "description": "youth wing", "wikipedia": "w", "human": False,
                            "org": True}, "_totals": {"Q1|P102": 883}}}
    (tmp_path / "actors.json").write_text(json.dumps(gaz))
    (tmp_path / "actors.yaml").write_text("{}")
    monkeypatch.setattr(actors, "GAZETTEER", tmp_path / "actors.json")
    monkeypatch.setattr(actors, "CONFIG", tmp_path / "actors.yaml")
    db.init()
    actors.init()
    h = topics.taxonomy()["hash"]
    texts = {1: "Björn Höcke spoke for the Alternative für Deutschland (AfD) in Erfurt.",
             2: "Höcke alone is not matched; the AfD and Alice Weidel are."}
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'DE/BfV','DE','BfV','intelligence-civil')")
        for i, t in texts.items():
            con.execute("INSERT INTO documents(id,source_id,url,year,status) VALUES(?,?,?,?,'downloaded')", (i, 1, f"u{i}", 2024))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", t))
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages) VALUES(?,?,?,?)", (i, len(t), h, "[0]"))
    actors.index(workers=1)
    return tmp_path


def test_connected_people_only_by_full_name(library):
    with db.session() as con:
        rows = {(r["doc_id"], r["actor_key"]) for r in con.execute("SELECT doc_id, actor_key FROM doc_actors")}
        hocke = con.execute("SELECT reason FROM actor_names WHERE name='Höcke'").fetchone()["reason"]
    assert (1, "Q2") in rows and (2, "Q2") not in rows
    assert hocke.startswith("one word of the name of a connected person")
    assert (2, "Q1") in rows and (2, "Q3") in rows          # "AfD": mixed-case abbreviation counts on its own


def test_connections_from_both_sides(library):
    d = actors.actor_detail("Q1")
    groups = {g["group"]: g for g in d["connections"]}
    members = groups["Members & people"]
    assert [c["key"] for c in members["entries"]] == ["Q2"] and members["entries"][0]["says"] == ["party members"]
    assert members["total"] == 883
    weidel = groups["Leadership"]["entries"][0]
    assert weidel["key"] == "Q3" and weidel["together"] == 1 and weidel["pair_link"] == "/actors/Q1/with/Q3"
    youth = groups["Organisation"]["entries"][0]
    assert youth["label"] == "Generation Germany" and not youth["actor"] and youth["sources"][0]["field"] == "leader_name"
    person = {g["group"]: g for g in actors.actor_detail("Q2")["connections"]}
    assert person["Memberships & roles"]["entries"][0]["key"] == "Q1"


def test_passages_name_nearby_connected_actors(library):
    d = actors.actor_detail("Q2")
    near = d["passages"][0]["nearby"]
    assert near[0]["key"] == "Q1" and near[0]["says"] == "member of the party"


def test_pair_page_shows_known_connection(library):
    k = actors.pair_detail("Q1", "Q2")["known"]
    assert k and k[0]["a_says"] == "member of the party" and k[0]["source"]["type"] == "wikidata"


def test_pages_render(library):
    from fastapi.testclient import TestClient

    from rozvedka.app import app
    with TestClient(app) as client:
        for url in ("/actors/Q1", "/actors/Q2", "/actors/Q1/with/Q2", "/actors?kind=party", "/actors/names"):
            r = client.get(url)
            assert r.status_code == 200, url
        assert "Generation Germany" in client.get("/actors/Q1").text
        assert "Known connection" in client.get("/actors/Q1/with/Q2").text
