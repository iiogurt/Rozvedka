"""Actor profiles: which picture is chosen (a group's flag before its article image, a person's photo), the facts and
how the actor page shows them with their sources."""
import json

import pytest
from fastapi.testclient import TestClient

from rozvedka import actor_profiles, actors, db
from rozvedka import app as app_module

GAZ = {"retrieved": "2026-10-01", "actors": [
    {"key": "Q5", "qid": "Q5", "kind": "armed", "label": "Wagner Group", "description": "Russian mercenary group",
     "reasons": [{"via": "seed", "kind": "armed", "text": "seed"}], "names": [{"name": "Wagner Group", "lang": "en", "origin": "Wikidata label"}],
     "wikidata": {"url": "https://www.wikidata.org/wiki/Q5", "revision": 1, "revision_url": "x", "retrieved": "2026-10-01"},
     "wikipedia": {"title": "Wagner Group", "extract": "", "url": "https://en.wikipedia.org/wiki/Wagner_Group"}},
    {"key": "Q1", "qid": "Q1", "kind": "person", "label": "Vladimir Putin", "description": "",
     "reasons": [{"via": "seed", "kind": "person", "text": "seed"}], "names": [{"name": "Vladimir Putin", "lang": "en", "origin": "Wikidata label"}],
     "wikidata": {"url": "https://www.wikidata.org/wiki/Q1", "revision": 1, "revision_url": "x", "retrieved": "2026-10-01"},
     "wikipedia": {"title": "Vladimir Putin", "extract": "", "url": "https://en.wikipedia.org/wiki/Vladimir_Putin"}}]}


def claim(prop, value, kind="wikibase-entityid", **qual):
    v = {"id": value} if kind == "wikibase-entityid" else value
    return {"rank": "normal", "mainsnak": {"snaktype": "value", "property": prop, "datavalue": {"type": kind, "value": v}},
            "qualifiers": {k: [{"datavalue": {"value": q}}] for k, q in qual.items()}}


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    g = tmp_path / "actors.json"
    g.write_text(json.dumps(GAZ))
    c = tmp_path / "actors.yaml"
    c.write_text("{}")
    monkeypatch.setattr(actors, "GAZETTEER", g)
    monkeypatch.setattr(actors, "CONFIG", c)
    monkeypatch.setattr(actor_profiles, "STORE", tmp_path / "profiles.json")
    monkeypatch.setattr(actor_profiles, "IMAGES", tmp_path / "img")
    app_module._independent["at"] = None
    db.init()
    actors.init()
    text = "The Wagner Group and Vladimir Putin."
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil',1)")
        con.execute("INSERT INTO documents(id,source_id,url,year,status) VALUES(1,1,'u1',2024,'downloaded')")
        con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(1,'',?)", (text,))
        con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages) VALUES(1,?,'x','[0]')", (len(text),))
    actors.index(workers=1)
    # the outside world, as the fetch would see it
    monkeypatch.setattr(actor_profiles, "wikipedia_pages", lambda titles: {
        "Wagner Group": {"title": "Wagner Group", "image": "Wagner fighters.jpg", "extract": "The Wagner Group is …",
                         "revision": 7, "revision_time": "2026-09-01T00:00:00Z", "url": "https://en.wikipedia.org/wiki/Wagner_Group",
                         "revision_url": "https://en.wikipedia.org/w/index.php?oldid=7"},
        "Vladimir Putin": {"title": "Vladimir Putin", "image": "Putin 2020.jpg", "extract": "Vladimir Putin is …",
                           "revision": 8, "revision_time": "2026-09-01T00:00:00Z", "url": "https://en.wikipedia.org/wiki/Vladimir_Putin",
                           "revision_url": "https://en.wikipedia.org/w/index.php?oldid=8"}})
    monkeypatch.setattr(actor_profiles, "wikidata", lambda qids: {
        "Q5": {"lastrevid": 99, "claims": {"P41": [claim("P41", "Flag of Wagner.svg", "string")],
                                           "P112": [claim("P112", "Q99")]}},
        "Q1": {"lastrevid": 98, "claims": {"P569": [claim("P569", {"time": "+1952-10-07T00:00:00Z", "precision": 11}, "time")],
                                           "P39": [claim("P39", "Q100", P580={"time": "+2012-05-07T00:00:00Z", "precision": 11})],
                                           "P41": [claim("P41", "Not used for people.svg", "string")]}}})
    monkeypatch.setattr(actor_profiles, "labels", lambda qids: {"Q99": "Dmitry Utkin", "Q100": "President of Russia"})
    monkeypatch.setattr(actor_profiles, "commons_info", lambda files: {
        f: {"file": f, "page": f"https://commons.wikimedia.org/wiki/File:{f}", "thumb": f"https://upload/{f}.png",
            "author": "Someone", "credit": None, "licence": "CC BY 4.0", "licence_url": "https://creativecommons.org/licenses/by/4.0"}
        for f in files})

    def download(url, stem):
        stem.with_suffix(".png").write_bytes(b"\x89PNG fake")
        return stem.with_suffix(".png").name
    monkeypatch.setattr(actor_profiles, "_download", download)
    yield tmp_path
    actor_profiles.load.cache_clear()
    app_module._independent["at"] = None


def test_fetch_chooses_pictures_and_facts(library):
    assert "2 pictures" in actor_profiles.fetch()
    wagner, putin = actor_profiles.profile("Q5"), actor_profiles.profile("Q1")
    assert wagner["picture"]["file"] == "Flag of Wagner.svg"            # a group: its flag before the article image
    assert wagner["picture"]["what"] == "flag (Wikidata P41)"
    assert putin["picture"]["file"] == "Putin 2020.jpg"                 # a person: the article's photo, never a flag
    assert {f["label"]: f["values"][0]["text"] for f in putin["facts"]} == {"Born": "1952-10-07", "Positions held": "President of Russia"}
    assert putin["facts"][1]["values"][0]["when"] == "2012–"
    assert actor_profiles.image_path("Q5").name == "Q5.png"


def test_actor_page_shows_profile(library):
    actor_profiles.fetch()
    client = TestClient(app_module.app)
    t = client.get("/actors/Q5").text
    assert 'src="/actor-image/Q5"' in t and "Flag (Wikidata P41)" in t
    assert '<a href="https://www.wikidata.org/wiki/Q99">Dmitry Utkin</a>' in t and 'href="https://www.wikidata.org/wiki/Q5#P112"' in t
    assert "CC BY 4.0" in t and "The Wagner Group is …" in t                     # picture licence; article lead as fallback
    r = client.get("/actor-image/Q5")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert client.get("/actor-image/Q404").status_code == 404
