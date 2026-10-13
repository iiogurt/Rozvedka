"""The menu table covers every page, highlights the right section, and /views lists it."""
from fastapi.testclient import TestClient

from rozvedka import nav

NOT_PAGES = ("/api/", "/feed.atom", "/actor-image", "/logo", "/doc/{doc_id}/download", "/data/logs")


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


def test_every_menu_link_is_unique_and_answers():
    links = [i[1] for _k, _l, _h, items in nav.GROUPS for i in items]
    assert len(links) == len(set(links))
    from rozvedka.app import app
    c = TestClient(app)
    for link in links:
        assert c.get(link).status_code == 200, link


def test_header_and_section_tabs():
    from rozvedka.app import app
    c = TestClient(app)
    t = c.get("/cves").text
    assert 'class="grp on"' in t
    assert 'class="subnav sectionnav" aria-label="Actors &amp; threats"' in t and 'class="on" title="Vulnerabilities' in t
    assert "sectionnav" not in c.get("/").text
    v = c.get("/views").text
    assert 'id="maintain"' in v and "/techniques" in v
