"""The menu table covers every page, highlights the right section, and /views lists it."""
import pytest
from fastapi.testclient import TestClient

from rozvedka import collect, db, nav, series

NOT_PAGES = ("/api/", "/feed.atom", "/actor-image", "/logo", "/doc/{doc_id}/download", "/data/logs")


@pytest.fixture
def empty_library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    db.init()
    collect.init()
    from rozvedka import actors, citations, cves, techniques, topics
    for m in (topics, actors, cves, techniques, citations):
        m.init()


def test_every_page_belongs_to_a_menu_entry():
    from rozvedka.app import app
    paths = [p for p, ops in app.openapi()["paths"].items() if "get" in ops and not p.startswith(NOT_PAGES)
             and not any(x in p for x in ("/download", "/logs/"))]
    orphans = [p for p in paths if nav.locate(p.split("{")[0].rstrip("/") or "/")[0] is None]
    assert not orphans, f"pages missing from rozvedka/nav.py: {orphans}"


def test_locate_picks_the_longest_match():
    assert nav.locate("/") == ("overview", "/")
    assert nav.locate("/actors/Q1/timeline") == ("actors", "/actors")
    assert nav.locate("/actors/sanctions") == ("actors", "/actors/sanctions")
    assert nav.locate("/sources/coverage") == ("maintain", "/sources/coverage")
    assert nav.locate("/sources") == ("sources", "/sources")
    assert nav.locate("/report/12") == ("library", "/documents")
    assert nav.locate("/publisher/3") == ("sources", "/publishers")
    assert nav.locate("/trends/terms") == ("topics", "/trends/terms")
    assert nav.locate("/nowhere") == (None, None)


def test_every_menu_link_is_unique_and_answers(empty_library):
    links = [i[1] for _k, _l, _h, items in nav.GROUPS for i in items]
    assert len(links) == len(set(links))
    from rozvedka.app import app
    c = TestClient(app)
    for link in links:
        assert c.get(link).status_code == 200, link


def test_header_and_section_tabs(empty_library):
    from rozvedka.app import app
    c = TestClient(app)
    t = c.get("/cves").text
    assert 'class="rgrp on"' in t
    assert 'class="subnav sectionnav" aria-label="Actors &amp; threats"' in t and 'class="on" title="Vulnerabilities' in t
    assert "sectionnav" not in c.get("/").text
    v = c.get("/views").text
    assert 'id="maintain"' in v and "/techniques" in v


def test_every_list_page_has_a_title(empty_library):
    from rozvedka.app import app
    c = TestClient(app)
    for _k, _l, _h, items in nav.GROUPS:
        for i in items:
            if i[1] in ("/", "/map", "/map/democracy", "/map/mentions", "/feed.atom"):      # the map pages title their side panel
                continue
            assert "<h1" in c.get(i[1]).text, i[1]


def test_breadcrumbs_lead_back_from_pages_below_a_menu_entry():
    assert nav.menu("/documents")["crumbs"] == []                     # a menu page: the section tabs show where it is
    assert nav.menu("/report/12")["crumbs"] == [{"label": "Documents", "href": "/documents"}]
    assert nav.menu("/entity/x")["crumbs"] == [{"label": "Actors & threats", "href": "/actors"},
                                                {"label": "Network", "href": "/graph"}]
    assert nav.menu("/ratings/DE")["crumbs"][-1] == {"label": "Ratings", "href": "/ratings"}
    assert nav.menu("/nowhere")["crumbs"] == []


def test_map_scripts_take_their_colours_from_the_stylesheet():
    """Colours live in style.css, one set per theme (rzTokens / var(--…)); a hex colour in a map script would not follow the theme."""
    import re
    from pathlib import Path
    static = Path(nav.__file__).parent / "static"
    for name in ("map.js", "map_democracy.js", "mentions.js"):
        assert not re.findall(r"#[0-9a-fA-F]{6}\b", (static / name).read_text()), name
