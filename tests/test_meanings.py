"""What a book says (rozvedka/meanings.py): distinctive terms, key sentences, dated statements, stated relations –
read from the text, every one with its sentence and page."""
import json

import pytest

from rozvedka import books, collect, db, meanings, series, topics


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    db.init()
    collect.init()
    topics.init()
    meanings.init()
    yield tmp_path


def test_dates_in_a_sentence():
    assert meanings.dates_in("On 12 March 2014 the GRU moved in.") == [("2014-03-12", "day")]
    assert meanings.dates_in("By March 12, 2014, it was over; in 2015 again.") == [("2014-03-12", "day"), ("2015", "year")]
    assert meanings.dates_in("In 2022, the department found it would end by June 2024.") == [("2022", "year"), ("2024-06", "month")]
    assert meanings.dates_in("In February 2022 Russia invaded.") == [("2022-02", "month")]
    assert meanings.dates_in("Page 34 of 120.") == []


def test_sentences_terms_and_key_sentences():
    text = ("The Wagner Group recruited fighters in prisons across Russia. " * 2 + "Weather was mild. "
            "Wagner fighters fought in Syria and in Libya for money and mines. The group answered to Prigozhin and the GRU. "
            "Bakhmut fell after months of fighting by Wagner units recruited in prisons.")
    sents = meanings.sentences(text)
    assert sents[0] == (0, "The Wagner Group recruited fighters in prisons across Russia.") and len(sents) == 6
    glued = "It targeted Guam.112 In 2023 it grew. † Importers can use ports. The end."
    assert [t for _, t in meanings.sentences(glued)] == ["It targeted Guam.", "In 2023 it grew.", "Importers can use ports.", "The end."]
    df = {"wagner": 1, "recruited": 50, "prisons": 2, "fighters": 30}
    terms = meanings.distinctive_terms(text * 3, df, 1000)
    assert terms[0][0] == "wagner"                                              # rare in the library, frequent here
    assert [t for t, _, _ in terms].index("recruited") > [t for t, _, _ in terms].index("prisons")   # common in the library: lower
    key = meanings.key_sentences(sents, {"wagner", "prisons"}, k=2)
    assert len(key) == 2 and all(k[0] in [s for s, _ in sents] for k in key)
    assert key == sorted(key)                                                   # in reading order
    assert "Weather was mild." not in [k[1] for k in key]                      # short and shares nothing


def test_build_dated_statements(library):
    body = ("Chapter one.\nIn March 2014 the GRU took Crimea. Nothing else happened.\n"
            "Chapter two.\nOn 9 May 2015 Sandworm and the GRU met in Moscow. The end.\n")
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,publisher,active) VALUES(9,'BOOK/X','OTHER','X','book','book',1)")
        con.execute("INSERT INTO documents(id,source_id,url,title,status,doc_type) VALUES(90,9,'book:x','B','downloaded','book')")
        con.execute("INSERT INTO books(doc_id,file,format,chapters) VALUES(90,'b.pdf','pdf','[]')")
        con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(90,'B',?)", (body,))
        con.execute("INSERT INTO doc_index(doc_id,pages) VALUES(90,?)", (json.dumps([0, body.index("Chapter two")]),))
        con.execute("INSERT INTO actors(key,kind,label,data) VALUES('Q1','state','GRU','{}'), ('Q2','cyber','Sandworm','{}')")
        gru = [[body.index("GRU"), body.index("GRU") + 3], [body.rindex("GRU"), body.rindex("GRU") + 3]]
        con.execute("INSERT INTO doc_actors(doc_id,actor_key,hits,spans) VALUES(90,'Q1',2,?)", (json.dumps(gru),))
        sw = body.index("Sandworm")
        con.execute("INSERT INTO doc_actors(doc_id,actor_key,hits,spans) VALUES(90,'Q2',1,?)", (json.dumps([[sw, sw + 8]]),))
    st = meanings.build()
    assert st["books"] == 1 and st["statements"] == 2
    total, rows = meanings.statements(90, 0, 10)
    assert total == 2 and [(r["date"], r["precision"], r["page"]) for r in rows] == [("2014-03", "month", 1), ("2015-05-09", "day", 2)]
    assert rows[1]["actors"] == [("Q1", "GRU"), ("Q2", "Sandworm")]
    assert meanings.statements(90, 0, 10, actor="Q2")[0] == 1
    of = meanings.of_book(90)
    assert of["n_statements"] == 2 and of["units"][0]["title"] == "pp. 1–2"           # no chapters: blocks of pages


