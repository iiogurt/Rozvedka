"""Actor matching rules: which names are used, what they match, and the corpus-wide checks."""
import json

import pytest

from rozvedka import actors, db, topics


def gaz(*entries):
    return {"retrieved": "2026-10-01", "actors": [
        {"key": k, "qid": k, "kind": kind, "label": names[0], "description": "", "reasons": [{"via": via, "kind": kind, "text": ""}],
         "names": [{"name": n.lstrip("+"), "lang": "en",
                    "origin": "added by hand in sources/actors.yaml" if n.startswith("+") else "Wikidata label"} for n in names]}
        for k, kind, via, names in entries]}


CFG = {"ignore_aliases": ["Base", "IS"], "exclude_aliases": {"Q1": ["Vladimir"]}, "weak_aliases": {"Q5": ["Wagner"]}}
GAZ = gaz(("Q1", "person", "seed", ["Vladimir Putin", "+Putin", "Vladimir"]),
          ("Q2", "terror", "class", ["The Base", "Base"]),
          ("Q3", "state", "class", ["Federal Security Service", "FSB"]),
          ("Q4", "terror", "class", ["Islamic State", "IS", "Daesh", "ISIS", "(Yemen)", "terrorist group"]),
          ("Q5", "armed", "seed", ["Wagner Group", "Wagner"]),
          ("Q6", "cyber", "class", ["Sandworm", "Wagner"]),          # shares "Wagner" with the seeded Q5
          ("Q7", "cyber", "class", ["Lazarus Group", "lazarus", "Abc"]),
          ("Q8", "crime", "class", ["Mafia Capitale", "Ndrangheta"]),
          ("Q9", "cyber", "class", ["APT28", "Academi"]),
          ("Q10", "state", "class", ["National Security Council", "NSC"]),
          ("Q11", "crime", "class", ["Hells Angels (disbanded)", "H.A."]),
          ("Q12", "person", "class", ["Donald Trump", "Donald", "Trump"]))


def names_by(rows):
    return {(r["actor_key"], r["name"]): r for r in rows}


def test_name_rules():
    rows = names_by(actors.prepare_names(GAZ, CFG))
    assert rows[("Q2", "Base")]["reason"].startswith("on the ignore list")
    assert rows[("Q1", "Vladimir")]["reason"].startswith("excluded for this actor")
    assert rows[("Q7", "lazarus")]["reason"] == "lowercase words"
    assert rows[("Q4", "terrorist group")]["reason"] == "lowercase words"
    assert rows[("Q4", "")]["reason"].startswith("no letters")                # "(Yemen)" is only a qualifier
    assert ("Q11", "Hells Angels") in rows and rows[("Q11", "H.A.")]["reason"] == "too short"
    assert actors.is_weak(("National", "Security", "Council")) and actors.is_weak(("FSB",))
    assert not actors.is_weak(("Islamic", "State")) and not actors.is_weak(("APT28",))
    assert rows[("Q7", "Abc")]["reason"] == "3 letters without being an abbreviation"
    assert rows[("Q5", "Wagner")]["status"] == "used"                    # seed keeps a shared name
    assert rows[("Q6", "Wagner")]["reason"] == "shared with Q5"
    assert rows[("Q3", "FSB")]["status"] == "used"
    assert rows[("Q12", "Trump")]["status"] == "used" and rows[("Q12", "Donald")]["reason"].startswith("one word of a person")


@pytest.fixture
def matcher():
    names = actors.prepare_names(GAZ, CFG)
    actors._init_matcher(names)
    return {(r["actor_key"], r["name"]): r["id"] for r in names}


def found(text, ids):
    hits, _ = actors.match_text(text)
    rev = {v: k for k, v in ids.items()}
    return {rev[i]: [text[s:e] for s, e in spans] for i, spans in hits.items()}


def test_matches_case_accents_inflection_headings(matcher):
    text = ("Putinův režim a Putina; the WAGNER GROUP and Wagnera. Islamic State (Daesh) and ISLAMIC STATE. "
            "Federal Security Service (FSB); APT28. Ndranghety. Academia. No Base here, base.")
    f = found(text, matcher)
    assert f[("Q1", "Putin")] == ["Putinův", "Putina"]   # Czech endings (accents are folded: ů → u)
    assert f[("Q5", "Wagner Group")] == ["WAGNER GROUP"]
    assert ("Q5", "Wagner") not in f                         # inside "WAGNER GROUP"; no ending: not added by hand
    assert f[("Q4", "Islamic State")] == ["Islamic State", "ISLAMIC STATE"]
    assert f[("Q3", "FSB")] == ["FSB"] and f[("Q9", "APT28")] == ["APT28"]
    assert ("Q2", "The Base") not in f and ("Q9", "Academi") not in f


