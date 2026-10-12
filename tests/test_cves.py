"""CVE numbers in the reports, the Known Exploited Vulnerabilities list, and the pages and links that show them."""
import json

import pytest
from fastapi.testclient import TestClient

from rozvedka import collect, cves, db, doclist, series


def test_cve_numbers_are_found_in_every_spelling():
    text = "CVE-2021-44228 and CVE‑2021‑26855, cve-2023-0001; not CVE-1850-1234 nor CVE-2021-12."
    found = cves.find(text)
    assert set(found) == {"CVE-2021-44228", "CVE-2021-26855", "CVE-2023-0001"}
    assert found["CVE-2021-44228"] == [[0, 14]]
    assert len(cves.find("CVE-2021-44228 once, CVE-2021-44228 twice")["CVE-2021-44228"]) == 2


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(cves, "KEV_FILE", tmp_path / "kev.json")
    cves._kev.cache_clear()
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    db.init()
    collect.init()
    from rozvedka import actors
    actors.init()
    cves.init()
    texts = {1: "Fancy Bear exploited CVE-2023-23397 in Outlook against Ukraine.",
             2: "Patch CVE-2021-44228 now. " + "x " * 800 + "Fancy Bear is named far away from the CVE.",
             3: "CVE-2023-23397 again, with Fancy Bear nearby."}
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'CZ/NUKIB','CZ','NÚKIB','cyber')")
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(2,'DE/BSI','DE','BSI','cyber')")
        con.execute("INSERT INTO actors(key,kind,label,data) VALUES('Q1','cyber','Fancy Bear','{}')")
        for i, t in texts.items():
            con.execute("INSERT INTO documents(id,source_id,url,title,year,lang,status) VALUES(?,?,?,?,?,'en','downloaded')",
                        (i, 1 if i < 3 else 2, f"https://x/{i}.pdf", f"Report {i}", 2023))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", t))
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages) VALUES(?,?,?,?)", (i, len(t), "x", "[0]"))
            s = t.index("Fancy Bear")
            con.execute("INSERT INTO doc_actors(doc_id,actor_key,hits,spans,names) VALUES(?, 'Q1', 1, ?, '{}')", (i, json.dumps([[s, s + 10]])))
    (tmp_path / "kev.json").write_text(json.dumps({
        "meta": {"version": "2026.01.01", "retrieved": "2026-01-02", "license": "CC0 1.0", "page": "https://k/"},
        "vulns": {"CVE-2023-23397": {"vendorProject": "Microsoft", "product": "Outlook", "vulnerabilityName": "Elevation",
                                     "dateAdded": "2023-03-14", "shortDescription": "d", "dueDate": "2023-04-04",
                                     "knownRansomwareCampaignUse": "Unknown", "cwes": ["CWE-294"]}}}))
    cves._kev.cache_clear()
    return tmp_path


def test_index_finds_cves_and_actors_named_in_the_same_passage(library):
    r = cves.index()
    assert r["reports"] == 3 and r["cves"] == 2 and r["mentions"] == 3
    with db.session() as con:
        pairs = {tuple(x) for x in con.execute("SELECT actor_key, cve, doc_id FROM actor_cves")}
    assert pairs == {("Q1", "CVE-2023-23397", 1), ("Q1", "CVE-2023-23397", 3)}      # document 2: the actor is far from the CVE


def test_overview_detail_and_actor_view(library):
    cves.index()
    o = cves.overview()
    assert [(r["cve"], r["docs"], r["agencies"], r["on_kev"]) for r in o["rows"]] == [
        ("CVE-2023-23397", 2, 2, True), ("CVE-2021-44228", 1, 1, False)]
    assert o["n_kev"] == 1 and o["meta"]["version"] == "2026.01.01"
    assert [r["cve"] for r in cves.overview(kev="yes")["rows"]] == ["CVE-2023-23397"]
    assert [r["cve"] for r in cves.overview(q="outlook")["rows"]] == ["CVE-2023-23397"]
    d = cves.detail("cve-2023-23397")
    assert d["reports"] == 2 and d["on_kev"] and [a["key"] for a in d["actors"]] == ["Q1"] and d["actors"][0]["docs"] == 2
    assert d["shown"][0]["match"] == "CVE-2023-23397" and cves.detail("CVE-2020-0001") is None
    assert [(r["cve"], r["docs"]) for r in cves.of_actor("Q1")] == [("CVE-2023-23397", 2)]
    assert [c["cve"] for c in cves.of_doc(2)] == ["CVE-2021-44228"]


def test_every_count_links_to_exactly_those_reports(library):
    cves.index()
    assert doclist.count(cve="CVE-2023-23397") == 2 and doclist.count(cve="CVE-2021-44228") == 1
    assert doclist.count(cve="CVE-2023-23397", cve_near="Q1") == 2
    assert doclist.count(cve="CVE-2021-44228", cve_near="Q1") == 0
    assert doclist.count(cve="kev") == 2                       # reports naming any CVE on CISA's list


def test_pages(library):
    cves.index()
    from rozvedka.app import app
    c = TestClient(app)
    t = c.get("/cves").text
    assert "CVE-2023-23397" in t and "added 2023-03-14" in t and "/documents?cve=CVE-2023-23397" in t and "2026.01.01" in t
    assert "CVE-2021-44228" not in c.get("/cves?kev=yes").text
    p = c.get("/cves/CVE-2023-23397").text
    assert "Yes – on CISA" in p and "Microsoft Outlook" in p and "Fancy Bear" in p and "cve_near=Q1" in p
    assert "Not on CISA's list" in c.get("/cves/CVE-2021-44228").text
    assert c.get("/cves/CVE-2020-0001").status_code == 404
    a = c.get("/actors/Q1").text
    assert 'id="cves"' in a and "/documents?cve=CVE-2023-23397&cve_near=Q1" in a
    d = c.get("/documents?cve=CVE-2023-23397&cve_near=Q1").text
    assert "within one passage of Fancy Bear" in d and "Report 1" in d and "Report 2" not in d
    assert 'id="cves"' in c.get("/report/2").text and "CVE-2021-44228" in c.get("/report/2").text
