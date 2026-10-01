"""Country names, regions and coalition memberships from sources/countries.yaml."""
from functools import lru_cache

import yaml

from .config import ROOT

COUNTRIES_FILE = ROOT / "sources" / "countries.yaml"


@lru_cache(maxsize=1)
def _data() -> dict:
    data = yaml.safe_load(open(COUNTRIES_FILE, encoding="utf-8"))
    # guard against the YAML "Norway problem": a bare NO key becomes boolean False
    assert all(isinstance(k, str) for k in data["countries"]), "quote country codes such as \"NO\" in countries.yaml"
    return data


def reload() -> None:
    _data.cache_clear()


def names() -> dict[str, str]:
    return {code: c["name"] for code, c in _data()["countries"].items()}


def coalitions() -> dict[str, dict]:
    """{'NATO': {'name': ..., 'short': ..., 'description': ...}, ...} in display order."""
    return _data()["coalitions"]


def memberships(country: str) -> dict[str, int]:
    """{'EU': 2004, 'NATO': 1999, ...} – coalition key -> year joined."""
    return dict(_data()["countries"].get(country, {}).get("coalitions") or {})


def scope(coalition: str) -> set[str]:
    """Registry country codes in a coalition; the EU and NATO filters also include their own institutions."""
    return members(coalition) | ({coalition} if coalition in ("EU", "NATO") else set())


def members(coalition: str) -> set[str]:
    return {code for code, c in _data()["countries"].items() if coalition in (c.get("coalitions") or {})}


def region_of(country: str) -> tuple[int, str]:
    regions = _data()["regions"]
    region = _data()["countries"].get(country, {}).get("region")
    return (regions.index(region), region) if region in regions else (len(regions), "Other")
