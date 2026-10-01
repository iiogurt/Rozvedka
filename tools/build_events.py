"""Resolve sources/events.yaml against Wikipedia and Wikidata, so every chart marker carries its source.

    python3 tools/build_events.py            # fill in missing items
    python3 tools/build_events.py --refresh  # look up every event again

For each event's English Wikipedia title it records the Wikidata item (from the article's page properties) and the
item's date – "point in time" (P585), else "start time" (P580), else "inception" (P571) – with links to both pages and the retrieval date.
"""
import argparse
import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "sources" / "events.yaml"
UA = "Rozvedka/0.x (personal research library; https://github.com/iiogurt/Rozvedka)"
DATE_PROPS = (("P585", "point in time"), ("P580", "start time"), ("P571", "inception"))


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def resolve(title: str) -> dict | None:
    q = urllib.parse.urlencode({"action": "query", "prop": "pageprops", "ppprop": "wikibase_item", "redirects": 1,
                                "titles": title, "format": "json", "formatversion": 2})
    page = get_json(f"https://en.wikipedia.org/w/api.php?{q}")["query"]["pages"][0]
    if page.get("missing") or "pageprops" not in page:
        print(f"WARNING: no Wikipedia article / Wikidata item for {title!r} – event not shown")
        return None
    qid = page["pageprops"]["wikibase_item"]
    time.sleep(1)
    claims = get_json(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")["entities"][qid]["claims"]
    for prop, prop_name in DATE_PROPS:
        for c in claims.get(prop, []):
            v = c["mainsnak"].get("datavalue", {}).get("value")
            if not v:
                continue
            # Wikidata time: "+2022-02-24T00:00:00Z", precision 11 = day, 10 = month, 9 = year
            y, m, d = v["time"][1:11].split("-")
            date = {11: f"{y}-{m}-{d}", 10: f"{y}-{m}"}.get(v["precision"], y)
            article = page["title"]
            return {"wikidata": qid, "date": date, "date_property": f"{prop} ({prop_name})",
                    "wikipedia_url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(article.replace(" ", "_")),
                    "wikidata_url": f"https://www.wikidata.org/wiki/{qid}#{prop}"}
    print(f"WARNING: {title!r} ({qid}) has no {', '.join(p for p, _ in DATE_PROPS)} on Wikidata – event not shown")
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    text = EVENTS.read_text(encoding="utf-8")
    header = text[:text.index("events:")]
    data = yaml.safe_load(text)
    today = dt.date.today().isoformat()
    for ev in data["events"]:
        if ev.get("wikidata") and not a.refresh:
            continue
        found = resolve(ev["wikipedia"])
        if found is None:
            continue
        ev.update(found, retrieved=today)
        print(f"{ev['date']:<10} {ev['wikidata']:<10} {ev['label']}  ({ev['date_property']})")
        time.sleep(1)
    data["events"].sort(key=lambda e: e.get("date", "9999"))
    EVENTS.write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


if __name__ == "__main__":
    main()
