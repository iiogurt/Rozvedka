"""Consistency checks for sources/registry.yaml (no network)."""
import pytest

from rozvedka.registry import load, source_key

SOURCES = load()
TYPES = {"intelligence-civil", "intelligence-military", "cyber", "civil-protection", "police-ct", "eu-body", "nato", "other"}
ACCESS = {"auto", "browser-ua", "tls-lenient", "browser-js", "manual"}
KINDS = {"current", "archive", "series"}
# rough (lat_min, lat_max, lon_min, lon_max) per country; EU members, EU bodies and NATO use the Europe box
EUROPE = (34, 71, -11, 35)
BOXES = {
    "GB": (49, 61, -9, 2), "NO": (57, 72, 4, 32), "CH": (45.8, 48, 5.9, 10.6), "US": (24, 50, -125, -66),
    "CA": (41, 84, -141, -52), "AU": (-44, -10, 112, 154), "NZ": (-48, -34, 166, 179), "JP": (24, 46, 122, 146),
    "KR": (33, 39, 124, 132), "TW": (21, 26, 119, 123), "OTHER": (-90, 90, -180, 180),
    "UA": (44, 53, 22, 41), "MX": (14, 33, -118, -86), "BR": (-34, 6, -74, -34), "AR": (-56, -21, -74, -53),
    "CL": (-56, -17, -76, -66), "CO": (-5, 13, -80, -66), "PE": (-19, 0, -82, -68),
}


def test_keys_unique():
    keys = [source_key(s) for s in SOURCES]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("s", SOURCES, ids=source_key)
def test_profile_complete(s):
    assert s["type"] in TYPES
    assert s.get("access", "auto") in ACCESS
    assert s.get("name_en") and s.get("name_local")
    assert s.get("homepage", "").startswith("https://")
    assert len(s.get("description", "")) > 40


@pytest.mark.parametrize("s", SOURCES, ids=source_key)
def test_pages_valid(s):
    assert s["pages"], "every source needs at least one report page"
    for p in s["pages"]:
        assert p["url"].startswith("https://"), p["url"]
        assert p["kind"] in KINDS
        assert p["lang"]


@pytest.mark.parametrize("s", SOURCES, ids=source_key)
def test_hq_location(s):
    hq = s.get("hq")
    assert hq, "every source needs an hq entry for the map"
    assert hq["precision"] in {"address", "street", "city"}
    assert hq["address"]
    lat0, lat1, lon0, lon1 = BOXES.get(s["country"], EUROPE)
    # a pin outside its country's box means the geocoder matched a namesake (London, Ontario …)
    assert lat0 <= hq["lat"] <= lat1 and lon0 <= hq["lon"] <= lon1, (s["country"], hq["lat"], hq["lon"])
