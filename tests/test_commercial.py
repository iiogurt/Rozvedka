"""Commercial analysts (registry publisher: commercial) – a third kind of publisher, told apart from official agencies and
think tanks in every view and count, rated by who owns them; their owners and sponsors become links of the network."""
import json
import re

import pytest
import yaml
from fastapi.testclient import TestClient

from rozvedka import app as app_module
from rozvedka import collect, db, doclist, home, publishers, ratings, series, ties, topics

PROFILES = {
    "US/Freedom House": {"funding": {"disclosure": "brackets", "evidence": "https://fh.org/funding", "checked": "2026-10-07",
                                     "governments": ["USA"]}},
    "US/Eurasia Group": {
        "ownership": {"disclosure": "none", "evidence": "https://eg.net/who", "checked": "2026-10-16", "note": "private"},
        "clients": {"disclosure": "some", "evidence": "https://w/eg", "checked": "2026-10-16"},
        "methods": {"authors": "named", "methodology": None, "evidence": "https://eg.net/tr", "checked": "2026-10-16"},
        "us_awards": ["EURASIA GROUP LTD"],
        "ties": [{"rel": "founded by", "name": "Ian Bremmer", "kind": "person", "qid": "Q5980992",
                  "evidence": "https://w/eg", "checked": "2026-10-16"},
                 {"rel": "owner of", "name": "GZERO Media", "kind": "company", "evidence": "https://w/eg", "checked": "2026-10-16"}]},
}
CHECKS = {"retrieved": "2026-10-16", "fara": {}, "eu_register": {},
          "sanctions": {"lists": {"US OFAC SDN": {"url": "https://ofac", "names": 10}}, "hits": {}},
          "identity": {"US/Eurasia Group": {"qid": "Q3274136", "wikidata": "https://www.wikidata.org/wiki/Q3274136", "revision": 7,
                                            "facts": {"funder": ["Open Society Foundations"]},
                                            "subjects": {"funder": [{"qid": "Q1140183", "label": "Open Society Foundations",
                                                                     "property": "P8324", "person": False}],
                                                         "headquarters": [{"qid": "Q60", "label": "New York City",
                                                                           "property": "P159", "person": False}]}}},
          "us_awards": {"US/Eurasia Group": {"recipients": [{"name": "EURASIA GROUP LTD", "id": "r-1", "uei": "U", "amount": 4.4e6,
                                                             "url": "https://www.usaspending.gov/recipient/r-1/latest"}],
                                             "period": ["2007-10-01", "2026-10-16"],
                                             "agencies": [{"name": "Department of Defense", "amount": 3444793.69},
                                                          {"name": "Department of Energy", "amount": 1015970.44}],
                                             "total": 4460764.13}}}
