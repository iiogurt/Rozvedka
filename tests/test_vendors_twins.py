"""Security vendors' names for threat groups (MISP galaxy) and toolkit twins (MITRE ATT&CK)."""
import json

import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, collect, db, sanctions, series, techniques, ties, twins, vendors

MISP = {"meta": {"version": 352, "retrieved": "2026-10-14"}, "clusters": [
    {"uuid": "u1", "value": "APT28", "synonyms": ["G0007", "Forest Blizzard", "STRONTIUM", "Pioneer", "TA422", "Shared Name"],
     "country": "RU", "sponsor": "Russian Federation", "refs": [], "description": "",
     "related": [{"uuid": "u3", "type": "similar", "likelihood": "likely"}]},
    {"uuid": "u2", "value": "Sandworm", "synonyms": ["Seashell Blizzard", "Shared Name"], "country": "RU", "sponsor": None,
     "refs": [], "description": "", "related": []},
    {"uuid": "u3", "value": "Unknown Group", "synonyms": [], "country": None, "sponsor": None, "refs": [], "description": "",
     "related": []},
]}
GAZ = [{"key": "Q1", "kind": "cyber", "label": "Fancy Bear", "attack": {"id": "G0007"}, "names": [{"name": "Fancy Bear", "lang": "", "origin": "x"}]},
       {"key": "Q2", "kind": "cyber", "label": "Sandworm", "attack": None, "names": [{"name": "Sandworm", "lang": "", "origin": "x"}]},
       {"key": "Q3", "kind": "person", "label": "Unknown Group", "names": [{"name": "Unknown Group", "lang": "", "origin": "x"}]}]


@pytest.fixture
def misp(tmp_path, monkeypatch):
    monkeypatch.setattr(vendors, "FILE", tmp_path / "misp.json")
    vendors._stored.cache_clear()
    (tmp_path / "misp.json").write_text(json.dumps(MISP))
    return tmp_path


def test_groups_tied_to_actors(misp):
    tied = vendors.tie_to_actors(GAZ)
    assert tied["u1"] == ("Q1", "ATT&CK G0007 among its synonyms")
    assert tied["u2"][0] == "Q2" and "u3" not in tied              # a person's name does not tie a group


def test_vendor_names_and_their_rules(misp):
    names = {k: [n["name"] for n in v] for k, v in vendors.extra_names(GAZ).items()}
    assert names["Q1"] == ["APT28", "Forest Blizzard", "STRONTIUM", "TA422"]     # not G0007, "Pioneer" or the shared name
    assert "Shared Name" not in names["Q2"] and "Seashell Blizzard" in names["Q2"]
    gaz = json.loads(json.dumps(GAZ))
    gaz.append({"key": "Q9", "kind": "cyber", "label": "STRONTIUM", "names": [{"name": "STRONTIUM", "lang": "", "origin": "x"}]})
    gaz = vendors.with_names({"actors": gaz})
    added = [n["name"] for n in gaz["actors"][0]["names"] if n["origin"].startswith(vendors.ORIGIN)]
    assert "Forest Blizzard" in added and "STRONTIUM" not in added          # another actor's own name stays its own
    assert vendors.distinctive("UNC2452") and vendors.distinctive("STRONTIUM") and not vendors.distinctive("Axiom")


ATTACK = {"meta": {"versions": {"enterprise-attack": "20.0"}, "retrieved": "2026-10-14"},
          "techniques": {f"T10{i:02d}": {"id": f"T10{i:02d}", "name": f"Tech {i}", "tactics": ["execution"], "retired": False,
                                         "groups": ([["G0001", "A"], ["G0002", "B"]] if i < 6 else []) + ([["G0003", "C"]] if i < 2 or i > 8 else [])}
                         for i in range(12)},
          "software": {"S0001": {"id": "S0001", "name": "Rare Implant", "type": "malware", "url": "u", "aliases": []},
                       "S0002": {"id": "S0002", "name": "Mimikatz", "type": "tool", "url": "u", "aliases": []}},
          "campaigns": {}, "groups": {"G0001": "A", "G0002": "B", "G0003": "C"},
          "relations": [["G0001", "uses", "S0001", ""], ["G0002", "uses", "S0001", ""], ["G0001", "uses", "S0002", ""],
                        ["G0002", "uses", "S0002", ""], ["G0003", "uses", "S0002", ""]]}


@pytest.fixture
def catalog(tmp_path, monkeypatch, misp):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(techniques, "FILE", tmp_path / "attack.json")
    monkeypatch.setattr(sanctions, "DIR", tmp_path / "s")
    monkeypatch.setattr(sanctions, "MATCHES", tmp_path / "s" / "m.json")
    techniques._stored.cache_clear()
    sanctions._load.cache_clear()
    (tmp_path / "attack.json").write_text(json.dumps(ATTACK))
    db.init()
    collect.init()
    actors.init()
    with db.session() as con:
        con.execute("INSERT INTO actors(key,kind,label,data) VALUES('Q1','cyber','Fancy Bear',?)", (json.dumps({"attack": {"id": "G0001"}}),))
    return tmp_path


def test_twins_weight_rare_items(catalog):
    rows = twins.ranking()
    assert [(r["a"], r["b"]) for r in rows] == [("G0002", "Q1")]     # A (actor Q1) and B share 6 techniques + 2 programs
    r = rows[0]
    assert r["techniques"] == 6 and r["software"] == 2 and 0 < r["score"] <= 1
    d = twins.pair("Q1", "G0002")
    assert d["shared_software"][0]["name"] == "Rare Implant"                 # used by 2 of 3 groups: rarer than Mimikatz
    assert {s["name"] for s in d["shared_software"]} == {"Rare Implant", "Mimikatz"}
    assert twins.of_group("Q1")[0]["b"] == "G0002" and twins.pair("Q1", "Q1") is None


def test_misp_layer_and_pages(catalog):
    gaz = {"actors": GAZ}
    import rozvedka.actors as A
    orig = A.load_gazetteer
    A.load_gazetteer = lambda: gaz
    try:
        ties.build()
    finally:
        A.load_gazetteer = orig
    with db.session() as con:
        rows = {(r["a"], r["b"], r["layer"]) for r in con.execute("SELECT a, b, layer FROM ties")}
    assert ("Q1", "misp:u3", "misp") in rows
    from rozvedka.app import app
    with TestClient(app) as client:
        assert "Toolkit twins" in client.get("/graph/twins").text
        page = client.get("/graph/twins/Q1/G0002").text
        assert "share <b>6</b> techniques and <b>2</b> programs" in page and "Rare Implant" in page
        assert client.get("/graph/twins/Q1/NOPE").status_code == 404
        assert 'id="twins"' in client.get("/actors/Q1").text
