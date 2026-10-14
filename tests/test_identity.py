"""One target on several sanctions lists, and the details list entries share: parsing, the merge rules, the graph."""
import json
import xml.etree.ElementTree as ET

import pytest

from rozvedka import actors, collect, db, identity, sanctions, series, techniques, ties


def test_dates_numbers_contacts():
    assert identity.dob("10 Dec 1948") == "1948-12-10" and identity.dob("12/03/1960") == "1960-03-12"
    assert identity.dob("dd/mm/1945") == "1945" and identity.dob("circa 1970") == "1970" and identity.dob("") == ""
    assert identity.imo("IMO 9187629") == identity.imo("IMO9187629") == "9187629" and identity.number("P-0458 1926") == "P04581926"
    assert identity._phones("+41 22 320 88 36; +41 22 320 74 00") == ["41223208836", "41223207400"]
    assert identity._phones("-103495") == []
    assert identity._web("https://www.Ghu.by/about") == "ghu.by" and identity._web("https://vk.com/club123") == "vk.com/club123"
    assert identity._web("t.me") == ""                      # a platform without an account says nothing
    assert identity._address("Moscow", "", "Russia") is None
    assert identity._address("1 Okhotny Ryad str", "Moscow", "Russia")["street"] == "1 Okhotny Ryad str"
    assert identity.bare("PUBLIC JOINT STOCK COMPANY SOVCOMFLOT") == identity.bare("PAO Sovcomflot") == "sovcomflot"


def test_details_of_each_list():
    us = ET.fromstring("""<sdnEntry><uid>1</uid><idList><id><idType>Passport</idType><idNumber>P 04581926</idNumber><idCountry>Russia</idCountry></id>
      <id><idType>Digital Currency Address - XBT</idType><idNumber>1AbcWallet</idNumber></id>
      <id><idType>Vessel Registration Identification</idType><idNumber>IMO 9187629</idNumber></id></idList>
      <dateOfBirthList><dateOfBirthItem><dateOfBirth>10 Dec 1948</dateOfBirth></dateOfBirthItem></dateOfBirthList>
      <addressList><address><address1>7 Rue de la Paix</address1><city>Geneva</city><country>Switzerland</country></address></addressList></sdnEntry>""")
    d = identity.details(us, "US")
    assert d["ids"] == [["passport", "P04581926", "Russia"], ["imo", "9187629", ""]] and d["wallets"] == ["1AbcWallet"]
    assert d["dob"] == ["1948-12-10"] and d["addresses"][0]["city"] == "Geneva"
    uk = ET.fromstring("""<Designation><UNReferenceNumber>QDi.001</UNReferenceNumber><DOB>dd/mm/1960</DOB>
      <BusinessRegistrationNumber>(INN): 7704734000/770301001 (Russia)</BusinessRegistrationNumber>
      <CurrentOwnerOperator>PAO Sovcomflot</CurrentOwnerOperator><EmailAddress>Info@Example.org</EmailAddress></Designation>""")
    d = identity.details(uk, "UK")
    assert d["un"] == "QDi.001" and d["dob"] == ["1960"] and d["ids"] == [["registration", "7704734000", ""]]
    assert d["owners"] == ["PAO Sovcomflot"] and d["emails"] == ["info@example.org"]


def _e(names, type_="person", **det):
    base = {"dob": [], "ids": [], "addresses": [], "emails": [], "webs": [], "phones": [], "wallets": [], "un": "",
            "parents": [], "subsidiaries": [], "owners": []}
    return {"names": names, "name": names[0], "type": type_, "details": {**base, **det}}


