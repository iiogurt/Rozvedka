"""Sanctions lists: reading the four formats, matching entries with actors by name (and the rules that keep it honest),
the actor-page section and the overview page."""
import json

import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, db, sanctions

UN = """<CONSOLIDATED_LIST><INDIVIDUALS><INDIVIDUAL><DATAID>1</DATAID><FIRST_NAME>ABDELMALEK</FIRST_NAME><SECOND_NAME>DROUKDEL</SECOND_NAME>
<UN_LIST_TYPE>Al-Qaida</UN_LIST_TYPE><REFERENCE_NUMBER>QDi.1</REFERENCE_NUMBER><LISTED_ON>2007-01-02</LISTED_ON>
<INDIVIDUAL_ALIAS><QUALITY>Good</QUALITY><ALIAS_NAME>Abu Musab Abdel Wadoud</ALIAS_NAME></INDIVIDUAL_ALIAS>
<INDIVIDUAL_ALIAS><QUALITY>Low</QUALITY><ALIAS_NAME>Droukdal Low</ALIAS_NAME></INDIVIDUAL_ALIAS></INDIVIDUAL></INDIVIDUALS>
<ENTITIES><ENTITY><DATAID>2</DATAID><FIRST_NAME>JIT</FIRST_NAME><UN_LIST_TYPE>X</UN_LIST_TYPE><REFERENCE_NUMBER>QDe.2</REFERENCE_NUMBER><LISTED_ON>2010-05-05</LISTED_ON></ENTITY>
<ENTITY><DATAID>3</DATAID><FIRST_NAME>Lashkar-e-Jhangvi</FIRST_NAME><UN_LIST_TYPE>Al-Qaida</UN_LIST_TYPE><REFERENCE_NUMBER>QDe.3</REFERENCE_NUMBER><LISTED_ON>2003-06-30</LISTED_ON></ENTITY></ENTITIES></CONSOLIDATED_LIST>"""
UK = """<Designations><Designation><DateDesignated>29/06/2012</DateDesignated><UniqueID>AFG0001</UniqueID>
<Names><Name><Name1>MOHAMMAD</Name1><Name2>HASSAN</Name2><Name6>AKHUND</Name6><NameType>Primary Name</NameType></Name>
<Name><Name6>Abu Hussein</Name6><NameType>Alias</NameType></Name></Names>
<RegimeName>The Afghanistan (Sanctions) Regulations</RegimeName><IndividualEntityShip>Individual</IndividualEntityShip></Designation></Designations>"""
OFAC = """<sdnList xmlns="x"><sdnEntry><uid>7</uid><lastName>HIZBALLAH</lastName><sdnType>Entity</sdnType>
<programList><program>SDGT</program></programList><akaList><aka><category>strong</category><lastName>ISLAMIC JIHAD ORGANIZATION</lastName></aka>
<aka><category>weak</category><lastName>PARTY OF GOD</lastName></aka></akaList></sdnEntry>
<sdnEntry><uid>8</uid><firstName>Maria</firstName><lastName>ZAKHAROVA</lastName><sdnType>Individual</sdnType><programList><program>RUSSIA-EO14024</program></programList></sdnEntry></sdnList>"""
EU = """<export xmlns="http://eu.europa.ec/fpi/fsd/export"><sanctionEntity euReferenceNumber="EU.1.2" designationDate="2020-01-15">
<regulation publicationDate="2020-01-15" entryIntoForceDate="2020-01-16" numberTitle="2020/1 (OJ L1)" programme="TERR"><publicationUrl>https://eur-lex.europa.eu/x</publicationUrl></regulation>
<subjectType code="enterprise"/><nameAlias wholeName="Asbat al-Ansar" strong="true"/></sanctionEntity></export>"""


