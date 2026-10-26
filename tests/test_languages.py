"""The language of a report's text by rule, and the correction of stored languages it allows."""
import pytest

from rozvedka import db, languages

EN = ("The service has observed that the threat from state actors is growing, and that their activities have been "
      "directed at critical infrastructure which is essential for the functioning of society. ") * 20
FI = ("Suojelupoliisi arvioi, että valtiollisten toimijoiden uhka on kasvanut ja että niiden toiminta kohdistuu myös "
      "kriittiseen infrastruktuuriin, joka on tärkeä yhteiskunnan toiminnalle ja se voi olla vaarallista. ") * 20
BG = ("Агенцията отбелязва, че заплахата от държавни участници нараства и че техните действия са насочени към "
      "критичната инфраструктура, която е важна за обществото, като се вижда и от доклада. ") * 20
DE = ("Das Amt stellt fest, dass die Bedrohung durch staatliche Akteure wächst und sich auch auf die kritische "
      "Infrastruktur richtet, die für die Gesellschaft wichtig ist und nicht ersetzt werden kann. ") * 20


@pytest.mark.parametrize("text,lang", [(EN, "en"), (FI, "fi"), (BG, "bg"), (DE, "de"), ("too short", None),
                                       ("防衛白書は日本の防衛政策を説明します。" * 60, "ja"),
                                       ("防卫白皮书说明日本的防卫政策。" * 60 + "です", "zh"),    # a few kana: still Chinese
                                       ("국방백서는 일본의 방위 정책을 설명합니다" * 60 + "です" * 30, "ko")])
def test_text_lang(text, lang):
    assert languages.text_lang(text) == lang


def test_bilingual_text_has_no_verdict():
    assert languages.text_lang(EN + DE) is None
    assert languages.prefers(DE, "de", "en") and not languages.prefers(EN, "de", "en")


def test_address_langs():
    assert languages.address_langs("https://europol.europa.eu/x/Blueprint-criminal-opportunism-resumen-es.pdf") == {"es"}
    assert languages.address_langs("https://x.eu/doc_bg?filename=Political%20Guidelines%202024-2029_BG.pdf") == {"bg"}
    assert languages.address_langs("https://x.de/Strategie-de-securite-nationale-FR.pdf") == {"de", "fr"}
    assert languages.address_langs("https://x.org/report.pdf") == set()


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init()
    from rozvedka import topics
    topics.init()
    rows = [  # id, url, stored language, why, text
        (1, "https://europol.europa.eu/d/TE-SAT-2026-Rezyume-bg.pdf", "en", None, BG),     # address and text: bg
        (2, "https://tet.dk/pet_2025_uk.pdf", "en", None, EN),                              # "uk" = United Kingdom
        (3, "https://ria.ee/aastaraamat_ar.pdf", "et", None, EN),                           # text alone: English
        (4, "https://supo.fi/documents/abc?t=1", "en", None, FI),                           # text alone: Finnish
        (5, "https://supo.fi/documents/def-fi.pdf", "en", "set by hand", FI),               # set by hand: kept
        (6, "https://x.de/Strategie-de-securite-nationale-FR.pdf", "de", None, DE),         # text says de: kept
        (7, "https://x.de/bilingual.pdf", "de", None, EN + DE),                             # both languages: kept
    ]
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'EU/X','EU','X','police-ct')")
        for i, url, lang, why, text in rows:
            con.execute("INSERT INTO documents(id,source_id,url,title,lang,lang_why,status) VALUES(?,1,?,'t',?,?,'downloaded')",
                        (i, url, lang, why))
            con.execute("INSERT INTO doc_text(rowid,title,body) VALUES(?,?,?)", (i, "", text))
    return tmp_path


def test_retag(library):
    out = languages.retag()
    assert out["languages_corrected"] == 3 and out["en→bg"] == 1 and out["et→en"] == 1 and out["en→fi"] == 1
    with db.session() as con:
        got = {r["id"]: (r["lang"], r["lang_why"]) for r in con.execute("SELECT id, lang, lang_why FROM documents")}
    assert got[1][0] == "bg" and got[1][1].startswith("address names “bg” and the text reads as bg")
    assert got[2] == ("en", None) and got[6] == ("de", None) and got[7] == ("de", None)
    assert got[3][0] == "en" and "the text reads as en" in got[3][1]
    assert got[4][0] == "fi" and got[5] == ("en", "set by hand")
    assert languages.retag()["languages_corrected"] == 0          # a corrected language is not looked at again