def test_merge_rules():
    entries = {
        "UN:QDi.001": _e(["ABU EXAMPLE"]), "UK:AQD1": _e(["Abu EXAMPLE"], un="QDi.001"),       # the list says so
        "EU:1": _e(["Ivan Petrov"], dob=["1960-01-02"]), "US:1": _e(["PETROV, Ivan", "Ivan PETROV"], dob=["1960-01-02"]),
        "US:2": _e(["Ivan Petrov"], dob=["1970-05-05"]),                                     # same name, other birthday
        "EU:2": _e(["Ali Hassan"], dob=["1977"]), "UK:2": _e(["Ali Hassan"], dob=["1977"]),   # two words, a year: not enough
        "EU:3": _e(["Wan Kuok Koi"], ids=[["passport", "31135083", ""]]), "UK:3": _e(["Kuok-Koi WAN"], ids=[["passport", "31135083", ""]]),
        "US:3": _e(["Someone Else"], ids=[["passport", "31135083", ""]]),                    # same number, no shared name word
        "EU:4": _e(["Arfa Paint Company", "Yasa Part"], "group"), "EU:5": _e(["Arfeh Company", "Yasa Part"], "group"),
        "UK:5": _e(["Yasa Part"], "group"),                                                  # an alias two EU entries share
        "EU:6": _e(["Hamcho International"], "group"), "UK:6": _e(["HAMCHO INTERNATIONAL"], "group"),
        "UK:7": _e(["Al Ghurair Trading"], "group"), "US:7": _e(["AL GHURAIR TRADING"], "group"),
    }
    root, reasons = identity.clusters(entries, {"UK:7": "Q1", "US:7": "Q2"})
    same = lambda a, b: root[a] == root[b]                                                    # noqa: E731
    assert same("UN:QDi.001", "UK:AQD1") and same("EU:1", "US:1") and not same("US:1", "US:2")
    assert not same("EU:2", "UK:2")
    assert same("EU:3", "UK:3") and not same("UK:3", "US:3")
    assert not (same("EU:4", "UK:5") and same("EU:5", "UK:5"))                              # at most one entry of each list
    assert same("EU:6", "UK:6")
    assert not same("UK:7", "US:7")                                                          # two different actors
    why = [w for v in reasons.values() for _, _, w in v]
    assert "the UK entry gives the UN reference QDi.001" in why and "same name and date of birth 1960-01-02" in why
    assert "same passport number 31135083" in why


def test_detail_nodes_only_when_shared():
    entries = {"US:1": _e(["A Co"], "group", emails=["x@y.org"], wallets=["1Abc"]), "UK:1": _e(["B Co"], "group", emails=["x@y.org"]),
               "EU:1": _e(["C Co"], "group", wallets=["1Abc"])}
    root = {"US:1": "US:1", "UK:1": "UK:1", "EU:1": "US:1"}                                  # EU:1 is the same target as US:1
    nodes = {n[1]: n for n in identity.detail_nodes(entries, root)}
    assert set(nodes) == {"email"} and [k for k, _ in nodes["email"][3]] == ["UK:1", "US:1"]


OFAC = """<sdnList xmlns="x">
<sdnEntry><uid>1</uid><firstName>Ivan</firstName><lastName>PETROV</lastName><sdnType>Individual</sdnType>
  <dateOfBirthList><dateOfBirthItem><dateOfBirth>02 Jan 1960</dateOfBirth></dateOfBirthItem></dateOfBirthList>
  <idList><id><idType>Email Address</idType><idNumber>office@front.example</idNumber></id></idList></sdnEntry>
<sdnEntry><uid>2</uid><lastName>FRONT TRADING LLC</lastName><sdnType>Entity</sdnType>
  <idList><id><idType>Email Address</idType><idNumber>office@front.example</idNumber></id></idList></sdnEntry>
</sdnList>"""
UK = """<Designations>
<Designation><UniqueID>RUS1</UniqueID><IndividualEntityShip>Individual</IndividualEntityShip><DOB>02/01/1960</DOB>
  <Names><Name><Name1>Ivan</Name1><Name6>PETROV</Name6><NameType>Primary Name</NameType></Name></Names></Designation>
<Designation><UniqueID>RUS2</UniqueID><IndividualEntityShip>Ship</IndividualEntityShip><IMONumber>IMO9187629</IMONumber>
  <CurrentOwnerOperator>PAO Front Trading</CurrentOwnerOperator>
  <Names><Name><Name6>OCEAN STAR</Name6><NameType>Primary Name</NameType></Name></Names></Designation>
</Designations>"""


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
    (tmp_path / "s" / "ofac.xml").write_text(OFAC, encoding="utf-8")
    (tmp_path / "s" / "uk.xml").write_text(UK, encoding="utf-8")
    (tmp_path / "s" / "matches.json").write_text(json.dumps({"actors": {}}))
    db.init()
    collect.init()
    actors.init()
    ties.build()
    return tmp_path


def test_graph_merges_and_shares(library):
    petrov = ties.entity("UK:RUS1") or ties.entity("US:1")
    assert petrov and {m["list"] for m in petrov["data"]["members"]} == {"UK", "US"}
    assert petrov["data"]["why"][0][2] == "same name and date of birth 1960-01-02"
    with db.session() as con:
        rows = {(r["a"], r["b"], r["layer"], r["rel"]) for r in con.execute("SELECT * FROM ties")}
    email = next(b for a, b, layer, rel in rows if layer == "ids")
    assert {a for a, b, layer, rel in rows if b == email} == {petrov["id"], "US:2"}              # the shared e-mail joins them
    assert ("UK:RUS2", "US:2", "uk", "owned or operated by") in rows                           # "PAO Front Trading" = FRONT TRADING LLC
    assert ties.meta()["stats"]["ids"]["targets_merged"] == 1