@pytest.fixture
def lists(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(sanctions, "DIR", tmp_path / "s")
    monkeypatch.setattr(sanctions, "MATCHES", tmp_path / "s" / "matches.json")
    (tmp_path / "s").mkdir()
    for key, text in (("UN", UN), ("UK", UK), ("US", OFAC), ("EU", EU)):
        (tmp_path / "s" / sanctions.LISTS[key]["file"]).write_text(text, encoding="utf-8")
    db.init()
    actors.init()
    with db.session() as con:
        rows = [("Q1", "person", "Abdelmalek Droukdel", ["Abdelmalek Droukdel", "Abu Musab Abdel Wadoud"]),
                ("Q2", "terror", "Hezbollah", ["Hezbollah", "Islamic Jihad Organization", "Party of God"]),
                ("Q3", "terror", "Lashkar-e-Jhangvi", ["Lashkar-e-Jhangvi"]),
                ("Q4", "terror", "Jama'at Islamiyya Taawun", ["JIT"]),
                ("Q5", "person", "Mohammad Hassan Akhund", ["Mohammad Hassan Akhund", "Abu Hussein"]),
                ("Q6", "person", "Maria Zakharova", ["Maria Zakharova"]),
                ("Q7", "terror", "Asbat al-Ansar", ["Asbat al-Ansar"]),
                ("Q8", "person", "Hizballah", ["Hizballah"]),        # a person with a group's name: not matched
                ("Q9", "state", "Ministry of Foo", ["Ministry of Foo"]), ("Q10", "state", "Ministry of Foo", ["Ministry of Foo"])]
        for key, kind, label, names in rows:
            con.execute("INSERT INTO actors(key,qid,kind,label,data) VALUES(?,?,?,?,'{}')", (key, key, kind, label))
            for n in names:
                con.execute("INSERT INTO actor_names(actor_key,name,status,weak) VALUES(?,?,'used',0)", (key, n))
    return tmp_path


def test_entries_are_read(lists):
    un = list(sanctions._entries(sanctions.DIR / "un.xml", "UN"))
    assert [e["ref"] for e in un] == ["QDi.1", "QDe.2", "QDe.3"]
    assert un[0]["names"] == ["ABDELMALEK DROUKDEL", "Abu Musab Abdel Wadoud"] and un[0]["date"] == "2007-01-02"   # Low-quality alias dropped
    uk = next(sanctions._entries(sanctions.DIR / "uk.xml", "UK"))
    assert uk["name"] == "MOHAMMAD HASSAN AKHUND" and uk["date"] == "2012-06-29" and uk["primary"] == 1
    us = list(sanctions._entries(sanctions.DIR / "ofac.xml", "US"))
    assert us[0]["names"] == ["HIZBALLAH", "ISLAMIC JIHAD ORGANIZATION"] and us[0]["url"].endswith("id=7")   # weak alias dropped
    assert us[1]["name"] == "Maria ZAKHAROVA" and us[1]["type"] == "person"
    eu = next(sanctions._entries(sanctions.DIR / "eu.xml", "EU"))
    assert eu["date"] == "2020-01-15" and eu["legal"][0]["url"] == "https://eur-lex.europa.eu/x" and eu["type"] == "group"


def test_matching_rules(lists):
    out = sanctions.match({"UN": {"retrieved": "2026-10-09"}})
    assert out["entries"]["UN"] == 3
    m = json.loads((sanctions.DIR / "matches.json").read_text())["actors"]
    assert m["Q1"][0]["via"] == "name" and m["Q1"][0]["list"] == "UN"
    assert m["Q2"][0]["via"] == "alias" and m["Q2"][0]["matched"] == "ISLAMIC JIHAD ORGANIZATION"     # 'Party of God' was a weak alias
    assert "Q3" in m and "Q7" in m and "Q6" in m
    assert "Q4" not in m                      # one short word ("JIT") is too ambiguous
    assert [x["matched"] for x in m["Q5"]] == ["MOHAMMAD HASSAN AKHUND"]     # not through 'Abu Hussein': a two-word nom de guerre
    assert "Q8" not in m                      # a person is not compared with a group entry
    assert "Q9" not in m and "Q10" not in m
    assert sanctions.of_actor("Q7")[0]["legal"][0]["text"].startswith("2020/1")


def test_pages(lists):
    sanctions.match({"EU": {"retrieved": "2026-10-09"}})
    sanctions._load.cache_clear()
    from rozvedka.app import app
    client = TestClient(app)
    t = client.get("/actors/sanctions").text
    assert "Sanctions and designations" in t and 'href="/actors/Q7#sanctions"' in t
    only = client.get("/actors/sanctions?list=EU").text
    assert 'href="/actors/Q7#sanctions"' in only and 'href="/actors/Q1#sanctions"' not in only
    assert "Q8" not in client.get("/actors/sanctions?via=alias").text
    a = client.get("/actors/Q7").text
    assert 'id="sanctions"' in a and "https://eur-lex.europa.eu/x" in a and "retrieved 2026-10-09" in a
    assert 'id="sanctions"' not in client.get("/actors/Q8").text
