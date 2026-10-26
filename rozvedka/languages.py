"""The language of a report's text, by rule: its script and its most frequent short words – no model.

Used to confirm a language code in a file's address (…_bg.pdf, /fr/…): the crawler only knows the languages a source
is listed with, so the 24 language versions of a Europol summary were all tagged English. An address code alone is
not enough – "_uk" is often the United Kingdom, "_ar" an annual report, "IT-" information technology – so a stored
language is changed only when the address and the text both name the same other language."""
import logging
import re
from collections import Counter

log = logging.getLogger("rozvedka.languages")

# the most frequent function words of each language (lowercase); words shared by close languages are left out
WORDS = {
    "en": "the of and to is that for are with this which be from have has were been their will would there",
    "de": "der die und das nicht ist mit sich auf für eine den dem des wird werden auch nach bei einer zur",
    "fr": "les des est une dans pour qui sur pas par aux sont cette ces leur été avec elle entre",
    "it": "della che il gli delle nel sono degli alla anche questo dei nella dalla essere stato tra",
    "es": "los las del que una por para con como más sus está entre también ser fue sobre",
    "pt": "dos das uma não são pelo pela mais também aos ao foi entre sobre seus",
    "nl": "het een van zijn niet voor met wordt ook deze aan worden bij naar door",
    "sv": "och att det som för med är på till inte har ett av också eller kan",
    "da": "og at det som for med er på af til ikke har et også eller kan",
    "no": "og at det som for med er på av til ikke har et også eller ble",
    "fi": "ja on että tai kuin myös ovat sekä se joka mukaan voi ei ole",
    "et": "ja on et ning või kui mis ka see oma selle need ei",
    "lv": "un ir ar par uz kas no lai vai tiek arī šo savu",
    "lt": "ir yra kad su iš kaip bei arba šios jų buvo taip",
    "pl": "się na że do nie jest dla oraz przez jak są w",
    "cs": "se na je že to jako pro jsou které také byl nebo",
    "sk": "sa na je že to ako pre sú ktoré tiež bol alebo",
    "hu": "az és hogy is nem egy meg csak vagy mint ez már",
    "ro": "și în la cu care pe din pentru este sau ale sunt",
    "hr": "je se na za da su od koji kao ili što",
    "sl": "in je se na za da so od ki kot ali tudi",
    "ga": "agus na ar le go bhfuil ag do ó",
    "mt": "ta il li fil għall tal huwa minn biex dan jew",
    "is": "og að í á er sem til um við með ekki það",
    "sq": "dhe të në për që me një nga është si së",
    "tr": "ve bir bu için ile olarak olan daha gibi",
    "bg": "и на за да в се от е с че които са като",
    "ru": "и в на что с по не для как это от из также",
    "uk": "і в на що з та до не для як це від також",
    "mk": "и на за да во се од е со што кои како",
    "el": "και το της την του να με που στην από για τα των",
}
_ALL = Counter(w for v in WORDS.values() for w in set(v.split()))
_SETS = {k: set(v.split()) for k, v in WORDS.items()}
_WORD = re.compile(r"[^\W\d_]+")
SCRIPTS = {"el", "ar", "ja", "ko", "zh"}
MIN_WORDS = 200          # fewer words than that: no verdict
MIN_SCORE = 0.03         # at least 3 % of the words must be the language's own
MARGIN = 2.0             # and twice as many as for the language it is compared with
# without a code in the address the text alone must be clear: 5 % of its words the other language's, and the
# stored language's at most 15 % of that (a bilingual report scores high for both and is left alone)
TEXT_ONLY_MIN = 0.05
TEXT_ONLY_RATIO = 0.15
SCRIPT_NAMES = {"el": "Greek", "ar": "Arabic", "ja": "Japanese", "ko": "Korean", "zh": "Chinese"}


def script_of(text: str) -> str | None:
    """A script that names its language by itself: Greek, Arabic, Japanese kana, Korean Hangul, Chinese characters."""
    counts = Counter()
    for ch in text[:20000]:
        o = ord(ch)
        if 0x370 <= o <= 0x3FF:
            counts["el"] += 1
        elif 0x600 <= o <= 0x6FF:
            counts["ar"] += 1
        elif 0x3040 <= o <= 0x30FF:
            counts["ja"] += 1
        elif 0xAC00 <= o <= 0xD7AF:
            counts["ko"] += 1
        elif 0x4E00 <= o <= 0x9FFF:
            counts["zh"] += 1
    if counts["ja"] > 50 and counts["ja"] * 10 >= counts["zh"] and counts["ja"] > counts["ko"]:
        return "ja"                       # kana: Japanese, even with more Chinese characters (a few kana are a heading)
    counts.pop("ja", None)
    best = counts.most_common(1)
    return best[0][0] if best and best[0][1] > 500 else None


