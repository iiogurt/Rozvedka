"""The case file: pins, the chain of every pair, connectors, the export with citations, and the page."""
from fastapi.testclient import TestClient

from rozvedka import casefile, config
from test_paths import network  # noqa: F401  – the same small network


def _setup(network, monkeypatch):
    monkeypatch.setattr(config, "DATA", network / "data")


def test_pins_and_pairs(network, monkeypatch):
    _setup(network, monkeypatch)
    assert casefile.pin("Evil Corp")["added"] == "Evil Corp"
    assert "exists" in casefile.pin("Q1")
    assert "several entities" in casefile.pin("Rostec")["error"]               # two list entries carry the name
    assert casefile.pin("US:X [US:X]", "the US entry")["added"] == "Rostec"
    casefile.pin("Federal Security Service")
    b = casefile.board()
    assert [p["id"] for p in b["pins"]] == ["Q1", "US:X", "Q2"] and b["pins"][1]["note"] == "the US entry"
    pair = b["grid"][("Q1", "Q2")]
    assert pair["steps"] == 1 and pair is b["grid"][("Q2", "Q1")]               # a co-mention is the most specific route
    assert b["grid"][("Q1", "US:X")]["chain"] is None and b["linked"] == 1        # Rostec is on an island
    casefile.unpin("US:X")
    casefile.set_note("Q1", "  a cyber gang ")
    assert [(p["id"], p["note"]) for p in casefile.board()["pins"]] == [("Q1", "a cyber gang"), ("Q2", "")]


def test_connectors_and_limit(network, monkeypatch):
    _setup(network, monkeypatch)
    for x in ("US:L1", "US:L2", "US:L3"):        # three leaves of the holding: every chain between them runs through it
        casefile.pin(x)
    b = casefile.board()
    assert [t["node"]["id"] for t in b["connectors"]] == ["US:H"] and len(b["connectors"][0]["pairs"]) == 3
    for i in range(4, 20):
        casefile.pin(f"US:L{i}")
    assert len(casefile.load()) == casefile.MAX_PINS and "at most" in casefile.pin("US:L30")["error"]


def test_export_cites_every_step(network, monkeypatch):
    _setup(network, monkeypatch)
    casefile.pin("US:1", "the banker")
    casefile.pin("Q2")
    md = casefile.markdown("http://pi:8080")
    assert "**Maksim YAKUBETS**" in md and "Note: the banker" in md
    assert "US sanctions list, entry 1 <https://x>" in md and "> Linked To: EVIL CORP" in md
    assert "http://pi:8080/graph/path?a=" in md


def test_page_and_pin_buttons(network, monkeypatch):
    _setup(network, monkeypatch)
    from rozvedka.app import app
    c = TestClient(app)
    assert "Nothing pinned yet" in c.get("/case").text
    r = c.post("/case/pin", data={"e": "Q1", "back": "/graph/rings?e=Q1"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/graph/rings?e=Q1&case=Pinned")
    assert "open the case file" in c.get(r.headers["location"]).text
    c.post("/case/pin", data={"e": "Q2"})
    t = c.get("/case").text
    assert 'class="case-grid' in t and "Federal Security Service" in t and "/case/export.md" in t
    assert "Which “Rostec”?" in c.get("/case?e=Rostec&case=x").text
    assert c.post("/case/pin", data={"e": "Q2", "back": "//evil.example"}, follow_redirects=False).headers["location"].startswith("/case?")
    ex = c.get("/case/export.md")
    assert ex.headers["content-disposition"].startswith("attachment") and "# Case file" in ex.text
    c.post("/case/clear")
    assert casefile.load() == []
    assert "📌 Pin" in c.get("/graph/rings?e=Q1").text
