"""Report page: provenance, series neighbours and other languages, topics with matched terms, actors with a passage,
and what changed against the previous edition."""
import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, collect, db, report, series, topics


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    db.init()
    collect.init()
    actors.init()
    topics.init()
    h = topics.taxonomy()["hash"]
    texts = {2022: "Ransomware gangs. Wagner Group in Africa. BIS reports.",
             2023: "Ransomware again; Wagner Group recruits. Russia and the Lazarus Group. BIS.",
             2024: "Drones. Lazarus Group stole crypto."}
    with db.session() as con:
        con.execute("""INSERT INTO sources(id,key,country,agency,type,name_en,active)
                       VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil','Security Information Service',1)""")
        con.execute("INSERT INTO pages(id,source_id,url,lang,kind) VALUES(1,1,'https://bis.cz/vyrocni-zpravy','cs','archive')")
        n = 0
        for y in (2022, 2023, 2024):
            for lang, title in (("cs", f"Výroční zpráva BIS {y}"), ("en", f"BIS Annual Report {y}")):
                n += 1
                con.execute("""INSERT INTO documents(id,source_id,page_id,url,title,lang,year,status,local_path,sha256,size,pages_count)
                               VALUES(?,1,1,?,?,?,?,'downloaded',?,'abc',2097152,40)""",
                            (n, f"https://bis.cz/{n}.pdf", title, lang, y, f"f{n}.pdf"))
                text = texts[y]
                con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (n, title, text))
                con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages) VALUES(?,?,?,'[0, 30]')", (n, len(text), h))
                for key, word in (("Q1", "Wagner Group"), ("Q2", "Lazarus Group"), ("Q3", "BIS"), ("Q4", "Russia")):
                    if word in text:
                        s = text.index(word)
                        con.execute("INSERT INTO doc_actors(doc_id,actor_key,hits,spans,names) VALUES(?,?,1,?,?)",
                                    (n, key, f"[[{s},{s + len(word)}]]", f'{{"{word}": 1}}'))
                main = ["ransomware", "russia"] if y < 2024 else ["drones-and-new-warfare"]
                for rank, t in enumerate(main):
                    con.execute("INSERT INTO doc_topics(doc_id,topic,score,hits,terms) VALUES(?,?,?,2,?)",
                                (n, t, 10 - rank, '["ransomware", "ransom*"]' if t == "ransomware" else '["x"]'))
        con.execute("INSERT INTO actors(key,kind,label) VALUES('Q1','armed','Wagner Group')")
        con.execute("INSERT INTO actors(key,kind,label,since_year) VALUES('Q2','apt','Lazarus Group',2024)")   # founded 2024
        con.execute("INSERT INTO actors(key,kind,label) VALUES('Q3','state','BIS')")                         # the agency itself
        con.execute("INSERT INTO actors(key,kind,label,iso) VALUES('Q4','country','Russia','RU')")
        con.execute("INSERT INTO uploads(doc_id,added_at,via,original_name,official) VALUES(6,'2026-05-01 10:00','upload','bis2024.pdf',1)")
    with db.session() as con:
        series.confirm(series.propose(con)[0], name="Annual Report")
    return tmp_path


def test_detail(library):
    d = report.detail(3)                                          # Výroční zpráva BIS 2023 (cs)
    assert d["doc"]["agency"] == "BIS" and d["doc"]["page_url"] == "https://bis.cz/vyrocni-zpravy"
    assert d["edition"]["year"] == 2023 and d["series"]["name"] == "Annual Report"
    assert d["prev"]["year"] == 2022 and d["next"]["year"] == 2024
    assert [(lg, f["id"]) for lg, f in d["other_langs"]] == [("en", 4)]
    assert [t["topic"] for t in d["main"]][:2] == ["ransomware", "russia"]
    assert d["topics"][0]["terms"] == ["ransomware", "ransom*"]
    # the agency naming itself is left out, Lazarus (founded 2024) is not counted in a 2023 report, countries apart
    assert [a["label"] for a in d["actors"]] == ["Wagner Group"]
    assert d["actors"][0]["match"] == "Wagner Group" and d["actors"][0]["page"] == 1
    assert [c["label"] for c in d["countries"]] == ["Russia"]
    assert d["upload"] is None


def test_changes_against_previous_edition(library):
    d = report.detail(5)                                          # 2024 cs
    assert d["next"] is None and d["prev"]["year"] == 2023
    assert [k for k, _ in d["this"]["topics_in"]] == ["drones-and-new-warfare"]
    assert {k for k, _ in d["this"]["topics_out"]} == {"ransomware", "russia"}
    assert [a["label"] for a in d["this"]["new_actors"]] == ["Lazarus Group"]
    assert report.detail(6)["upload"]["original_name"] == "bis2024.pdf"
    assert report.detail(999) is None


def test_page_and_links(library):
    from rozvedka.app import app
    client = TestClient(app)
    r = client.get("/report/3")
    assert r.status_code == 200
    t = r.text
    assert "Výroční zpráva BIS 2023" in t and "https://bis.cz/3.pdf" in t and 'href="/doc/3"' in t
    assert 'href="/report/1"' in t and 'href="/report/5"' in t and 'href="/report/4"' in t   # previous, next, English
    assert "<mark>Wagner Group</mark>" in t and "ransom*" in t
    assert "added by hand" in client.get("/report/6").text
    assert client.get("/report/999").status_code == 404
    assert 'href="/report/1"' in client.get("/documents").text
    sid = series.sid(series.load()["series"][0])
    assert 'href="/report/1"' in client.get(f"/series/{sid}").text
