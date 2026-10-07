"""Cross-language search: a word naming a concept also finds its names in other languages (from Wikidata)."""
import json
import re

import pytest
import yaml
from fastapi.testclient import TestClient

from rozvedka import collect, concepts, db, doclist, series, topics

STORE = {"source": "Wikidata (labels and aliases)", "retrieved": "2026-10-07", "missing": [], "concepts": [
    {"title": "Unmanned aerial vehicle", "category": "geopolitics", "qid": "Q484000", "revision": 1,
     "names": {"en": ["unmanned aerial vehicle", "drone", "UAV"], "de": ["unbemanntes Luftfahrzeug", "Drohne"],
               "cs": ["bezpilotní letoun", "dron"], "da": ["drone"]}},
    {"title": "Terrorism", "category": "extremism", "qid": "Q7283", "revision": 2,
     "names": {"en": ["terrorism", "terror"], "de": ["Terrorismus"], "fr": ["terrorisme"]}},
]}


@pytest.fixture
def store(tmp_path, monkeypatch):
    p = tmp_path / "concepts.json"
    p.write_text(json.dumps(STORE))
    monkeypatch.setattr(concepts, "STORE", p)
    concepts.load.cache_clear()
    yield p
    concepts.load.cache_clear()


def test_titles_file_is_valid():
    t = concepts.titles()
    assert "Unmanned aerial vehicle" in t and len(t) > 80
    cats = yaml.safe_load(concepts.CONCEPTS.read_text(encoding="utf-8"))
    assert all(isinstance(v, list) for v in cats.values())


def test_expand(store):
    fts, notes = concepts.expand("Drohne")
    assert [n["qid"] for n in notes] == ["Q484000"] and notes[0]["retrieved"] == "2026-10-07"
    assert '"drohne"*' in fts.lower() and '"drone"*' in fts and '"unmanned aerial vehicle"' in fts
    assert '"dron"' in fts and '"dron"*' not in fts          # short names as whole words (not Danish "dronning")
    assert '"uav"' in fts and '"uav"*' not in fts            # three letters: kept, as a whole word
    names = [n for _, n in notes[0]["names"]]
    assert names[:3] == ["unmanned aerial vehicle", "unbemanntes Luftfahrzeug", "bezpilotní letoun"]  # labels first
    # several words: each word is expanded on its own, and all must occur
    fts2, _ = concepts.expand("Drohne Angriff")
    assert fts2.endswith('AND "Angriff"*')
    # a multi-word name typed as a whole
    _, n3 = concepts.expand("unmanned aerial vehicle")
    assert [n["qid"] for n in n3] == ["Q484000"]
    # explicit OR and unknown words: as typed
    assert concepts.expand("drone OR Drohne")[1] == [] and concepts.expand("Kreml")[1] == []


def test_prefix_cover(store):
    fts, _ = concepts.expand("terrorism")
    assert '"terror"*' in fts and "terrorismus" not in fts and "terrorisme" not in fts


@pytest.fixture
def library(tmp_path, monkeypatch, store):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    db.init()
    collect.init()
    topics.init()
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(1,'DE/BfV','DE','BfV','intelligence-civil',1)")
        for i, text in ((1, "Die Drohne flog über die Kaserne."), (2, "Drones were seen over the base."),
                        (3, "Bezpilotní letoun nad základnou."), (4, "Nothing related.")):
            con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,local_path)
                           VALUES(?,1,?,?,'de',2025,'downloaded',?)""", (i, f"https://x/{i}.pdf", f"Report {i}", f"f{i}.pdf"))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", text))
    return tmp_path


def test_documents_search_in_all_languages(library):
    assert doclist.count(q="Drohne") == 3 and doclist.count(q="Drohne", exact=1) == 1
    assert doclist.count(q="Drohne", indexed=1) == 0          # a Trends link counts literally (and only indexed text)
    from rozvedka.app import app
    client = TestClient(app)
    t = client.get("/documents?q=Drohne").text
    assert re.search(r"<b>3</b> documents match", t) and "Q484000" in t and "Search only the words as typed" in t
    t = client.get("/documents?q=Drohne&exact=1").text
    assert re.search(r"<b>1</b> documents match", t) and "Also find it in other languages" in t
