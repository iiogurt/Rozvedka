"""Check the portal's counts against the lists they link to – run before a release (CLAUDE.md, traceability).

    python tools/check_links.py

For every number on the home page and the latest update on What's new, opens its Documents link and compares the list's total with the number.
Then follows every internal link on the main pages once and reports any that fail.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from rozvedka import compare, home, updates, watch  # noqa: E402
from rozvedka.app import app  # noqa: E402

PAGES = ["/", "/new", "/watch", "/compare", "/actors/review", "/data", "/documents", "/years", "/ratings", "/series", "/sources", "/topics", "/trends", "/actors", "/network", "/map", "/collect"]


def main() -> int:
    client = TestClient(app)          # no startup: the registry is not re-synced
    bad = 0
    d = home.dashboard()
    figs = home.figures(d) + updates.figures(updates.update()) + watch.figures(watch.overview())
    if d["top_actors"]:                                      # two sample comparisons: the most named actor, a rising topic
        figs += compare.figures(compare.compare(actor=d["top_actors"][0]["key"]))
    if d["rising"]["rising"]:
        figs += compare.figures(compare.compare(topic=d["rising"]["rising"][0]["key"]))
    for label, n, url in figs:
        r = client.get(url)
        m = re.search(r"<b>(\d+)</b> documents match", r.text)
        listed = int(m.group(1)) if m else None
        if listed != n:
            bad += 1
            print(f"MISMATCH {label}: shows {n}, list has {listed} – {url}")
    print(f"home, What's new, Compare, Watchlist: {len(figs)} counts checked, {bad} mismatches")
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