def scores(text: str) -> dict[str, float]:
    """Share of the words that are each language's function words; a word of several languages counts for each in
    part (Danish and Norwegian share most of theirs). A script of its own scores 1 for its language."""
    if not text:
        return {}
    s = script_of(text)
    if s in SCRIPTS - {"el"}:
        return {s: 1.0}
    words = _WORD.findall(text[:60000].lower())
    if len(words) < MIN_WORDS:
        return {}
    freq = Counter(words)
    return {k: sum(freq[w] / _ALL[w] for w in ws) / len(words) for k, ws in _SETS.items()}


def text_lang(text: str) -> str | None:
    """The language of a text, or None when the evidence is thin or two languages score close."""
    sc = sorted(((v, k) for k, v in scores(text).items()), reverse=True)
    if not sc:
        return None
    if len(sc) == 1:
        return sc[0][1]
    (top, lang), (second, _) = sc[0], sc[1]
    return lang if top >= MIN_SCORE and top >= second * MARGIN else None


def prefers(text: str, lang: str, other: str) -> bool:
    """Does the text read as `lang` rather than as `other`? (Norwegian Bokmål is scored as Norwegian.)"""
    sc = scores(text)
    a, b = sc.get("no" if lang == "nb" else lang, 0.0), sc.get("no" if other == "nb" else other, 0.0)
    return a >= MIN_SCORE and a >= b * MARGIN


CODES = "en|de|fr|it|nl|cs|sk|pl|sv|da|nb|fi|et|lv|lt|es|pt|ro|bg|hr|sl|hu|el|ru|ja|zh|ga|mt|is|sq|mk|tr|uk|ar"


def address_langs(url: str) -> set[str]:
    """The language codes an address names: …/en/…, en_x.pdf, x-en.pdf, x_EN.pdf, ?filename=…_SL.pdf."""
    from urllib.parse import parse_qsl, unquote, urlsplit
    parts = urlsplit(url or "")
    names = [unquote(parts.path).lower()] + [unquote(v).lower() for _, v in parse_qsl(parts.query) if re.search(r"\.pdf$", v, re.I)]
    found = set()
    for path in names:
        stem = path.rsplit(".", 1)[0] if "." in path.rsplit("/", 1)[-1] else path
        found |= set(re.findall(rf"(?:^|[/_. -])({CODES})(?=[/_. -]|$)", stem))
    return found


def _text_only(text: str, stored: str) -> str | None:
    lang = text_lang(text)
    if not lang or lang == ("no" if stored == "nb" else stored):
        return None
    sc = scores(text)
    a, b = sc.get(lang, 0.0), sc.get("no" if stored == "nb" else stored, 0.0)
    if a < TEXT_ONLY_MIN or b > a * TEXT_ONLY_RATIO:
        return None
    _text_only.why = (f"the text is written in {SCRIPT_NAMES[lang]} script (was tagged {stored or '–'})" if lang in SCRIPTS else
                      f"the text reads as {lang}: {a:.0%} of its words are {lang} function words, {b:.1%} {stored or '–'}"
                      f" (was tagged {stored or '–'})")
    return lang


def retag() -> dict:
    """Correct a stored language (`documents.lang_why` keeps the evidence) where
      1. the address names another language and the text reads as that language rather than the stored one, or
      2. the text alone reads clearly as another language and hardly as the stored one.
    Languages set by hand or by an earlier pass are left alone."""
    from . import db
    stats = Counter()
    with db.session() as con:
        rows = con.execute(
            """SELECT d.id, d.url, d.lang, substr(t.body, 1, 60000) body FROM documents d JOIN doc_text t ON t.rowid=d.id
               WHERE d.hidden=0 AND d.lang_why IS NULL AND d.status NOT IN ('missing','duplicate','skipped')""").fetchall()
        for r in rows:
            stored = r["lang"] or ""
            named = [c for c in address_langs(r["url"]) if c != stored and prefers(r["body"], c, stored)]
            if len(named) == 1:
                new = named[0]
                why = f"address names “{new}” and the text reads as {new}, not {stored or 'unknown'} (was tagged {stored or '–'})"
            elif not (new := _text_only(r["body"], stored)):
                continue
            else:
                why = _text_only.why
            con.execute("UPDATE documents SET lang=?, lang_why=? WHERE id=?", (new, why, r["id"]))
            stats[f"{stored or '?'}→{new}"] += 1
    out = {"languages_corrected": sum(stats.values()), **dict(stats.most_common())}
    log.info("languages %s", out)
    return out
