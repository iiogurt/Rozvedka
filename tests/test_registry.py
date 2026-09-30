"""Consistency checks for sources/registry.yaml (no network)."""
import pytest

from rozvedka.registry import load, source_key

SOURCES = load()
TYPES = {"intelligence-civil", "intelligence-military", "cyber", "civil-protection", "police-ct", "eu-body", "nato", "other"}
ACCESS = {"auto", "browser-ua", "tls-lenient", "browser-js", "manual"}
KINDS = {"current", "archive", "series"}


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
    if s["country"] == "OTHER":
        assert -90 <= hq["lat"] <= 90 and -180 <= hq["lon"] <= 180
    else:
        # EU member states, EU bodies and NATO HQs all lie inside this box (Lisbon … Nicosia, Crete … Lapland)
        assert 34 <= hq["lat"] <= 71 and -11 <= hq["lon"] <= 35, (hq["lat"], hq["lon"])
