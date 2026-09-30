"""Fill in coordinates for registry entries whose `hq:` has an address but no lat/lon yet.

    python3 tools/geocode_hq.py            # geocode missing entries, rewrite sources/registry.yaml in place
    python3 tools/geocode_hq.py --dry-run  # only show what would be found

Uses OpenStreetMap Nominatim (usage policy: max 1 request/second, identify the application).
precision is derived from what Nominatim actually matched: address (building), street, or city.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent.parent / "sources" / "registry.yaml"
UA = "Rozvedka/0.1 (personal research archive; geocoding agency HQ addresses)"
BUILDING = {"building", "house", "office", "amenity", "military", "government", "place", "house_number",
            "public_building", "man_made", "tourism"}
STREET = {"road", "street", "square", "neighbourhood", "quarter"}


def geocode(query: str) -> dict | None:
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "jsonv2", "limit": 1})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
        res = json.load(r)
    time.sleep(1.1)
    return res[0] if res else None


def locate(address: str) -> tuple[float, float, str] | None:
    hit = geocode(address)
    if hit:
        kind = hit.get("addresstype", "")
        parts = address.split(", ")
        precision = ("address" if kind in BUILDING else "street" if kind in STREET else "city")
        if len(parts) <= 2:          # the address itself is only "City, Country"
            precision = "city"
        return round(float(hit["lat"]), 5), round(float(hit["lon"]), 5), precision
    city = ", ".join(address.split(", ")[-2:])          # fall back to "City, Country"
    hit = geocode(city) if city != address else None
    return (round(float(hit["lat"]), 5), round(float(hit["lon"]), 5), "city") if hit else None


def main(dry_run: bool) -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    pattern = re.compile(r'^(  hq: )\{address: ("(?:[^"\\]|\\.)*")\}\s*$', re.M)

    def repl(m: re.Match) -> str:
        address = json.loads(m.group(2))
        found = locate(address)
        if not found:
            print(f"NOT FOUND  {address}")
            return m.group(0)
        lat, lon, precision = found
        print(f"{precision:<8} {lat:>9} {lon:>10}  {address}")
        return f"{m.group(1)}{{address: {m.group(2)}, lat: {lat}, lon: {lon}, precision: {precision}}}"

    new = pattern.sub(repl, text)
    if not dry_run and new != text:
        REGISTRY.write_text(new, encoding="utf-8")
        print("registry updated")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
