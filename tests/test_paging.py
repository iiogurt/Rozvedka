"""The shared pager: page window, clamping, links that keep the filters, page-size choice."""
from urllib.parse import parse_qs, urlsplit

from rozvedka.paging import PER_PAGE_CHOICES, page_offset, paginate, per_page_of


def q(href):
    return parse_qs(urlsplit(href).query)


def test_window_with_gaps():
    p = paginate(2937, 7, 100, "/", {})
    assert [i["n"] for i in p["numbers"]] == [1, None, 5, 6, 7, 8, 9, None, 30]
    assert [i["n"] for i in p["numbers"] if i["current"]] == [7]
    assert (p["first"], p["last"], p["pages"], p["offset"]) == (601, 700, 30, 600)


def test_clamping_and_bad_input():
    assert paginate(250, 99, 100, "/", {})["page"] == 3                 # past the end → last page
    assert paginate(250, "x", 100, "/", {})["page"] == 1
    assert paginate(0, 1, 100, "/", {})["pages"] == 1 and paginate(0, 1, 100, "/", {})["first"] == 0
    assert page_offset(250, 99, 100) == 200
    assert per_page_of("50") == 50 and per_page_of("7") == 100 and per_page_of(None, 25) == 25


def test_links_keep_filters_and_omit_defaults():
    p = paginate(500, 2, 50, "/", {"country": "CZ", "topic": ["russia", "china"], "page": 2, "per_page": 50, "q": ""})
    assert q(p["next"]) == {"country": ["CZ"], "topic": ["russia", "china"], "page": ["3"], "per_page": ["50"]}
    assert q(p["prev"]) == {"country": ["CZ"], "topic": ["russia", "china"], "per_page": ["50"]}   # page 1 omitted
    sizes = {c["n"]: q(c["href"]) for c in p["choices"]}
    assert sizes[100] == {"country": ["CZ"], "topic": ["russia", "china"]}                       # default omitted
    assert [c["n"] for c in p["choices"]] == list(PER_PAGE_CHOICES)
    assert p["first_href"] and p["last_href"] and q(p["last_href"])["page"] == ["10"]


def test_passages_default_and_anchor():
    p = paginate(60, 1, 25, "/actors/Q1", {}, anchor="#passages", default=25)
    assert p["next"] == "/actors/Q1?page=2#passages"
    assert q(p["choices"][2]["href"].split("#")[0])["per_page"] == ["100"]
