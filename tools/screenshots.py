"""Retake the README screenshots (docs/images/*.png) from a running portal, in the dark theme, 1280 px wide.

    .venv/bin/python -m rozvedka serve --host 127.0.0.1 --port 8091 &      # a second portal on the same library
    python3 tools/screenshots.py                    # every shot
    python3 tools/screenshots.py report ratings    # only these
    python3 tools/screenshots.py --base http://127.0.0.1:8080

Drives headless Chromium over the DevTools protocol (needs `chromium` and the `websockets` package, which comes with
uvicorn[standard]). Agency logos are removed before every shot – they are the agencies' marks and are not committed – and the machine's
home folder is shown as /home/user (the folder picker and job logs would otherwise show the account name).
The data-exchange shots need a job: start an export (data-export, taken while it runs) or a "Check and compare" of a
dataset (data-import, taken when the check is done) on /data, then take that shot alone. Every other shot is plain.
"""
import asyncio
import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websockets

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
PORT = 9333
NO_LOGOS = 'document.querySelectorAll(\'img[src^="/logo/"], .logo-sm\').forEach((e) => e.remove()); 1'
# the folder picker and job logs show the machine's home folder: the pictures say /home/user instead
NO_HOME = r"""(() => { const re = /\/home\/(?!user\b)[^\/\s'"]+/g;   // not "user": that would loop
  const clean = () => {
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n; (n = w.nextNode());) if (n.nodeValue.search(re) >= 0) n.nodeValue = n.nodeValue.replace(re, "/home/user");
  };
  clean();
  new MutationObserver(clean).observe(document.body, { childList: true, subtree: true, characterData: true });
  return 1; })()"""
WAGNER, CHINA = "Q36597284", "Q148"

