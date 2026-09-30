"""countries.yaml consistency, well-known membership facts, and version/changelog agreement."""
import re
from pathlib import Path

from rozvedka import __version__, countries
from rozvedka.registry import load

ROOT = Path(__file__).resolve().parent.parent


def test_every_registry_country_is_described():
    names = countries.names()
    missing = {s["country"] for s in load()} - set(names)
    assert not missing, f"add to sources/countries.yaml: {missing}"


def test_coalition_keys_and_years_valid():
    keys = set(countries.coalitions())
    for code in countries.names():
        for coalition, year in countries.memberships(code).items():
            assert coalition in keys, (code, coalition)
            assert 1940 <= year <= 2030, (code, coalition, year)


def test_known_memberships():
    assert countries.members("FVEY") == {"US", "GB", "CA", "AU", "NZ"}
    assert countries.members("AUKUS") == {"AU", "GB", "US"}
    assert countries.members("G7") == {"US", "CA", "GB", "FR", "DE", "IT", "JP"}
    assert countries.memberships("FI")["NATO"] == 2023
    assert countries.memberships("SE")["NATO"] == 2024
    assert "EU" not in countries.memberships("GB")                       # left in 2020
    assert not {"AT", "IE", "CY", "MT", "CH"} & countries.members("NATO")
    assert "NO" in countries.members("SCHENGEN") and "IE" not in countries.members("SCHENGEN")
    assert len(countries.members("EU")) == 27


def test_regions_known():
    for code in countries.names():
        assert countries.region_of(code)[1] != "Other", code


def test_version_matches_changelog():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    releases = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
    assert releases and releases[0] == __version__, "newest CHANGELOG.md release must equal rozvedka.__version__"