def test_stated_relations():
    nlp = meanings.parser()
    if nlp is None:
        pytest.skip("spaCy and en_core_web_sm are not installed")
    s = "The GRU ordered Sandworm to attack the grid."
    rel = meanings.relations_in(nlp(s), [(4, 7, "GRU"), (16, 24, "SW")])
    assert ("GRU", "order", "SW", False) in rel
    s = "Russia did not fund the Wagner Group."
    assert meanings.relations_in(nlp(s), [(0, 6, "RU"), (24, 36, "WG")]) == [("RU", "fund", "WG", True)]
    s = "Sandworm was funded by the GRU."
    assert ("GRU", "fund", "SW", False) in meanings.relations_in(nlp(s), [(0, 8, "SW"), (27, 30, "GRU")])
    s = "The GRU and Sandworm were mentioned."                                       # no relation verb
    assert meanings.relations_in(nlp(s), [(4, 7, "GRU"), (12, 20, "SW")]) == []


def test_tables_are_not_statements():
    assert meanings.is_table("Key Recommendations ...................... iii v 1 5 27 2024 Report to Congress")
    assert meanings.is_table("Date 2024 1,200 3,400 5,600 7,800 2023 1,100 3,300")
    assert meanings.is_table("101 Figure 1: PLA Organizational Structure before and after April 2024 Reorganization")
    assert not meanings.is_table("Russia surpassed Saudi Arabia as China's top foreign crude oil supplier in 2023.")


def test_references_are_not_statements():
    assert meanings.is_reference('Allen, “Japan and the Netherlands Announce Plans for New Export Controls,” CSIS, April 10, 2023.')
    assert meanings.is_reference("Translation; CCP International Liaison Department, Liu Jianchao Meets the Ambassador, May 26, 2024.")
    assert meanings.is_reference("CCP International Liaison Department, Liu Jianchao Meets Polish Ambassador to China, December 25, 2023.")
    assert meanings.is_reference("United States Commission on International Religious Freedom, 2024 Annual Report, May 2024, 23.")
    assert not meanings.is_reference("In March 2014 the GRU took Crimea.")
    assert not meanings.is_reference("Nauru switched its recognition to the PRC in January 2024.")
    assert meanings.is_reference("Department of State, Imposing New Measures on Russia, May 1, 2024; Alan Rappeport, “U.S.")
    assert meanings.is_reference("Nargiza Salidjanova, “Going Out: 290 stance, China National Building Material")


def test_relations_are_strict():
    nlp = meanings.parser()
    if nlp is None:
        pytest.skip("spaCy and en_core_web_sm are not installed")
    s = "But the roads leading from Italy into Germany are long."                  # roads lead, not Italy
    assert meanings.relations_in(nlp(s), [(26, 31, "IT"), (37, 44, "DE")]) == []
    s = "Liu met the Polish ambassador."                                            # a demonym is not its country
    assert meanings.relations_in(nlp(s), [(0, 3, "LIU"), (12, 18, "PL")]) == []
    s = "In 2015 Moscow sanctioned Kyiv."
    at = lambda w, k: (s.index(w), s.index(w) + len(w), k)
    assert meanings.relations_in(nlp(s), [at("Moscow", "MOS"), at("Kyiv", "KYI")]) == [("MOS", "sanction", "KYI", False)]