RATINGS = {"retrieved": "2026-10-16", "iso3": {}, "measures": {}, "iso2to3": {"US": "USA", "QA": "QAT"},
           "names": {"USA": "United States", "QAT": "Qatar"},
           "values": {"USA": {"vdem_regime": {"2025": 2}}, "QAT": {"vdem_regime": {"2025": 0}}}}


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    (tmp_path / "publishers.yaml").write_text(yaml.safe_dump(PROFILES))
    (tmp_path / "publishers.json").write_text(json.dumps(CHECKS))
    (tmp_path / "ratings.json").write_text(json.dumps(RATINGS))
    monkeypatch.setattr(publishers, "PROFILES", tmp_path / "publishers.yaml")
    monkeypatch.setattr(publishers, "STORE", tmp_path / "publishers.json")
    monkeypatch.setattr(ratings, "STORE", tmp_path / "ratings.json")
    publishers.load.cache_clear(); ratings.load.cache_clear()
    app_module._independent["at"] = None
    db.init()
    collect.init()
    topics.init()
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil',1)")
        con.execute("""INSERT INTO sources(id,key,country,agency,type,publisher,active)
                       VALUES(2,'US/Freedom House','US','Freedom House','think-tank','independent',1)""")
        con.execute("""INSERT INTO sources(id,key,country,agency,name_en,type,publisher,active)
                       VALUES(3,'US/Eurasia Group','US','Eurasia Group','Eurasia Group','commercial','commercial',1)""")
        for i, src in ((1, 1), (2, 1), (3, 2), (4, 3)):
            con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,local_path)
                           VALUES(?,?,?,?,'en',2023,'downloaded',?)""", (i, src, f"https://x/{i}.pdf", f"Report {i}", f"f{i}.pdf"))
    yield tmp_path
    publishers.load.cache_clear(); ratings.load.cache_clear()
    app_module._independent["at"] = None


def _write(path, data):
    path.write_text(yaml.safe_dump(data) if path.suffix == ".yaml" else json.dumps(data))
    publishers.load.cache_clear()


def test_counted_apart_from_agencies_and_think_tanks(library):
    assert doclist.count() == 4 and doclist.count(type="official") == 2
    assert doclist.count(type="think-tank") == 1 and doclist.count(type="commercial") == 1
    d = home.dashboard.__wrapped__() if hasattr(home.dashboard, "__wrapped__") else home.dashboard()
    assert d["totals"]["think_tanks"]["reports"] == 1 and d["totals"]["commercial"]["reports"] == 1
    y = next(y for y in d["years"] if y["year"] == 2023)
    assert (y["n_off"], y["n_ind"], y["n_com"]) == (2, 1, 1) and "type=commercial" in y["url_com"]


def test_marked_in_views(library):
    client = TestClient(app_module.app)
    docs = client.get("/documents").text
    assert re.search(r"◆ 1 from think tanks", docs) and re.search(r"■ 1 from commercial analysts", docs)
    assert docs.count('class="pub-ind pub-com pub-lv-') == 1 and "commercial analyst · concerns" in docs
    t = client.get("/sources").text
    assert t.index('id="independent"') < t.index('id="commercial"') and "<b>1</b> commercial analysts" in t
    assert 'class="card card-com" id="s-3"' in t and 'class="card card-ind" id="s-2"' in t
    report = client.get("/report/4").text
    assert "■ Commercial analyst – concerns" in report and "not a state agency or a think tank" in report
    page = client.get("/publisher/3").text
    assert "owners not disclosed" in page and "Ian Bremmer" in page and "USAspending: EURASIA GROUP LTD" in page
    assert "Open Society Foundations" in page and "$3,444,794" in page
    lst = client.get("/publishers").text
    assert 'id="independent"' in lst and 'id="commercial"' in lst and "transparent ownership" in lst
    assert client.get("/publisher/1").status_code == 404


def test_rating_by_ownership(library):
    p = publishers.profile("US/Eurasia Group", "commercial")
    assert p["level"] == "concerns" and p["reasons"] == ["Ownership: owners not disclosed"]
    assert {c["key"]: c["status"] for c in p["checks"]} == {
        "sanctions": "ok", "fara": "ok", "ownership": "concern", "clients": "partial", "methods": "partial",
        "us_awards": "info", "eu_register": "unknown"}
    prof = json.loads(json.dumps(PROFILES))
    prof["US/Eurasia Group"]["ownership"]["disclosure"] = "listed"
    prof["US/Eurasia Group"]["methods"]["methodology"] = "https://eg.net/method"
    prof["US/Eurasia Group"]["clients"]["disclosure"] = "none"            # usual – does not change the rating
    _write(publishers.PROFILES, prof)
    assert publishers.profile("US/Eurasia Group", "commercial")["level"] == "transparent"
    prof["US/Eurasia Group"]["ownership"]["states"] = ["QAT"]               # a stake of an autocracy's state
    _write(publishers.PROFILES, prof)
    p = publishers.profile("US/Eurasia Group", "commercial")
    assert p["level"] == "concerns" and "Qatar (closed autocracy, V-Dem 2025)" in p["reasons"][0]
    prof["US/Eurasia Group"]["ownership"] = {**prof["US/Eurasia Group"]["ownership"], "disclosure": "named", "states": []}
    _write(publishers.PROFILES, prof)
    assert publishers.profile("US/Eurasia Group", "commercial")["level"] == "partial"
    assert publishers.profile("US/Eurasia Group", "commercial")["label"] == "partly transparent"
    assert publishers.profile("US/Freedom House")["label"] == "transparent funding"           # think tanks: funding


def test_us_awards_count_only_the_named_recipients(monkeypatch):
    calls = []

    def post(url, body):
        calls.append((url.rsplit("/", 2)[-2], body["filters"]))
        if "recipient" in url and "awarding" not in url:
            return {"results": [{"name": "GRAPHIKA, INC.", "recipient_id": "g-1", "amount": 10.0},
                                {"name": "OCTANT DATA, LLC", "recipient_id": "o-1", "amount": 4293070.0}]}
        return {"results": [{"name": "Department of Defense", "amount": 7.0}, {"name": "Department of State", "amount": 3.0}]}
    monkeypatch.setattr(publishers, "_post", post)
    monkeypatch.setattr("time.sleep", lambda s: None)
    out = publishers.us_awards({"US/Graphika": ["Graphika, Inc."]}, today="2026-10-16")["US/Graphika"]
    assert [r["name"] for r in out["recipients"]] == ["GRAPHIKA, INC."]       # the loose search also found another company
    assert out["agencies"] == [{"name": "Department of Defense", "amount": 7.0}, {"name": "Department of State", "amount": 3.0}]
    assert out["total"] == 10.0 and [c[0] for c in calls] == ["recipient", "awarding_agency"]
    assert calls[1][1]["recipient_id"] == "g-1"


def test_influence_lists_every_stated_tie(library):
    got = {(t["origin"], t["rel"], t["name"]): t for t in publishers.influence("US/Eurasia Group")}
    assert set(got) == {("profile", "founded by", "Ian Bremmer"), ("profile", "owner of", "GZERO Media"),
                        ("usaspending", "received US federal contracts or grants from", "US Department of Defense"),
                        ("usaspending", "received US federal contracts or grants from", "US Department of Energy"),
                        ("wikidata", "funded by", "Open Society Foundations")}       # headquarters is not a tie
    assert got[("profile", "owner of", "GZERO Media")]["back"] == "owned by"
    assert got[("profile", "founded by", "Ian Bremmer")]["kind"] == "person"
    fh = publishers.influence("US/Freedom House")
    assert [(t["rel"], t["name"], t["iso3"]) for t in fh] == [("funded by the government of", "United States", "USA")]


def test_network_layer(library):
    actors = {"Q30": {"key": "Q30", "kind": "country", "label": "United States", "data": json.dumps({"iso": "US"})},
              "Q5980992": {"key": "Q5980992", "kind": "person", "label": "Ian Bremmer", "data": "{}"},
              "Q11209": {"key": "Q11209", "kind": "state", "label": "United States Department of Defense", "data": "{}"}}
    g = ties._Graph(actors)
    with db.session() as con:
        stats = ties._from_publishers(g, con)
    assert stats["publishers"] == 2 and stats["ties"] == 6
    assert g.entities["Q3274136"][:4] == ("commercial", "Eurasia Group", None, "publishers")
    assert json.loads(g.entities["Q3274136"][4])["publisher"] == {"source": 3, "key": "US/Eurasia Group", "kind": "commercial"}
    t = {(a, b, rel): ev for (a, b, rel, layer), (*_, ev) in g.ties.items() if layer == "publishers"}
    assert ("Q3274136", "Q5980992", "founded by") in t                  # the gazetteer's actor for the founder
    assert ("Q3274136", "Q11209", "received US federal contracts or grants from") in t      # matched by name
    assert ("Q3274136", "pub-ref:us-department-of-energy", "received US federal contracts or grants from") in t
    assert ("Q3274136", "Q1140183", "funded by") in t and g.entities["Q1140183"][3] == "wikidata"
    assert ("pub:US/Freedom House", "Q30", "funded by the government of") in t          # a donor government = its country
    ev = json.loads(t[("Q3274136", "Q11209", "received US federal contracts or grants from")])
    assert ev["origin"] == "usaspending" and ev["amount"] == 3444793.69 and ev["profile"] == "/publisher/3"


def _claim(qid, rank="normal", **qualifiers):
    return {"rank": rank, "mainsnak": {"datavalue": {"type": "wikibase-entityid", "value": {"id": qid}}},
            "qualifiers": {p: [{"datavalue": {"value": v}}] for p, v in qualifiers.items()}}


def test_wikidata_ties_hold_today():
    # past chief executives carry an end time, the current one is preferred: only that one is a tie
    claims = [_claim("Q1", "preferred", P580={"time": "+2015-05-07T00:00:00Z", "precision": 11}),
              _claim("Q2", P582={"time": "+2015-05-06T00:00:00Z", "precision": 11}), _claim("Q3"), _claim("Q4", "deprecated")]
    assert [c["mainsnak"]["datavalue"]["value"]["id"] for c in publishers._current(claims)] == ["Q1"]
    # without a preferred one: every statement that has not ended
    assert [c["mainsnak"]["datavalue"]["value"]["id"] for c in publishers._current(claims[1:])] == ["Q3"]


def test_wikidata_grant_keeps_year_amount_purpose_and_reference():
    grant = _claim("Q786194", P585={"time": "+2023-00-00T00:00:00Z", "precision": 9},
                   P2121={"amount": "+425000", "unit": "http://www.wikidata.org/entity/Q4917"},
                   P6208={"text": "to measure impunity", "language": "en"})
    grant["references"] = [{"snaks": {"P854": [{"datavalue": {"value": "https://www.opensocietyfoundations.org/grants/x"}}]}}]
    assert publishers._qualifiers(grant) == {"when": "2023", "amount": "US$425,000", "purpose": "to measure impunity",
                                             "ref": "https://www.opensocietyfoundations.org/grants/x"}
