"""The connection graph: links read from the sanctions lists, Wikidata, ATT&CK and the reports, with their evidence,
the rules that keep the narrative matching honest, and the pages that show them."""
import json

import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, collect, db, sanctions, series, techniques, ties

OFAC = """<sdnList xmlns="x">
<sdnEntry><uid>7</uid><lastName>HIZBALLAH</lastName><sdnType>Entity</sdnType><programList><program>SDGT</program></programList>
  <akaList><aka><category>strong</category><lastName>ISLAMIC JIHAD ORGANIZATION</lastName></aka></akaList></sdnEntry>
<sdnEntry><uid>8</uid><lastName>AL-QARD FINANCE</lastName><sdnType>Entity</sdnType><programList><program>SDGT</program></programList>
  <remarks>(Linked To: HIZBALLAH; Linked To: DOE, John)</remarks></sdnEntry>
<sdnEntry><uid>9</uid><firstName>John</firstName><lastName>DOE</lastName><sdnType>Individual</sdnType>
  <remarks>(Linked To: NOBODY ON THIS LIST)</remarks></sdnEntry>
<sdnEntry><uid>10</uid><lastName>OCEAN STAR</lastName><sdnType>Vessel</sdnType><remarks>(Linked To: AL-QARD FINANCE)</remarks></sdnEntry>
</sdnList>"""
UK = """<Designations>
<Designation><UniqueID>RUS1</UniqueID><DateDesignated>01/02/2023</DateDesignated><IndividualEntityShip>Individual</IndividualEntityShip>
  <Names><Name><Name1>Ivan</Name1><Name6>PETROV</Name6><NameType>Primary Name</NameType></Name></Names>
  <UKStatementofReasons>Ivan PETROV is a director of Rostec, which is owned by the Government. He works for the Ministry of Defence. This undermines prosperity. No. 12 “On Rostec” was signed.</UKStatementofReasons></Designation>
<Designation><UniqueID>RUS2</UniqueID><IndividualEntityShip>Entity</IndividualEntityShip>
  <Names><Name><Name6>ROSTEC</Name6><NameType>Primary Name</NameType></Name></Names></Designation>
<Designation><UniqueID>RUS3</UniqueID><IndividualEntityShip>Entity</IndividualEntityShip>
  <Names><Name><Name6>PROSPERITY</Name6><NameType>Primary Name</NameType></Name></Names></Designation>
<Designation><UniqueID>RUS4</UniqueID><IndividualEntityShip>Entity</IndividualEntityShip>
  <Names><Name><Name6>MINISTRY OF DEFENCE</Name6><NameType>Primary Name</NameType></Name></Names></Designation>
<Designation><UniqueID>RUS5</UniqueID><IndividualEntityShip>Ship</IndividualEntityShip>
  <Names><Name><Name6>KALININGRAD</Name6><NameType>Primary Name</NameType></Name></Names>
  <UKStatementofReasons>Owned by Ivan Petrov, sails from Kaliningrad.</UKStatementofReasons></Designation>
</Designations>"""
UN = """<CONSOLIDATED_LIST><INDIVIDUALS><INDIVIDUAL><DATAID>1</DATAID><FIRST_NAME>ABU</FIRST_NAME><SECOND_NAME>EXAMPLE</SECOND_NAME>
<UN_LIST_TYPE>Al-Qaida</UN_LIST_TYPE><REFERENCE_NUMBER>QDi.001</REFERENCE_NUMBER><LISTED_ON>2007-01-02</LISTED_ON>
<COMMENTS1>Responsible for the finances of Al-Qa’ida (QDe.004) in Yemen.</COMMENTS1></INDIVIDUAL></INDIVIDUALS>
<ENTITIES><ENTITY><DATAID>2</DATAID><FIRST_NAME>AL-QAIDA</FIRST_NAME><UN_LIST_TYPE>Al-Qaida</UN_LIST_TYPE>
<REFERENCE_NUMBER>QDe.004</REFERENCE_NUMBER><LISTED_ON>2001-10-06</LISTED_ON></ENTITY></ENTITIES></CONSOLIDATED_LIST>"""


ENTRY = {"list": "US", "ref": "7", "entry": "HIZBALLAH", "matched": "HIZBALLAH", "date": "", "programme": "SDGT", "legal": [],
         "url": "https://sanctionssearch.ofac.treas.gov/Details.aspx?id=7", "type": "group"}


