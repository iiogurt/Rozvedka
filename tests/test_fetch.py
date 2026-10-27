"""robots.txt: its rules are followed, and a robots.txt that cannot be read is never taken as permission. Rendering
JavaScript-built pages: Firefox first, Chromium only without it, robots.txt checked before either starts."""
import httpx
import pytest

from rozvedka import fetch


@pytest.fixture
def robots(monkeypatch):
    """allowed() with a fake site: answers[host] is a robots.txt status and body, or an exception to raise."""
    answers = {}
    monkeypatch.setattr(fetch, "_robots", {})
    monkeypatch.setattr(fetch, "_unreadable", {})

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, timeout=None):
            got = answers[httpx.URL(url).host]
            if isinstance(got, Exception):
                raise got
            return httpx.Response(got[0], text=got[1], request=httpx.Request("GET", url))

    monkeypatch.setattr(fetch, "_client", lambda lenient: Client())
    monkeypatch.setattr(fetch, "_curl", lambda url, dest, lenient: (_ for _ in ()).throw(RuntimeError("curl exit 28: ")))
    return answers


def test_rules_followed(robots):
    robots["a.org"] = (200, "User-agent: *\nDisallow: /private/\n")
    assert fetch.allowed("https://a.org/report.pdf") and not fetch.allowed("https://a.org/private/x.pdf")
    assert str(fetch.blocked("https://a.org/private/x.pdf")) == "blocked by robots.txt"


def test_no_robots_file_means_no_rules(robots):
    robots["b.org"] = (404, "not found")
    assert fetch.allowed("https://b.org/anything.pdf")


@pytest.mark.parametrize("answer", [(503, "busy"), httpx.ConnectTimeout("timed out")])
def test_unreadable_robots_means_nothing_is_fetched(robots, answer):
    robots["c.org"] = answer
    assert not fetch.allowed("https://c.org/report.pdf")
    assert str(fetch.blocked("https://c.org/report.pdf")).startswith("robots.txt could not be read (")
    with pytest.raises(fetch.Blocked):
        fetch.get("https://c.org/report.pdf")


@pytest.fixture
def browsers(monkeypatch):
    """render() with stand-in browsers that record which one was asked."""
    used = []
    monkeypatch.setattr(fetch, "_wait", lambda host: None)
    monkeypatch.setattr(fetch, "_firefox", lambda url, budget: used.append("firefox") or fetch.Response(url, 200, "text/html", b"<a>"))
    monkeypatch.setattr(fetch, "_chromium", lambda url, budget: used.append("chromium") or fetch.Response(url, 200, "text/html", b"<a>"))
    return used


def test_render_prefers_firefox(robots, browsers, monkeypatch):
    robots["d.org"] = (404, "")
    monkeypatch.setattr(fetch, "FIREFOX", "/usr/bin/firefox")
    monkeypatch.setattr(fetch, "CHROMIUM", "/usr/bin/chromium")
    fetch.render("https://d.org/list")
    monkeypatch.setattr(fetch, "FIREFOX", None)
    fetch.render("https://d.org/list")
    assert browsers == ["firefox", "chromium"]


def test_render_respects_robots_and_needs_a_browser(robots, browsers, monkeypatch):
    robots["e.org"] = (200, "User-agent: *\nDisallow: /\n")
    monkeypatch.setattr(fetch, "FIREFOX", "/usr/bin/firefox")
    with pytest.raises(fetch.Blocked):
        fetch.render("https://e.org/list")
    monkeypatch.setattr(fetch, "FIREFOX", None)
    monkeypatch.setattr(fetch, "CHROMIUM", None)
    with pytest.raises(RuntimeError, match="no firefox or chromium"):
        fetch.render("https://e.org/list")
    assert browsers == []
