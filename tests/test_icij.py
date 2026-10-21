"""ICIJ Offshore Leaks: matching listed companies and people to leaked records, the review of people, the network layer."""
import json

from rozvedka import icij, ties


def node(name, cs, kind="officer", source="Panama Papers"):
    return {"name": name, "kind": kind, "countries": cs, "jurisdiction": "", "source": source, "valid": "", "incorporated": "", "status": ""}


def test_companies_need_a_distinctive_name_in_the_country():
    orgs = {"ledra nominees limited": {"US:1"}, "orion limited": {"US:2"}, "isi maritime limited": {"US:3"}}
    where = {"US:1": {"CY"}, "US:2": {"RU"}, "US:3": {"MT"}}
    nodes = {"1": node("LEDRA NOMINEES LIMITED", ["CY"], "entity"), "2": node("Ledra Nominees Limited", ["CY"], "entity"),
             "3": node("ISI MARITIME LIMITED", ["MT"], "entity"), "4": node("ISI MARITIME LIMITED", ["PA"], "entity")}
    m = icij.match({}, {k: v for k, v in orgs.items() if k != "orion limited"}, where, nodes)
    assert m == {"US:1": {"nodes": ["1", "2"], "how": "company"}}         # the same company in two leaks; ISI also in Panama: not sure


def test_people_need_a_rare_name_in_the_country():
    people = {"marian kocner": {"US:1"}, "zhang wei long": {"US:2"}, "darren debono": {"US:3"}}
    where = {"US:1": {"SK"}, "US:2": {"CN"}, "US:3": {"MT"}}
    nodes = {"1": node("MARIAN KOCNER", ["SK"]), **{f"z{i}": node("ZHANG WEI LONG", ["CN"]) for i in range(5)},
             "d": node("DARREN DEBONO", ["GB"])}
    m = icij.match(people, {}, where, nodes)
    assert m == {"US:1": {"nodes": ["1"], "how": "person"}}               # five Zhang Wei Longs; Debono's record is elsewhere
    assert icij.node_kind(node("BEARER 1", [])) == "org" and icij.node_kind(node("ANNA MARIA SMITH", [])) == "person"
    assert icij.countries("RUS;CYP") >= set() and isinstance(icij.countries(""), set)


def test_people_are_linked_only_once_confirmed(tmp_path, monkeypatch):
    st = {"meta": {"retrieved": "2026-10-21"}, "matches": {"US:1": {"nodes": ["1"], "how": "person"},
                                                          "US:2": {"nodes": ["2"], "how": "company"}},
          "nodes": {"1": node("MARIAN KOCNER", ["SK"]), "2": node("SEABRASS LIMITED", ["MT"], "entity"),
                    "3": node("ALPHA CORP LTD", ["VG"], "entity"), "4": node("JOHN SMITH", ["MT"])},
          "edges": [{"a": "1", "b": "3", "rel": "shareholder of", "start": "23-MAR-2006", "end": "", "source": "Panama Papers"},
                    {"a": "4", "b": "2", "rel": "Director of", "start": "", "end": "", "source": "Paradise Papers"}]}
    monkeypatch.setattr(icij, "stored", lambda: st)
    monkeypatch.setattr(icij, "REVIEWS", tmp_path / "icij_reviews.yaml")
    assert set(icij.accepted()) == {"US:2"}

    def build():
        g = ties._Graph({})
        g.node("US:1", "person", "Marian KOCNER", "us", {})
        g.node("US:2", "org", "SEABRASS LIMITED", "us", {})

        class T:
            root = {"US:1": "US:1", "US:2": "US:2"}

            def node(self, k):
                return k
        g.targets = T()
        return g, ties._from_icij(g)
    g, st1 = build()
    assert st1 == {"matched": 1, "links": 1, "nodes": 1}
    (t,) = g.ties.values()
    assert t[:5] == ["icij:4", "US:2", "director of", "has as director", "icij"]
    assert json.loads(g.entities["US:1"][4])["icij"][0]["how"] == "unconfirmed"     # shown, not linked
    assert icij.record("US:2", "confirmed")["error"] and icij.record("US:1", "maybe")["error"]
    assert icij.record("US:1", "confirmed", "the Slovak businessman")["ok"]
    g, st2 = build()
    assert st2["matched"] == 2 and any(v[:3] == ["US:1", "icij:3", "shareholder of"] and v[5] == "2006-03-23" for v in g.ties.values())
    assert icij.reviews()["US:1"]["note"] == "the Slovak businessman"
