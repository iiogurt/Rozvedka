"""Events for the timeline (rozvedka/events.py): Wikidata items, EuRepoC cyber incidents and UCDP organised violence,
each with its source; actors linked only when they match the gazetteer unambiguously."""
import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, app as app_module, collect, db, events, series, topics
from rozvedka.sanctions import _actor_names


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    app_module._independent["at"] = None
    db.init()
    collect.init()
    topics.init()
    actors.init()
    events.init()
    with db.session() as con:
        for key, kind, label, iso in (("Q212", "country", "Ukraine", "UA"), ("Q159", "country", "Russia", "RU"),
                                      ("Q183", "country", "Germany", "DE"), ("Q96", "country", "Mexico", "MX"),
                                      ("Q1", "cyber", "APT28", None), ("Q2", "cyber", "Sandworm", None),
                                      ("Q3", "cyber", "Lazarus Group", None), ("Q4", "cyber", "Andariel", None)):
            con.execute("INSERT INTO actors(key,qid,kind,label,data,iso) VALUES(?,?,?,?,'{}',?)", (key, key, kind, label, iso))
        for key, name in (("Q1", "APT28"), ("Q1", "Fancy Bear"), ("Q2", "Sandworm"), ("Q3", "Lazarus Group"),
                          ("Q4", "Andariel"), ("Q2", "Shared Name"), ("Q3", "Shared Name")):
            con.execute("INSERT INTO actor_names(actor_key,name,status,weak) VALUES(?,?,'used',0)", (key, name))
    yield tmp_path
    app_module._independent["at"] = None


def test_names_match_the_gazetteer_unambiguously(library):
    with db.session() as con:
        names = _actor_names(con)
    written = "Fancy Bear/APT28/Sofacy/Forest Blizzard fka STRONTIUM (GRU, Unit 26165)"
    assert events._aliases(written) == ["Fancy Bear", "APT28", "Sofacy", "Forest Blizzard", "STRONTIUM"]
    assert events.resolve_name(written, names) == ("Q1", None)
    # an umbrella after '<' is not the actor itself
    assert events.resolve_name("Andariel/APT45 < Lazarus Group/HIDDEN COBRA", names) == ("Q4", None)
    assert events.resolve_name("Shared Name", names) == (None, "2 actors share these names")
    # one stray alias of another group does not hide a clear majority
    assert events.resolve_name("Sandworm/Shared Name", names) == ("Q2", "2 of 3 matching names point to it")
    assert events.resolve_name("APT28/Sandworm", names) == (None, "2 actors share these names")       # 1 vs 1: too close
    assert events.resolve_name("Fancy Bear/APT28/Shared Name", names) == ("Q1", "2 of 4 matching names point to it")
    assert events.resolve_name("Not attributed", names) == (None, "not a name")
    assert events.resolve_name("Some Crew", names) == (None, "no name in the gazetteer")


def test_eurepoc_incidents(library):
    with db.session() as con:
        names = _actor_names(con)
    rows = [{"incident_id": "7", "name": " GRU hits a ministry ", "description": "On 19 December 2024 …",
             "start_date": "19.12.2024", "end_date": "20.12.2024", "receiver_country_alpha_2_code": "UA;UA;DE",
             "initiator_name": "Fancy Bear/APT28 (GRU)", "initiator_alpha_2": "RU", "initiator_category": "State",
             "attributing_country": "Ukraine", "weighted_intensity": "4.5", "source_url": "https://news/a;https://news/b",
             "incident_type": "Disruption", "attribution_date": "19.12.2024", "settled_initiator": "True"},
            {"incident_id": "8", "name": "Hacktivists", "description": "", "start_date": "01.02.2023", "end_date": "Not available",
             "receiver_country_alpha_2_code": "DE", "initiator_name": "Unknown", "initiator_alpha_2": "RU",
             "initiator_category": "Non-state-group", "attributing_country": "Not available", "weighted_intensity": "",
             "source_url": ""},
            {"incident_id": "9", "name": "Too early", "description": "", "start_date": "01.01.1999", "end_date": "",
             "receiver_country_alpha_2_code": "DE", "initiator_name": "", "initiator_alpha_2": "", "initiator_category": "",
             "attributing_country": "", "weighted_intensity": "", "source_url": ""}]
    evs = events.parse_eurepoc(rows, names, {"RU": "Q159", "UA": "Q212", "DE": "Q183"})
    assert [e["key"] for e in evs] == ["eurepoc:7", "eurepoc:8"]               # before 2000: left out
    a, b = evs
    assert a["label"] == "GRU hits a ministry" and a["start"] == "2024-12-19" and a["end"] == "2024-12-20"
    assert a["countries"] == ["DE", "UA"] and a["url"] == "https://news/a" and a["weight"] == 4.5
    roles = {(x["role"], x["actor_key"]) for x in a["actors"]}
    assert ("initiator", "Q1") in roles and ("initiator state", "Q159") in roles
    # a non-state initiator does not make its country an initiator
    assert [(x["role"], x["actor_key"], x["reason"]) for x in b["actors"]] == [("initiator", None, "not a name")]
    assert b["url"] == events.EUREPOC_RECORD


