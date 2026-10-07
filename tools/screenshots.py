"""Retake the README screenshots (docs/images/*.png) from a running portal, in the dark theme, 1280 px wide.

    .venv/bin/python -m rozvedka serve --host 127.0.0.1 --port 8091 &      # a second portal on the same library
    python3 tools/screenshots.py                    # every shot
    python3 tools/screenshots.py report ratings    # only these
    python3 tools/screenshots.py --base http://127.0.0.1:8080

Drives headless Chromium over the DevTools protocol (needs `chromium` and the `websockets` package, which comes with
uvicorn[standard]). Agency logos are removed before every shot – they are the agencies' marks and are not committed.
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
    "series": ("/series/e64e96b2", 1200, [], None),
    "collect": ("/collect", 1100, [], None),
    "topics": ("/topics", 1100, [], None),
    "terms": ("/trends/terms?term=drone&term=ransomware&term=disinformation", 1000, [("sleep", 4)], None),
    "matrix": ("/trends/matrix", 1000, [("sleep", 5)], None),
    "actor-search": ("/actors", 760, [("eval", "document.getElementById('ac-q').focus(); 1"), ("type", "prigozin"),
                                      ("sleep", 2)], None),
    "actor": ("/actors/Q7747", 1200, [("sleep", 3)], None),        # a profile with a photo and facts
    "connections": (f"/actors/{WAGNER}", 900, [("sleep", 3)], "#connections"),
    "review": ("/actors/review", 1100, [], None),
    "network": ("/network", 1100, [("sleep", 6)], None),
    "map": ("/map", 800, [("sleep", 5)], None),
    "democracy-map": ("/map/democracy?measure=vdem_regime&year=2025", 900, [("sleep", 6)], None),
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
    await call("Runtime.evaluate", expression=NO_LOGOS)
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
