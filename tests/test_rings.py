"""Rings around one entity: who is on which ring and in which sector, what is left out and counted, and the page."""
import math

from fastapi.testclient import TestClient

from rozvedka import rings
from test_paths import network  # noqa: F401  – the same small network


def test_inner_ring_sectors_and_what_is_left_out(network):
    d = rings.rings("Q1")
    inner = {n["id"]: n for n in d["inner"]}
    assert set(inner) == {"US:1", "US:H", "S1"}                    # stated links; the country and the co-mention are left out
    assert inner["US:1"]["sector"] == "us" and inner["S1"]["sector"] == "attack"
    assert inner["US:1"]["says"] == ["linked to it"]               # as read from Evil Corp's side
    assert [s["layer"] for s in d["sectors"]] == ["us", "attack"]
    assert d["counts"]["near"] == 3 and all(s["more"] == 0 for s in d["sectors"])
    assert "Q2" not in inner and {n["id"] for n in d["outer"]} >= {"Q2"}  # the FSB is two steps away, through three neighbours
    with_all = {n["id"] for n in rings.rings("Q1", "all", countries=True)["inner"]}
    assert {"C1", "Q2"} <= with_all
    assert {n["id"] for n in rings.rings("Q1", "official")["inner"]} == {"US:1", "US:H"}
    assert rings.rings("nobody") is None


def test_outer_ring_prefers_shared_neighbours_over_hub_leaves(network):
    d = rings.rings("Q1")
    outer = d["outer"]
    q2 = next(f for f in outer if f["id"] == "Q2")
    leaf = next(f for f in outer if f["id"].startswith("US:L"))
    assert len(q2["via"]) == 3 and q2["score"] > leaf["score"]
    assert len(outer) == rings.OUTER                                # 61 candidates, 48 drawn
    assert d["counts"]["far"] == 61
    angles = sorted(f["angle"] % (2 * math.pi) for f in outer)    # evenly spaced, none on top of another
    assert min(b - a for a, b in zip(angles, angles[1:])) > 2 * math.pi / rings.OUTER * 0.99


def test_inner_ring_keeps_the_most_stated_first(network, monkeypatch):
    monkeypatch.setattr(rings, "INNER", 1)
    d = rings.rings("US:H")                                        # 62 neighbours, one drawn
    assert len(d["inner"]) == 1 and d["inner"][0]["id"] in ("Q1", "Q2")   # actors before anonymous leaves
    assert d["sectors"][0]["more"] == 61


def test_page(network):
    from rozvedka.app import app
    c = TestClient(app)
    t = c.get("/graph/rings?e=Q1").text
    assert 'class="rings"' in t and "Maksim YAKUBETS" in t and 'href="#sector-us"' in t and 'id="sector-us"' in t
    assert "/graph/path?a=Q1&amp;b=US%3A1" in t
    assert "Which “Rostec”?" in c.get("/graph/rings?e=Rostec").text
    assert "Nothing in the network" in c.get("/graph/rings?e=zzzz").text
    assert c.get("/graph/rings").status_code == 200


def test_every_number_matches_the_list_it_opens(network):
    for center in ("Q1", "US:H", "Q2"):
        d = rings.rings(center)
        assert sum(s["n"] for s in d["sectors"]) == d["counts"]["near"]
        for s in d["sectors"]:
            assert len(s["all"]) == s["n"] and sum(n["drawn"] for n in s["all"]) == s["n"] - s["more"]
        assert len(d["far"]) == d["counts"]["far"] and sum(f["drawn"] for f in d["far"]) == len(d["outer"])