def test_ucdp_months_and_big_events(library):
    with db.session() as con:
        names, by_name = _actor_names(con), events._country_names(con)
    base = {"type_of_violence": "1", "conflict_name": "Russia - Ukraine", "conflict_new_id": "13243", "side_a": "Government of Russia (Soviet Union)",
            "side_b": "Government of Ukraine", "dyad_name": "", "where_coordinates": "Bakhmut town", "latitude": "48.6",
            "longitude": "38.0", "low": "", "high": "", "source_headline": ""}
    base.update(event_clarity="1", date_prec="1")
    rows = [{**base, "id": "1", "country": "Ukraine", "date_start": "2023-05-01 00:00:00.000", "date_end": "2023-05-02 00:00:00.000", "best": "120"},
            {**base, "id": "2", "country": "Ukraine", "date_start": "2023-05-09 00:00:00.000", "date_end": "", "best": "3"},
            {**base, "id": "3", "country": "Russia (Soviet Union)", "date_start": "2023-05-03 00:00:00.000", "date_end": "", "best": "80",
             "type_of_violence": "3"},
            {**base, "id": "4", "country": "Mexico", "date_start": "2023-06-01 00:00:00.000", "date_end": "", "best": "60",
             "type_of_violence": "2", "side_a": "Sinaloa Cartel", "side_b": "Jalisco Cartel"},
            # UCDP's own sum of a month's losses: counted in the month, not a single event
            {**base, "id": "5", "country": "Ukraine", "date_start": "2023-07-01 00:00:00.000", "date_end": "2023-07-31 00:00:00.000",
             "best": "900", "event_clarity": "2", "date_prec": "4"}]
    months = {}
    evs = events.parse_ucdp(rows, by_name, {"UA", "MX", "DE"}, names, months=months)
    assert months[("UA", "2023-05")] == {"deaths": 123, "events": 2, "state": 123, "nonstate": 0, "onesided": 0, "preliminary": 0}
    assert months[("RU", "2023-05")]["onesided"] == 80                          # every state's months are kept
    assert [e["key"] for e in evs] == ["ucdp:1", "ucdp:4"]                     # ≥ 50 deaths, in a state of the library, one clear event
    assert months[("UA", "2023-07")]["deaths"] == 900
    ua = evs[0]
    assert ua["label"] == "Russia - Ukraine: Bakhmut town" and ua["deaths"] == 120 and ua["url"].endswith("/conflict/13243")
    assert [(a["role"], a.get("country")) for a in ua["actors"]] == [("side A", "RU"), ("side B", "UA")]
    assert evs[1]["kind"] == "non-state conflict" and evs[1]["actors"][0]["reason"] == "no name in the gazetteer"


def _item(**claims):
    def snak(v):
        if isinstance(v, dict):
            return {"mainsnak": {"datavalue": {"type": v.pop("_type"), "value": v}}, "rank": "normal"}
        return {"mainsnak": {"datavalue": {"type": "wikibase-entityid", "value": {"id": v}}}, "rank": "normal"}
    return {"labels": {"en": {"value": "Attack"}}, "descriptions": {"en": {"value": "an attack"}},
            "claims": {p: [snak(v) for v in vs] for p, vs in claims.items()}}


def test_wikidata_items_and_stated_relations(library):
    t = lambda d: {"_type": "time", "time": f"+{d}T00:00:00Z", "precision": 11}
    ent = _item(P585=[t("2017-06-27")], P17=["Q212"], P8031=["Q2"], P828=["Q100"], P1542=["Q200"], P361=["Q300"],
                P1120=[{"_type": "quantity", "amount": "+3"}])
    e = events.parse_item("Q50", ent, "cyberattack", 40)
    assert events._label({"labels": {"uk": {"value": "Удар по Києву"}}}) == "Удар по Києву"   # no English label: another language
    # a decade or century is no date: '+2020' with precision 8 is the 2020s
    assert events._date({"time": "+2020-00-00T00:00:00Z", "precision": 8}) is None
    assert events._date({"time": "+2014-02-20T00:00:00Z", "precision": 11}) == "2014-02-20"
    assert e["start"] == e["end"] == "2017-06-27" and e["deaths"] == 3 and e["weight"] == 40
    assert e["actors"] == [("perpetrator", "Q2")]
    # cause → effect whichever item states it; the part points to its whole
    assert {(l["src"], l["rel"], l["dst"]) for l in e["links"]} == {("Q100", "caused", "Q50"), ("Q50", "caused", "Q200"),
                                                                   ("Q50", "part of", "Q300")}


