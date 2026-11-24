"""The coverage grid: covered, empty, checked and open slots, and that every count opens its reports."""
from fastapi.testclient import TestClient

from rozvedka import collect, db, gaps
from test_trends import library  # noqa: F401  – CZ/BIS (intelligence-civil) and DE/BSI (cyber) with a few reports


def test_cells(library, monkeypatch, tmp_path):
    f = tmp_path / "gaps.yaml"
    f.write_text("- {country: CZ, type: cyber, checked: 2026-10-06, note: none found}\n"
                 "- {country: CZ, type: intelligence-civil, checked: 2026-10-06, note: ignored – a source exists}\n", encoding="utf-8")
    monkeypatch.setattr(gaps, "FILE", f)
    gaps.checked.cache_clear()
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,access) VALUES(7,'CZ/NUKIB','CZ','NUKIB','civil-protection','manual')")
        con.execute("INSERT INTO sources(id,key,country,agency,type,publisher) VALUES(8,'CZ/TT','CZ','TT','think-tank','independent')")
    g = gaps.grid()
    cz = next(r for r in g["rows"] if r["code"] == "CZ")
    cells = {c["type"]: c for c in cz["cells"]}
    assert cells["intelligence-civil"]["state"] == "covered" and cells["intelligence-civil"]["n"] == 2     # hidden doc not counted
    assert cells["cyber"]["state"] == "checked" and cells["cyber"]["note"] == "none found"
    assert cells["civil-protection"]["state"] == "empty" and cells["civil-protection"]["manual"] == 1
    assert cells["police-ct"]["state"] == "open"
    assert [i["type"] for i in cz["independent"]] == ["think-tank"] and cz["other"] == []          # think tanks apart
    assert {"code": "CZ", "name": cz["name"], "type": "police-ct", "type_name": "Police / counter-terrorism"} in g["open"]
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    collect.init()
    from rozvedka.app import app
    c = TestClient(app)
    for r in g["rows"]:
        for x in r["cells"]:
            if x["state"] == "covered":
                assert f"<b>{x['n']}</b> documents match" in c.get(x["link"]).text, x["link"]
    assert "∅" in c.get("/sources/grid").text
    # a second agency of the same type: its reports are added once, the agencies counted once each (and the
    # cached grid is recomputed after the write)
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(9,'CZ/UZSI','CZ','UZSI','intelligence-civil')")
        con.execute("INSERT INTO documents(id,source_id,url,title,year,hidden,status) "
                    "VALUES(90,9,'https://uzsi.cz/v.pdf','Výroční zpráva',2031,0,'downloaded')")
    civil = next(c for c in next(r for r in gaps.grid()["rows"] if r["code"] == "CZ")["cells"] if c["type"] == "intelligence-civil")
    assert (civil["n"], civil["agencies"], civil["newest"]) == (3, 2, 2031)
