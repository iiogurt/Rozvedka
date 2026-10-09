"""Official attributions: quote checks, the hand-written file, and the pages."""
import json

import pytest
from fastapi.testclient import TestClient

from rozvedka import attributions, db


def test_quote_check_is_loose_about_typography():
    text = attributions.page_text("<p>The NCSC has attributed  Sandworm to the Russian GRU’s Main Centre &ndash; GTsST.</p><script>x</script>")
    e = {"quote": "attributed Sandworm to the Russian GRU's Main Centre - GTsST", "names": ["sandworm"]}
    assert attributions.check_page(e, text)["ok"]
    r = attributions.check_page({"quote": "attributed Turla to the GRU", "names": ["Sandworm", "APT29"]}, text)
    assert not r["ok"] and not r["quote"] and r["names_missing"] == ["APT29"]


def test_the_file_is_well_formed():
    rows = attributions.load()
    assert len(rows) >= 20
    for r in rows:
        assert r["url"].startswith("https://") and r["quote"].strip() and r["says"].strip() and r["title"].strip()
        assert r["actors"] and len(str(r["date"])) == 10 and r["by"] and len(r["country"]) == 2, r["url"]
    assert len({r["url"] for r in rows}) == len(rows)
    assert [str(r["date"]) for r in rows] == sorted((str(r["date"]) for r in rows), reverse=True)


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    f = tmp_path / "attributions.yaml"
    f.write_text("""attributions:
  - {date: 2025-05-21, by: NCSC, country: GB, kind: cyber, actors: [Q1, Q2], title: T1, url: "https://x/1", quote: q1, says: s1}
  - {date: 2024-01-01, by: CISA, country: US, kind: cyber, actors: [Q1], title: T2, url: "https://x/2", quote: q2, says: s2}
""")
    monkeypatch.setattr(attributions, "FILE", f)
    monkeypatch.setattr(attributions, "CHECKS", tmp_path / "checks.json")
    attributions._checks.cache_clear()
    db.init()
    from rozvedka import actors
    actors.init()
    with db.session() as con:
        for k, label in (("Q1", "Fancy Bear"), ("Q2", "GRU"), ("Q3", "Other")):
            con.execute("INSERT INTO actors(key,kind,label,data) VALUES(?,'cyber',?,'{}')", (k, label))
    return tmp_path


def test_pages_and_check_state(library):
    (library / "checks.json").write_text(json.dumps({"https://x/1": {"ok": True, "checked": "2026-10-09"},
                                                     "https://x/2": {"ok": False, "checked": "2026-10-09"}}))
    attributions._checks.cache_clear()
    from rozvedka.app import app
    c = TestClient(app)
    a = c.get("/actors/Q1").text
    assert 'id="attributions"' in a and "T1" in a and "T2" in a
    assert "quote confirmed on the page, checked 2026-10-09" in a and "quote not confirmed" in a
    assert 'id="attributions"' not in c.get("/actors/Q3").text
    t = c.get("/actors/attributions").text
    assert "2 listed, 1 with the quote confirmed" in " ".join(t.split())
    assert "/actors/Q2" in t
    assert attributions.overview()["confirmed"] == 1