# name: (path, height, steps, clip_from) – steps: ("eval", js) | ("type", text) | ("sleep", s); clip_from: a CSS
# selector the picture starts at (its section), else the top of the page
SHOTS = {
    "home": ("/", 1250, [], None),
    "home-search": ("/", 640, [("eval", "document.getElementById('hq').focus(); 1"), ("type", "wagn"), ("sleep", 3)], None),
    "new": ("/new", 1300, [], None),
    "watch": ("/watch", 1300, [], None),
    "compare": (f"/compare?actor={WAGNER}", 1300, [], None),
    "cross-language": ("/documents?q=Drohne", 900, [("eval", "document.querySelector('.xl-names').open = true; 1")], None),
    "doc-works": ("/documents?country=CH&type=intelligence-civil", 760, [], None),
    "doc-types": ("/documents?doc_type=all&country=GB", 900, [], None),
    "years": ("/years?kind=stamp", 1000, [], None),
    "report": ("/report/2964", 1250, [], None),
    "sources-independent": ("/sources", 1000, [("eval", "document.querySelectorAll('section.country[id^=\"c-\"], "
                                                       "h2.region:not(.region-ind), .flagbar, .coalition-filter')"
                                                       ".forEach((e) => e.style.display = 'none'); 1")], None),
    "think-tanks": ("/publishers", 1000, [], None),
    "ratings": ("/ratings?sort=change", 900, [], None),
    "ratings-security": ("/ratings?group=security", 900, [], None),      # security measures with their places
    "ratings-country": ("/ratings/DE", 1300, [], None),                  # one state: a chart per measure
    "series": ("/series/e64e96b2", 1200, [], None),
    "collect": ("/collect", 1100, [], None),
    "topics": ("/topics", 1100, [], None),
    "terms": ("/trends/terms?term=drone&term=ransomware&term=disinformation", 1000, [("sleep", 4)], None),
    "matrix": ("/trends/matrix", 1000, [("sleep", 5)], None),
    "matrix-lift": ("/trends/matrix?mx=lift", 1000, [("sleep", 5)], None),   # over-emphasis against all reports
    "actor-search": ("/actors", 760, [("eval", "document.getElementById('ac-q').focus(); 1"), ("type", "prigozin"),
                                      ("sleep", 2)], None),
    "actor-precision": ("/actors", 470, [], None),                 # the measured precision above the list
    "actor": ("/actors/Q7747", 1200, [("sleep", 3)], None),        # a profile with a photo and facts
    "connections": (f"/actors/{WAGNER}", 900, [("sleep", 3)], "#connections"),
    "actor-timeline": ("/actors/Q38799/timeline", 1300, [], None),   # Hamas: agencies, countries, neighbours
    "attributions": ("/actors/Q20757678", 900, [("sleep", 3)], "#attributions"),   # APT28: statements of the UK NCSC
    "cves": ("/cves", 900, [], None),                                  # CVE numbers named in reports, with CISA's list
    "cve": ("/cves/CVE-2021-26855", 1000, [], None),                   # one CVE: CISA entry, reports with passages, actors nearby
    "threat-levels": ("/threat-levels", 1300, [], None),               # official levels with the passage behind each
    "menu": ("/cves", 520, [("eval", "var s=document.createElement('style');s.textContent='.rgrp:nth-of-type(4) .drop{display:block!important}';"
                                      "document.head.appendChild(s); 1")], None),   # a group's pages open under the header
    "views": ("/views", 1000, [], None),                               # every page, grouped like the menu
    "techniques": ("/techniques", 1000, [], None),                     # ATT&CK techniques named in reports
    "citations": ("/citations", 1100, [], None),                      # who cites whom: agencies, reports, outside hosts
    "review": ("/actors/review", 1100, [], None),
    "network": ("/network", 1100, [("sleep", 6)], None),
    "graph": ("/graph", 1250, [], None),                                # the network of stated links: layers, most linked
    "graph-actor": ("/actors/Q41053", 1100, [("sleep", 2)], "#network"),  # Hezbollah: what the sanctions lists tie to it
    "graph-ties": ("/graph/ties?q=Rostec", 1000, [], None),             # links found by name, each with its evidence
    "graph-wikitext": ("/graph/ties?entity=Q4119382&layer=wikitext", 1100, [], None),   # links from Wikipedia article sentences
    "entity-wanted": ("/entity/US:26192", 1300, [], None),            # a GRU officer: OFAC entry and FBI notice merged, the links it states
    "leads": ("/graph/leads", 1000, [], None),                         # hypotheses: never named together, shared neighbours
    "lead": ("/graph/leads/Q42418/Q736955", 1100, [], None),         # one lead with the evidence on both sides
    "brokers": ("/graph/brokers", 900, [], None),                      # entities bridging state, cyber, terror, armed, crime
    "twins": ("/graph/twins", 1000, [], None),                         # threat groups with the most alike toolkits
    "graph-entity": ("/entity/EU:EU.11824.28", 1100, [], None),        # one company on three lists: why, numbers, its ships
    "graph-path": ("/graph/path?a=Evil+Corp&b=Federal+Security+Service", 1300, [], None),     # chains of stated links between two actors
    "rings": ("/graph/rings?e=Q41053", 1350, [], None),               # Hezbollah: links on two rings, a sector per source
    "map": ("/map", 800, [("sleep", 5)], None),
    "democracy-map": ("/map/democracy?measure=vdem_regime&year=2025", 900, [("sleep", 6)], None),
    "homicide-map": ("/map/democracy?measure=homicide&year=2023", 900, [("sleep", 6)], None),
    "timeline": ("/timeline?lane=country:UA&lane=actor:Q100605916&lane=country:DE&lane=country:US&start=2013-01-01&end=2026-12-31",
                 900, [("sleep", 6)], None),
    "timeline-event": ("/timeline?lane=country:UA&lane=actor:Q100605916&start=2021-06-01&end=2023-06-01&sel=Q110999040",
                       900, [("sleep", 7)], None),                          # an event selected: its details and relations
    "timeline-chain": ("/timeline?lane=country:IR&lane=country:IL&start=2024-01-01&end=2026-06-30&sel=Q128172378",
                       900, [("sleep", 7)], None),                          # a chain of stated causes and effects across lanes
    "democracy-change": ("/map/democracy?measure=change&year=2025", 900, [("sleep", 6)], None),
    "mentions": (f"/map/mentions?mode=about&about={CHINA}", 800, [("sleep", 6)], None),
    "mindmap": ("/topics/map", 1000, [("sleep", 4)], None),
    "update": ("/update", 1200, [], None),
    # taken while a job runs (see the module docstring): start an export or a check on /data first
    "data-export": ("/data", 1000, [("sleep", 2)], None),
    "data-import": ("/data", 1100, [("eval", "document.querySelector('input[name=tab][value=import]').click(); 1"),
                                    ("sleep", 2)], None),
}