def test_linked_to_names():
    assert sanctions.linked_to("(Linked To: ISLAMIC REVOLUTIONARY GUARD CORPS (IRGC)-QODS FORCE; Linked To: HIZBALLAH)") == \
        ["ISLAMIC REVOLUTIONARY GUARD CORPS (IRGC)-QODS FORCE", "HIZBALLAH"]
    assert sanctions.linked_to("(Linked To: PATINO FOMEQUE, Victor Julio)") == ["PATINO FOMEQUE, Victor Julio"]
    assert sanctions.linked_to("") == []


def test_sentences_keep_abbreviations():
    assert ties._sentences("Head of it. Mr. Ivan PETROV (No. 7 “On X”). He is.\nNew line") == \
        ["Head of it.", "Mr. Ivan PETROV (No. 7 “On X”).", "He is.", "New line"]


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(sanctions, "DIR", tmp_path / "s")
    monkeypatch.setattr(sanctions, "MATCHES", tmp_path / "s" / "matches.json")
    monkeypatch.setattr(techniques, "FILE", tmp_path / "attack.json")
    techniques._stored.cache_clear()
    sanctions._load.cache_clear()
    (tmp_path / "s").mkdir()
    for key, text in (("US", OFAC), ("UK", UK), ("UN", UN)):
        (tmp_path / "s" / sanctions.LISTS[key]["file"]).write_text(text, encoding="utf-8")
    # the sanctions matching tied OFAC's HIZBALLAH to Hezbollah by its own name, and to another actor only by an alias
    (tmp_path / "s" / "matches.json").write_text(json.dumps({"retrieved": {"US": "2026-10-09"}, "actors": {
        "Q2": [{**ENTRY, "via": "name"}], "Q9": [{**ENTRY, "via": "alias"}]}}))
    (tmp_path / "attack.json").write_text(json.dumps({
        "meta": {"retrieved": "2026-10-14"}, "techniques": {},
        "software": {"S0002": {"id": "S0002", "name": "Mimikatz", "type": "tool", "url": "https://attack.mitre.org/software/S0002", "aliases": []}},
        "campaigns": {}, "groups": {"G0007": "APT28"},
        "relations": [["G0007", "uses", "S0002", "APT28 has used Mimikatz."]]}))
    db.init()
    collect.init()
    actors.init()
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'DE/BfV','DE','BfV','intelligence-civil')")
        for key, kind, label, data in (("Q1", "cyber", "Fancy Bear", {"attack": {"id": "G0007"}}), ("Q2", "terror", "Hezbollah", {}),
                                       ("Q3", "terror", "Hamas", {}), ("Q9", "terror", "Islamic Jihad Organization", {}),
                                       ("Q10", "country", "Lebanon", {})):
            con.execute("INSERT INTO actors(key,kind,label,data) VALUES(?,?,?,?)", (key, kind, label, json.dumps(data)))
        for i in (1, 2, 3):
            con.execute("INSERT INTO documents(id,source_id,url,title,year,status) VALUES(?,1,?,?,2024,'downloaded')", (i, f"u{i}", f"R{i}"))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", "Hezbollah and Hamas. Lebanon."))
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages) VALUES(?,?,?,?)", (i, 30, "x", "[0]"))
        # Hezbollah and Hamas named together in two reports, Hezbollah and Fancy Bear in one, a country in all three
        con.executemany("INSERT INTO actor_pairs VALUES(?,?,?,1)", [(1, "Q2", "Q3"), (2, "Q2", "Q3"), (3, "Q1", "Q2"),
                                                                    (1, "Q10", "Q2"), (2, "Q10", "Q2"), (3, "Q10", "Q2")])
        con.executemany("INSERT INTO doc_actors VALUES(?,?,1,?,'{}')", [(1, "Q2", "[[0,9]]"), (1, "Q3", "[[14,19]]"),
                                                                       (2, "Q2", "[[0,9]]"), (2, "Q3", "[[14,19]]")])
        con.execute("""INSERT INTO actor_links(a,b,a_says,b_says,source) VALUES('Q2','Q77','led by','leader of',?)""",
                    (json.dumps({"type": "wikidata", "property": "P488", "url": "https://www.wikidata.org/wiki/Q2#P488", "retrieved": "2026-10-07"}),))
        con.execute("INSERT INTO link_entities VALUES('Q77','Naim Qassem','Lebanese cleric',NULL,1,0)")
    ties.build()
    return tmp_path