def test_stored_and_listed(library):
    e = events.parse_item("Q50", _item(P585=[{"_type": "time", "time": "+2017-06-27T00:00:00Z", "precision": 11}], P17=["Q212"],
                                       P8031=["Q2"], P1542=["Q200"]), "cyberattack", 40)
    e["countries"] = ["UA"]
    e["actors"] = [{"role": "perpetrator", "name": "Sandworm", "qid": "Q2", "actor_key": "Q2", "reason": None}]
    for l in e["links"]:
        l["src_label"], l["dst_label"] = "NotPetya", "Maersk outage"
    with db.session() as con:
        events._store(con, [e], "wikidata")
        events._meta(con, "wikidata", 1, "test")
    total, rows = events.listing(0, 10, country="UA")
    assert total == 1 and rows[0]["actors"][0]["actor_key"] == "Q2" and rows[0]["links"][0]["dst"] == "Q200"
    assert events.listing(0, 10, country="DE")[0] == 0
    assert events.listing(0, 10, actor="Q2")[0] == 1
    client = TestClient(app_module.app)
    t = client.get("/events?country=UA").text
    assert "<b>Attack</b>" in t
    assert 'href="/actors/Q2"' in t and "→ caused <b>Maersk outage</b>" in t and "Wikidata P1542" in t
    assert 'href="/events"' in client.get("/views").text


def test_timeline_lanes_and_strips(library):
    e = events.parse_item("Q50", _item(P585=[{"_type": "time", "time": "+2017-06-27T00:00:00Z", "precision": 11}]), "cyberattack", 40)
    e["countries"] = ["UA"]
    e["actors"] = [{"role": "perpetrator", "name": "Sandworm", "qid": "Q2", "actor_key": "Q2", "reason": None}]
    small = {**e, "key": "Q51", "weight": 2, "actors": [], "links": []}
    with db.session() as con:
        events._store(con, [e, small], "wikidata")
        con.execute("INSERT INTO event_months VALUES('UA','2017-06',120,3,120,0,0,0)")
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(1,'DE/BfV','DE','BfV','intelligence-civil',1)")
        con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,local_path)
                       VALUES(1,1,'https://x/1.pdf','Report','en',2018,'downloaded','f1.pdf')""")
        con.execute("INSERT INTO doc_index(doc_id, taxonomy_hash) VALUES(1, 't')")
        con.execute("INSERT INTO doc_actors(doc_id,actor_key,hits) VALUES(1,'Q2',3)")
    assert events.parse_lanes(["country:ua", "actor:Q2", "bogus:1", "country:UA", "actor:x;drop"]) == [("country", "UA"), ("actor", "Q2")]
    assert events.ranks() == {"Q51": 0.0, "Q50": 1.0}                     # heaviest of its own source = 1
    d = events.timeline([("country", "UA"), ("actor", "Q2")])
    assert [(l["id"], l["label"], l["events"]) for l in d["lanes"]] == [("country:UA", "Ukraine", 2), ("actor:Q2", "Sandworm", 1)]
    assert {i["id"] for i in d["items"]} == {"country:UA|Q50", "country:UA|Q51", "actor:Q2|Q50"}
    assert d["strips"]["country:UA"]["deaths"] == {"2017-06": {"n": 120, "preliminary": 0}}
    # each year of the report strip opens the list it counts
    from rozvedka import doclist
    rp = d["strips"]["actor:Q2"]["reports"]
    assert rp == {"2018": {"n": 1, "url": "/documents?actor=Q2&indexed=1&year=2018"}}
    assert doclist.count(actor="Q2", indexed=1, year="2018") == 1
    client = TestClient(app_module.app)
    assert client.get("/api/timeline?lane=actor:Q2").json()["lanes"][0]["label"] == "Sandworm"
    assert client.get("/api/timeline/event/Q50").json()["actors"][0]["actor_key"] == "Q2"
    assert client.get("/api/timeline/event/Q999").status_code == 404
    t = client.get("/timeline").text
    assert "vis-timeline-graph2d.min.js" in t and "timeline.js" in t and 'data-lanes="country:UA,country:RU' in t
