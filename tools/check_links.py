"""Check the portal's counts against the lists they link to – run before a release (CLAUDE.md, traceability).

    python tools/check_links.py

For every number on the home page and the latest update on What's new, opens its Documents link and compares the list's total with the number;
the same for the Network page's numbers and their lists of links.
Then follows every internal link on the main pages once and reports any that fail.
"""
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("ROZVEDKA_ALLOWED_HOSTS", "testserver")   # the host name of FastAPI's test client
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from rozvedka import briefings, citations, compare, cves, gaps, home, leads, techniques, ties, twins, updates, watch  # noqa: E402
from rozvedka.app import app  # noqa: E402

PAGES = ["/", "/new", "/watch", "/compare", "/actors/review", "/data", "/documents", "/years", "/ratings", "/publishers", "/series", "/sources", "/topics", "/trends", "/actors", "/network", "/graph", "/graph/path?a=Evil+Corp&b=Federal+Security+Service", "/graph/twins", "/graph/leads", "/graph/brokers", "/map", "/map/democracy", "/collect", "/countries", "/topics/ransomware", "/countries/DE", "/sources/grid", "/citations", "/citations?by=country", "/techniques", "/cves"]


def main() -> int:
    client = TestClient(app)          # no startup: the registry is not re-synced
    bad = 0
    d = home.dashboard()
    figs = home.figures(d) + updates.figures(updates.update()) + watch.figures(watch.overview())
    if d["top_actors"]:                                      # two sample comparisons: the most named actor, a rising topic
        figs += compare.figures(compare.compare(actor=d["top_actors"][0]["key"]))
    if d["rising"]["rising"]:
        figs += compare.figures(compare.compare(topic=d["rising"]["rising"][0]["key"]))
    figs += briefings.figures("ransomware", "DE") + briefings.figures("war-in-ukraine", "EE")      # two sample briefings
    figs += gaps.figures()                                                                        # every cell of the coverage grid
    figs += citations.figures()                                                                   # Citations: type flows and both matrices
    figs += techniques.figures() + cves.figures()                                                 # ATT&CK grid, CVE lag bars
    for label, n, url in figs:
        r = client.get(url)
        m = re.search(r"<b>(\d+)</b> documents match", r.text)
        listed = int(m.group(1)) if m else None
        if listed != n:
            bad += 1
            print(f"MISMATCH {label}: shows {n}, list has {listed} – {url}")
    print(f"home, What's new, Compare, Watchlist, briefings, grid, citations, ATT&CK, CVEs: {len(figs)} counts checked, {bad} mismatches")
    net = ties.figures() + [f for f in leads.figures() if f[1] < 0]    # a negative number counts other entities ("with N others")
    for label, n, url in net:
        m = re.search(r"<b>(\d+)</b> links(?: with <b>(\d+)</b> others)?", client.get(url).text)
        listed = (int(m.group(2) or 0) if n < 0 else int(m.group(1))) if m else None
        if listed != abs(n):
            bad += 1
            print(f"MISMATCH {label}: shows {abs(n)}, list has {listed} – {url}")
    for label, n, url in twins.figures():
        m = re.search(r"share <b>(\d+)</b> techniques and <b>(\d+)</b> programs", client.get(url).text)
        listed = int(m.group(1)) + int(m.group(2)) if m else None
        if listed != n:
            bad += 1
            print(f"MISMATCH {label}: shows {n}, pair page has {listed} – {url}")
        net.append((label, n, url))
    for label, n, url in [f for f in leads.figures() if f[1] >= 0]:
        m = re.search(r"share <b>(\d+)</b> counted neighbours", client.get(url).text)
        if (int(m.group(1)) if m else None) != n:
            bad += 1
            print(f"MISMATCH {label}: shows {n}, lead page has {m and m.group(1)} – {url}")
        net.append((label, n, url))
    print(f"Network, Toolkit twins, Leads, Brokers: {len(net)} counts checked")
    seen, broken = set(), 0
    # one report page as well: the first report on the home page
    sample = re.search(r'href="(/report/\d+)"', client.get("/").text)
    for page in PAGES + ([sample.group(1)] if sample else []):
        for href in re.findall(r'href="(/[^"#]*)"', client.get(page).text):
            href = href.replace("&amp;", "&")
            if href in seen or href.startswith(("/static/", "/doc/", "/logo/")):
                continue
            seen.add(href)
            code = client.get(href, follow_redirects=True).status_code
            if code != 200:
                broken += 1
                print(f"BROKEN {code} {href} (on {page})")
    print(f"links: {len(seen)} internal links followed, {broken} broken")
    return 1 if bad or broken else 0


if __name__ == "__main__":
    sys.exit(main())
