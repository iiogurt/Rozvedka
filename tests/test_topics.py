"""Topic taxonomy validity and classification behaviour (no network, no PDFs)."""
import re

import pytest

from rozvedka.topics import classify, fts_query, normalize, taxonomy, term_regex


def test_taxonomy_loads_and_keys_unique():
    tax = taxonomy()
    assert len(tax["topics"]) >= 50
    for key, tp in tax["topics"].items():
        assert re.fullmatch(r"[a-z0-9-]+", key), key
        assert tp["terms"], key


def test_no_dangerously_short_stems():
    """A prefix stem of 1–3 letters would match half the dictionary."""
    for key, tp in taxonomy()["topics"].items():
        for term in tp["terms"]:
            for tok in term.split():
                if tok.endswith("*"):
                    assert len(normalize(tok.rstrip("*"))) >= 3, (key, term)


def test_normalize_folds_accents_and_special_letters():
    assert normalize("Rechtsextremismus Ärger Øst Straße łódź Đ") == "rechtsextremismus arger ost strasse lodz d"


@pytest.mark.parametrize("term,text,hit", [
    ("extremis*", "the extremist scene", True),
    ("extremis*", "nonextremist", False),                 # stems anchor at a word start
    ("isis", "crisis management", False),                 # whole words only
    ("pravicov* extremis*", "pravicového extremismu", True),
    ("far right", "far-right groups", True),              # spaces also match hyphens
    ("右翼", "日本の右翼団体", True),                        # CJK: substring
])
def test_term_regex(term, text, hit):
    assert bool(re.search(term_regex(term), normalize(text))) is hit


@pytest.mark.parametrize("text,title,expected", [
    ("Right-wing extremists and neo-Nazi groups recruited online. The far-right scene grew; "
     "accelerationist propaganda spread among far-right youth.", "", "right-wing-extremism"),
    ("Rechtsextremisten und Neonazis: das rechtsextreme Personenpotenzial stieg weiter an. "
     "Rechtsextremistische Musik", "", "right-wing-extremism"),
    ("Pravicoví extremisté a neonacisté. Pravicový extremismus a neonacistické skupiny.", "", "right-wing-extremism"),
    ("Russia's intelligence services and the Kremlin run influence operations; Russian disinformation", "",
     "russia"),
    ("Ransomware groups such as LockBit and Akira extorted victims; ransom demands rose.", "", "ransomware"),
    ("Short text", "Nasjonal trusselvurdering: høyreekstremisme", "right-wing-extremism"),   # title alone suffices
    # languages added for the hazard, resilience, cyber and crime topics (0.32.1)
    ("Procjena rizika od katastrofa: poplave, bujice i klizišta. Poplave su najveći rizik.", "", "floods-storms"),
    ("Ocena tveganja za poplave. Poplave in zemeljski plazovi ogrožajo naselja.", "", "floods-storms"),
    ("Sustav civilne zaštite i skloništa; civilna zaštita djeluje u svim općinama.", "", "civil-defence"),
    ("Emergencias y damnificados por huaicos; atención de emergencias en Piura.", "", "crisis-management"),
    ("Kibernetički kriminal i prijevare: zlonamjerni softver i računalni kriminal.", "", "cybercrime-fraud"),
    ("Οργανωμένο έγκλημα και ναρκωτικά: η κοκαΐνη και τα ναρκωτικά.", "", "drug-trafficking"),
    ("Polizeiliche Kriminalstatistik (PKS): Fallzahlen, Tatverdächtige und Aufklärungsquote.", "", "crime-statistics"),
    ("ISO 27001 information security management; encryption and intrusion detection; Locked Shields.", "", "cyber-security-practice"),
])
def test_classify_finds_topic(text, title, expected):
    assert expected in [f["key"] for f in classify(text, title)]


def test_single_passing_mention_is_not_enough():
    text = ("This long report is about flood defences, heavy rain and river management. " * 400) + " One sentence mentions Russia."
    keys = [f["key"] for f in classify(text)]
    assert "russia" not in keys and "floods-storms" in keys


def test_fts_query_is_safe():
    assert fts_query('ruská "hybridní hrozby" 2025') == '"hybridní hrozby" AND "ruská"* AND "2025"*'
    assert fts_query('drop table"; --') == '"drop"* AND "table"*'


@pytest.mark.parametrize("text,not_expected", [
    ("Tasking orders and tasking cycles; tasking again. Storm troopers.", "floods-storms"),         # Turkish taşkın → taskin
    ("SUSE Linux and SUSE updates; Linux drought of patches.", "wildfires-heat-drought"),           # suše → suse
    ("Šiem gadījumiem un šiem dokumentiem; šiem nolūkiem šifrēšana.", "cyber-security-practice"),  # Latvian šiem → siem
])
def test_false_friends_from_accent_folding(text, not_expected):
    """Terms are folded (š → s, ş → s): a term from one language must not become a common word of another."""
    assert not_expected not in [f["key"] for f in classify(text * 5)]