def test_longest_match_wins():
    g = gaz(("Q20", "terror", "class", ["Islamic State of Iraq"]),
            ("Q21", "terror", "class", ["Islamic State of Iraq and the Levant"]))
    names = actors.prepare_names(g, {})
    actors._init_matcher(names)
    ids = {(r["actor_key"], r["name"]): r["id"] for r in names}
    f = found("The Islamic State of Iraq and the Levant (2014) grew out of the Islamic State of Iraq.", ids)
    assert f == {("Q21", "Islamic State of Iraq and the Levant"): ["Islamic State of Iraq and the Levant"],
                 ("Q20", "Islamic State of Iraq"): ["Islamic State of Iraq"]}


def test_lowercase_word_counts(matcher):
    hits, lower = actors.match_text("Sandworm attacked. A sandworm is also a worm. sandworm sandworm")
    assert lower[matcher[("Q6", "Sandworm")]] == 3
    assert len(hits[matcher[("Q6", "Sandworm")]]) == 1


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    g = tmp_path / "actors.json"
    g.write_text(json.dumps(GAZ))
    c = tmp_path / "actors.yaml"
    c.write_text(json.dumps(CFG))
    monkeypatch.setattr(actors, "GAZETTEER", g)
    monkeypatch.setattr(actors, "CONFIG", c)
    db.init()
    actors.init()
    texts = {1: "The FSB recruited agents. The FSB again.",                                   # abbreviation alone
             2: "The Federal Security Service (FSB) and the Wagner Group work together.",
             3: "Sandworm. A sandworm, sandworm, sandworm in the desert.",                     # mostly an ordinary word
             4: "The National Security Council met.",                                         # generic name alone
             5: "Composer Richard Wagner.",                                                   # weak by configuration
             6: "The Wagner Group, founded in 2014, …"}
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'CZ/BIS','CZ','BIS','intelligence-civil')")
        for i, t in texts.items():
            con.execute("INSERT INTO documents(id,source_id,url,year,status) VALUES(?,?,?,?,'downloaded')",
                        (i, 1, f"u{i}", 2010 if i == 6 else 2024))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", t))
            con.execute("INSERT INTO doc_index(doc_id,chars,taxonomy_hash,pages) VALUES(?,?,?,?)", (i, len(t), "x", "[0]"))
    return tmp_path


def test_index_applies_corpus_rules(library):
    stats = actors.index(workers=1)
    assert stats["matched_docs"] == 6
    with db.session() as con:
        rows = {(r["doc_id"], r["actor_key"]) for r in con.execute("SELECT doc_id, actor_key FROM doc_actors")}
        sandworm = con.execute("SELECT status, reason FROM actor_names WHERE name='Sandworm'").fetchone()
    assert (1, "Q3") not in rows            # "FSB" alone is not corroborated by another name
    assert (4, "Q10") not in rows           # nor is a name made only of generic words
    assert (5, "Q5") not in rows            # "Wagner" is weak by configuration
    assert (2, "Q3") in rows and (2, "Q5") in rows
    assert (3, "Q6") not in rows and sandworm["status"] == "ignored"
    assert "lowercase more often" in sandworm["reason"]
    d = actors.actor_detail("Q3")
    assert d["docs"] == 1 and d["passages"][0]["page"] == 1 and d["passages"][0]["match"] == "Federal Security Service"
    assert [r["key"] for r in d["related"]["actors"]] == ["Q5"]
    assert actors.index(workers=1)["matched_docs"] == 0          # nothing new: nothing matched again


def test_reports_before_founding_are_not_counted(library):
    actors.index(workers=1)
    with db.session() as con:
        con.execute("UPDATE actors SET since_year=2014 WHERE key='Q5'")
    d = actors.actor_detail("Q5")
    assert [b["doc_id"] for b in d["before"]] == [6] and d["docs"] == 1      # doc 2 (2024) counts, doc 6 (2010) not
    assert {r["key"]: r["docs"] for r in actors.actor_list(min_docs=1)}["Q5"] == 1


def test_page_of():
    assert topics.page_of([0, 100, 250], 0) == 1
    assert topics.page_of([0, 100, 250], 120) == 2
    assert topics.page_of(None, 5) is None


def test_exclude_sources(library):
    (library / "actors.yaml").write_text(json.dumps({**CFG, "exclude_sources": {"Q5": ["CZ/BIS"]}}))
    actors.index(workers=1)
    with db.session() as con:
        assert con.execute("SELECT COUNT(*) FROM doc_actors WHERE actor_key='Q5'").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM doc_actors WHERE actor_key='Q3'").fetchone()[0] == 1


def test_person_names_inside_other_names_are_skipped():
    g = gaz(("Q30", "person", "class", ["Alan Turing"]), ("Q31", "person", "class", ["Theodore Roosevelt"]))
    names = actors.prepare_names(g, {})
    actors._init_matcher(names)
    ids = {(r["actor_key"], r["name"]): r["id"] for r in names}
    f = found("Alan Turing broke Enigma. The Alan Turing Institute. USS Theodore Roosevelt; Theodore Roosevelt said.", ids)
    assert f == {("Q30", "Alan Turing"): ["Alan Turing"], ("Q31", "Theodore Roosevelt"): ["Theodore Roosevelt"]}
