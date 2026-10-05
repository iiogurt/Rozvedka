"""Report series: title stems, proposals, coverage states and the confirmations written to series.yaml."""
import datetime as dt

import pytest
import yaml

from rozvedka import db, series


def test_stem_drops_years_sizes_and_filler():
    assert series.stem("Výroční zpráva BIS 2023 (PDF, 2,3 MB)") == "vyrocni zprava bis"
    assert series.stem("Annual Report of the Security Information Service for 2021") == \
        series.stem("Annual Report of the Security Information Service for 2019")
    assert series.stem("Bericht 2022/2023") == series.stem("Bericht 2023-24")


def test_clean_name():
    assert series._clean_name("Výroční zpráva 2023 (PDF, 3 MB) Stáhnout") == "Výroční zpráva"
    assert series._clean_name("Krajobraz bezpieczeństwa polskiego Internetu w roku 2023") == "Krajobraz bezpieczeństwa polskiego Internetu"
    assert series._clean_name("DEFENSE OF JAPAN 2024 (Digest") == "DEFENSE OF JAPAN (Digest)"


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    db.init()
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil')")
        n = 0
        for y in range(2018, 2025):
            for lang, title in (("cs", f"Výroční zpráva BIS {y}"), ("en", f"BIS Annual Report {y}")):
                if (y, lang) in ((2021, "en"), (2024, "en")):
                    continue                                   # no English edition in 2021; 2024 not yet
                n += 1
                status = "browser-only" if (y, lang) == (2019, "cs") else "downloaded"
                con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,local_path)
                               VALUES(?,1,?,?,?,?,?,?)""", (n, f"u{n}", title, lang, y, status,
                                                            None if status != "downloaded" else f"f{n}.pdf"))
        con.execute("INSERT INTO documents(id,source_id,url,title,lang,year,status) VALUES(99,1,'x','Press release 2020','en',2020,'downloaded')")
    return tmp_path


def test_proposal_joins_languages_with_the_same_years(library):
    with db.session() as con:
        props = series.propose(con)
    assert len(props) == 1
    p = props[0]
    assert p["languages"] == ["cs", "en"] and p["since"] == 2018 and p["per_year"] == 1
    assert p["titles"] == {"cs": ["vyrocni zprava bis"], "en": ["bis annual report"]}


def test_coverage_states_and_yaml(library):
    with db.session() as con:
        prop = series.propose(con)[0]
    s = series.confirm(prop, name="Annual Report")
    with db.session() as con:
        assert series.propose(con) == []                          # confirmed: no longer proposed
        c = series.coverage(con, s, today=dt.date(2026, 3, 1))
    state = {(r["lang"], cell["year"]): cell["state"] for r in c["rows"] for cell in r["cells"]}
    assert state[("cs", 2018)] == "have" and state[("cs", 2019)] == "listed"
    assert state[("en", 2021)] == "missing"
    assert state[("en", 2024)] == "expected" and state[("cs", 2025)] == "expected"
    assert c["years"][-1] == 2025 and not c["complete"]

    series.mark_absent("CZ/BIS", "Annual Report", 2021, "en", "no English edition (checked)")
    data = yaml.safe_load(series.SERIES_FILE.read_text())
    assert data["series"][0]["absent"] == {"2021 en": "no English edition (checked)"}
    with db.session() as con:
        c = series.coverage(con, series.load()["series"][0], today=dt.date(2026, 3, 1))
    assert {cell["state"] for r in c["rows"] for cell in r["cells"] if cell["year"] == 2021} == {"have", "absent"}
    series.unmark_absent("CZ/BIS", "Annual Report", 2021, "en")
    assert not series.load()["series"][0].get("absent")


def test_reject_and_merge_into(library):
    with db.session() as con:
        p = series.propose(con)[0]
    series.reject(p["key"])
    with db.session() as con:
        assert series.propose(con) == []
    assert series.load()["rejected"] == [p["key"]]
    # merging: confirm the cs part, then add the en titles into it
    series.SERIES_FILE.unlink()
    only_cs = {**p, "languages": ["cs"], "titles": {"cs": p["titles"]["cs"]}}
    series.confirm(only_cs, name="Výroční zpráva")
    series.confirm({**p, "languages": ["en"], "titles": {"en": p["titles"]["en"]}}, into="Výroční zpráva")
    (s,) = series.load()["series"]
    assert s["languages"] == ["cs", "en"] and s["titles"]["en"] == ["bis annual report"]


def test_pages_render(library):
    from fastapi.testclient import TestClient

    from rozvedka.app import app
    with db.session() as con:
        series.confirm(series.propose(con)[0], name="Annual Report")
    with TestClient(app) as client:
        r = client.get("/sources/coverage")
        assert r.status_code == 200 and "Annual Report" in r.text and "sg-missing" in r.text
        assert client.get("/sources").status_code == 200


def test_series_reading_views(library):
    from fastapi.testclient import TestClient

    from rozvedka import actors, topics
    from rozvedka.app import app
    actors.init()
    with db.session() as con:
        s = series.confirm(series.propose(con)[0], name="Annual Report")
        h = topics.taxonomy()["hash"]
        for doc_id, tags in {1: ["russia", "china"], 3: ["china", "terrorism"], 5: ["china"]}.items():
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash) VALUES(?,?,?)", (doc_id, 10, h))
            for rank, t in enumerate(tags):
                con.execute("INSERT INTO doc_topics(doc_id,topic,score) VALUES(?,?,?)", (doc_id, t, 10 - rank))
    sid = series.sid(s)
    assert series.get(sid)["name"] == "Annual Report"
    idx = series.doc_index()
    assert idx[1] == {"id": sid, "name": "Annual Report", "year": 2018, "lang": "cs"} and 99 not in idx
    d = series.detail(sid, "cs")
    assert [e["year"] for e in d["editions"]][:2] == [2024, 2023] and d["lang"] == "cs"
    e2019 = next(e for e in d["editions"] if e["year"] == 2019)
    assert [k for k, _ in e2019["main"]] == ["china", "terrorism"]
    assert [k for k, _ in e2019["topics_in"]] == ["terrorism"] and [k for k, _ in e2019["topics_out"]] == ["russia"]
    cat = series.catalogue()
    assert cat[0]["id"] == sid and cat[0]["editions"] == 7
    with TestClient(app) as client:
        assert client.get("/series").status_code == 200
        r = client.get(f"/series/{sid}")
        assert r.status_code == 200 and "Edition by edition" in r.text
        docs = client.get(f"/documents?series={sid}")
        assert docs.status_code == 200 and "editions of CZ/BIS – Annual Report" in docs.text
        assert client.get("/series/nope").status_code == 404
