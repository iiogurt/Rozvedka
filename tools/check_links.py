"""Check the portal's counts against the lists they link to – run before a release (CLAUDE.md, traceability).

    python tools/check_links.py

For every number on the home page, opens its Documents link and compares the list's total with the number.
Then follows every internal link on the main pages once and reports any that fail.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from rozvedka import home  # noqa: E402
from rozvedka.app import app  # noqa: E402

PAGES = ["/", "/documents", "/series", "/sources", "/topics", "/trends", "/actors", "/network", "/map", "/collect"]


def main() -> int:
    client = TestClient(app)          # no startup: the registry is not re-synced
    bad = 0
    figs = home.figures(home.dashboard())
    for label, n, url in figs:
        r = client.get(url)
        m = re.search(r"<b>(\d+)</b> documents match", r.text)
        listed = int(m.group(1)) if m else None
        if listed != n:
            bad += 1
            print(f"MISMATCH {label}: shows {n}, list has {listed} – {url}")
    print(f"home page: {len(figs)} counts checked, {bad} mismatches")
    seen, broken = set(), 0
    for page in PAGES:
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