def _all():
    with db.session() as con:
        return {(r["a"], r["b"], r["layer"]): dict(r) for r in con.execute("SELECT * FROM ties")}


def test_ofac_linked_to_resolved_on_the_list(library):
    t = _all()
    assert ("US:8", "Q2", "us") in t                 # HIZBALLAH is Hezbollah: matched by its own name, the alias match yields
    assert ("US:8", "US:9", "us") in t               # "DOE, John" is the entry John DOE
    assert ("US:10", "US:8", "us") in t              # a vessel linked to a company
    assert json.loads(t[("US:8", "Q2", "us")]["evidence"])["quote"] == "Linked To: HIZBALLAH"
    assert ties.meta()["stats"]["us"]["unresolved"] == 1          # "NOBODY ON THIS LIST"
    assert ties.entity("US:10")["kind"] == "vessel"


def test_listing_narratives_rules(library):
    t = _all()
    uk = {(a, b) for a, b, layer in t if layer == "uk"}
    assert uk == {("UK:RUS1", "UK:RUS2"), ("UK:RUS5", "UK:RUS1")}
    # not "PROSPERITY" (written as an ordinary word), not "MINISTRY OF DEFENCE" (generic words only: whose ministry?),
    # not the vessel "KALININGRAD" (one-word names only for organisations)
    ev = json.loads(t[("UK:RUS1", "UK:RUS2", "uk")]["evidence"])
    assert ev["quote"].startswith("Ivan PETROV is a director of Rostec") and ev["found"] == "rostec"
    assert t[("UK:RUS1", "UK:RUS2", "uk")]["date"] == "2023-02-01"
    assert ("UN:QDi.001", "UN:QDe.004", "un") in t     # UN listings cite each other by reference number


def test_reference_layers_and_reports(library):
    t = _all()
    assert ("Q1", "S0002", "attack") in t and t[("Q1", "S0002", "attack")]["rel"] == "uses"
    assert ("Q2", "Q77", "wikidata") in t
    rep = {(a, b): r for (a, b, layer), r in t.items() if layer == "reports"}
    assert set(rep) == {("Q2", "Q3")}             # one report together is not enough; countries never
    assert rep[("Q2", "Q3")]["weight"] == actors.pair_detail("Q2", "Q3")["docs"] == 2


def test_neighbours_seen_from_each_side(library):
    groups = {g["layer"]: g for g in ties.neighbours("Q2")}
    us = groups["us"]["rels"][0]
    assert us["says"] == "linked to it" and us["rows"][0]["other"] == "US:8"
    assert ties.neighbours("US:8")[0]["rels"][0]["says"] in ("linked to", "linked to it")
    assert {g["layer"] for g in ties.neighbours("Q2", skip=("wikidata", "reports"))} == {"us"}


def test_counts_match_their_lists(library):
    for label, n, url in ties.figures():
        q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
        if n >= 0:
            assert ties.count(**{k: v for k, v in q.items() if k in ("entity", "layer", "group")}) == n, label
        else:
            assert ties.others(**{k: v for k, v in q.items() if k in ("entity", "layer", "group")}) == -n, label


def test_pages(library):
    from rozvedka.app import app
    with TestClient(app) as client:
        assert "Network" in client.get("/graph").text
        page = client.get("/graph/ties?entity=Q2").text
        assert "<b>3</b> links with <b>3</b> others" in page and "Linked To: HIZBALLAH" in page
        assert client.get("/graph/ties?layer=uk").status_code == 200
        assert "Ivan PETROV is a director" in client.get("/graph/ties?q=Rostec").text
        assert "Mimikatz" in client.get("/entity/S0002").text
        r = client.get("/entity/Q2", follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == "/actors/Q2#network"
        actor = client.get("/actors/Q2").text
        assert 'id="network"' in actor and "AL-QARD FINANCE" in actor
        assert client.get("/entity/NOPE").status_code == 404 and client.get("/graph/ties?entity=NOPE").status_code == 404