async def shoot(ws, name: str, base: str, path: str, height: int, steps: list, clip_from: str | None) -> None:
    n = 0

    async def call(method, **params):
        nonlocal n
        n += 1
        await ws.send(json.dumps({"id": n, "method": method, "params": params}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == n:
                return m.get("result", m)

    await call("Emulation.setDeviceMetricsOverride", width=1280, height=height, deviceScaleFactor=1, mobile=False)
    await call("Page.navigate", url=base + path)
    await asyncio.sleep(3)
    # never let a step start anything: every confirmation is answered "no" (and alerts are silenced)
    await call("Runtime.evaluate", expression="window.confirm = () => false; window.alert = () => {}; "
                                              "window.rzSetTheme && rzSetTheme('dark'); 1")
    for kind, arg in steps:
        if kind == "eval":
            await call("Runtime.evaluate", expression=arg, awaitPromise=True)
        elif kind == "type":
            for ch in arg:                       # insertText fires the page's "input" events, as real typing does
                await call("Input.insertText", text=ch)
                await asyncio.sleep(0.05)
        elif kind == "sleep":
            await asyncio.sleep(arg)
    # headless Chromium does not start loading the page's web fonts by itself: load them all, then draw
    await call("Runtime.evaluate", expression="Promise.all([...document.fonts].map((f) => f.load().catch(() => 0))).then(() => 1)",
               awaitPromise=True)
    await call("Runtime.evaluate", expression=NO_LOGOS)
    await call("Runtime.evaluate", expression=NO_HOME)
    await asyncio.sleep(0.5)
    y = 0
    if clip_from:
        r = await call("Runtime.evaluate", returnByValue=True, expression=
                       f"(() => {{ const e = document.querySelector('{clip_from}'); "
                       f"return e ? e.getBoundingClientRect().top + window.scrollY - 12 : 0; }})()")
        y = max(0, int(r.get("result", {}).get("value") or 0))
    # the viewport already has the picture's size; capturing beyond it (only for a section further down) resizes the
    # page, which would also close open menus such as the search suggestions
    shot = await call("Page.captureScreenshot", format="png", captureBeyondViewport=bool(clip_from),
                      clip={"x": 0, "y": y, "width": 1280, "height": height, "scale": 1})
    (OUT / f"{name}.png").write_bytes(base64.b64decode(shot["data"]))
    print(f"{name}.png  {base + path}")


async def main(names: list[str], base: str) -> None:
    proc = subprocess.Popen(["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                             f"--remote-debugging-port={PORT}", "--window-size=1280,900", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                break
            except OSError:
                time.sleep(0.2)
        url = next(t for t in tabs if t["type"] == "page")["webSocketDebuggerUrl"]
        async with websockets.connect(url, max_size=60_000_000) as ws:
            for name in names:
                await shoot(ws, name, base, *SHOTS[name])
    finally:
        proc.terminate()


if __name__ == "__main__":
    args = sys.argv[1:]
    base = "http://127.0.0.1:8091"
    if "--base" in args:
        i = args.index("--base")
        base = args[i + 1]
        del args[i:i + 2]
    unknown = [a for a in args if a not in SHOTS]
    if unknown:
        sys.exit(f"unknown shots: {unknown}; known: {', '.join(SHOTS)}")
    asyncio.run(main(args or [n for n in SHOTS if not n.startswith("data-")], base))
