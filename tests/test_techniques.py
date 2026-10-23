"""ATT&CK technique numbers in the reports, MITRE's technique list, and the pages and links that show them."""
import json

import pytest
from fastapi.testclient import TestClient

from rozvedka import collect, db, doclist, series, techniques


def test_technique_numbers_are_found_with_and_without_sub_technique():
    found = techniques.find("T1566.001 and T1566, (T1059.003) but not T12345, XT1566, T1566x, T2000 or v1.T1003")
    assert set(found) == {"T1566.001", "T1566", "T1059.003"}
    assert found["T1566.001"] == [[0, 9]]
    assert len(techniques.find("T1003 then T1003")["T1003"]) == 2


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(techniques, "FILE", tmp_path / "attack.json")
    techniques._stored.cache_clear()
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    db.init()
    collect.init()
    from rozvedka import actors
    actors.init()
    techniques.init()
    texts = {1: "Phishing (T1566.001) then T1059.003 on the host.", 2: "T1566.001 once, T1999 never defined.", 3: "T1059.003 again."}
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'CZ/NUKIB','CZ','NÚKIB','cyber')")
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(2,'DE/BSI','DE','BSI','cyber')")
        con.execute("INSERT INTO actors(key,kind,label,data) VALUES('Q1','cyber','Fancy Bear',?)",
                    (json.dumps({"attack": {"id": "G0007"}}),))
        for i, t in texts.items():
            con.execute("INSERT INTO documents(id,source_id,url,title,year,lang,status) VALUES(?,?,?,?,?,'en','downloaded')",
                        (i, 1 if i < 3 else 2, f"https://x/{i}.pdf", f"Report {i}", 2023))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", t))
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages) VALUES(?,?,?,?)", (i, len(t), "x", "[0]"))
    (tmp_path / "attack.json").write_text(json.dumps({
        "meta": {"versions": {"enterprise-attack": "19.0"}, "retrieved": "2026-01-02", "page": "https://m/", "terms": "https://m/t"},
        "techniques": {
            "T1566.001": {"id": "T1566.001", "name": "Spearphishing Attachment", "parent": "Phishing", "url": "https://m/T1566/001",
                          "tactics": ["initial-access"], "matrix": "enterprise-attack", "retired": False,
                          "groups": [["G0007", "APT28"], ["G9999", "Other"]]},
            "T1059.003": {"id": "T1059.003", "name": "Windows Command Shell", "parent": "Command and Scripting Interpreter",
                          "url": "https://m/T1059/003", "tactics": ["execution"], "matrix": "enterprise-attack", "retired": True,
                          "groups": []}}}), encoding="utf-8")
    techniques._stored.cache_clear()
    return tmp_path


def test_index_and_views(library):
    r = techniques.index()
    assert r["reports"] == 3 and r["techniques"] == 3 and r["mentions"] == 5
    o = techniques.overview()
    assert [(x["technique"], x["docs"], x["agencies"]) for x in o["rows"]] == [("T1059.003", 2, 2), ("T1566.001", 2, 1)]
    assert o["total"] == 2 and o["unknown"] == 1                                   # T1999 is not in MITRE's list
    assert [x["technique"] for x in techniques.overview(tactic="execution")["rows"]] == ["T1059.003"]
    assert [x["technique"] for x in techniques.overview(q="phishing")["rows"]] == ["T1566.001"]
    d = techniques.detail("t1566.001")
    assert d["reports"] == 2 and d["title"] == "Phishing: Spearphishing Attachment" and d["shown"][0]["match"] == "T1566.001"
    assert [(g["id"], g["actor"] and g["actor"]["key"]) for g in d["groups"]] == [("G0007", "Q1"), ("G9999", None)]
    assert techniques.detail("T1999") is None and [t["technique"] for t in techniques.of_doc(2)] == ["T1566.001"]


def test_every_count_links_to_exactly_those_reports(library):
    techniques.index()
    assert doclist.count(technique="T1566.001") == 2 and doclist.count(technique="T1059.003") == 2
    assert doclist.count(technique="T1999") == 1                                  # the filter is by number; the views drop unknown ones


def test_pages(library):
    techniques.index()
    from rozvedka.app import app
    c = TestClient(app)
    t = c.get("/techniques").text
    assert "Spearphishing Attachment" in t and "/documents?technique=T1566.001" in t and "retired" in t and "19.0" in t
    assert "T1566.001" not in c.get("/techniques?tactic=execution").text
    p = c.get("/techniques/T1566.001").text
    assert "initial-access" in p and '<a href="/actors/Q1">Fancy Bear</a>' in p and "Other" in p
    assert "MITRE has retired this number" in c.get("/techniques/T1059.003").text
    assert c.get("/techniques/T1999").status_code == 404
    d = c.get("/documents?technique=T1566.001").text
    assert "naming ATT&amp;CK technique T1566.001" in d and "Report 1" in d and "Report 3" not in d
    r = c.get("/report/2").text
    assert 'id="techniques"' in r and "Spearphishing Attachment" in r and "T1999" not in r


def test_tactic_grid_follows_attacks_order_and_every_number_is_its_list(library):
    techniques.index()
    g = techniques.grid()
    assert [(c["tactic"], c["reports"], c["named"], c["in_catalog"]) for c in g["cols"]] == [
        ("initial-access", 2, 1, 1), ("execution", 2, 1, 1)]                   # kill-chain order, not alphabetical
    assert g["reports"] == 3 and g["cols"][0]["techniques"][0]["technique"] == "T1566.001"
    for _label, n, url in techniques.figures():
        assert doclist.count(technique=url.split("technique=")[1].split("&")[0], indexed=1) == n, url
    assert techniques.tactic_name("command-and-control") == "Command & control"
    c = TestClient(__import__("rozvedka.app", fromlist=["app"]).app)
    assert 'id="grid"' in c.get("/techniques").text
    assert "of the ATT&amp;CK tactic “initial access”" in c.get("/documents?technique=tactic:initial-access").text
