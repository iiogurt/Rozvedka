"""robots.txt: its rules are followed, and a robots.txt that cannot be read is never taken as permission."""
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
