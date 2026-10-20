"""What a book of the local library says (roadmap H2c, docs/BOOKS.md) – read from its text, never written anew:

  - distinctive terms: per chapter, the words it uses far more than the library's other documents do (tf–idf against
    the document frequencies of the full-text index), so a reader sees its vocabulary;
  - key sentences: per chapter, the 3 sentences most central to it (TextRank on the words sentences share, as in
    Mihalcea & Tarau 2004), quoted as written with their page, and the distinctive terms they hold as "why chosen";
  - dated statements: every sentence that names a gazetteer actor and a date (a day, a month or a year), with its page;
  - stated relations (optional, with spaCy): two actors in one sentence joined by a verb of RELATION_VERBS – who did
    what to whom, from the sentence's grammar; a negated verb ("did not fund") is kept and marked. Every relation shows
    its sentence. Without spaCy installed this part is skipped and says so.

A part is one of the book's chapters (books.structure), read in blocks of BLOCK pages when it is longer than two
blocks; a book without chapters is read in blocks of BLOCK pages.
`python -m rozvedka index-books` builds all of it after the structure."""
import bisect
import json
import logging
import math
import re

from . import db, topics

log = logging.getLogger("rozvedka.meanings")

BLOCK = 25                  # pages per block of a book without chapters
KEY_SENTENCES = 3
TERMS = 12
MAX_SENTENCES = 400         # TextRank compares every pair: a long chapter is sampled evenly to this many sentences
STOP = frozenset("""a about above after again against all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each either else etc even ever every few for from further
had has have having he her here hers herself him himself his how however i if in into is it its itself just least
less like made make many may me might more most much must my myself neither no nor not now of off often on once one
only or other our ours ourselves out over own per rather same shall she should since so some such than that the their
theirs them themselves then there these they this those though through thus to too under until up upon us very was we
were what when where whether which while who whom whose why will with within without would yet you your yours also
two three four first second new see said say says one may might upon among page chapter part vol volume ibid op cit""".split())

SCHEMA = """
CREATE TABLE IF NOT EXISTS book_terms (doc_id INTEGER NOT NULL, unit INTEGER NOT NULL, term TEXT NOT NULL, n INTEGER,
    score REAL, PRIMARY KEY (doc_id, unit, term));
CREATE TABLE IF NOT EXISTS book_sentences (doc_id INTEGER NOT NULL, unit INTEGER NOT NULL, rank INTEGER, page INTEGER,
    sentence TEXT, why TEXT, PRIMARY KEY (doc_id, unit, rank));
CREATE TABLE IF NOT EXISTS book_statements (doc_id INTEGER NOT NULL, start INTEGER NOT NULL, page INTEGER, date TEXT,
    precision TEXT, sentence TEXT, actors TEXT, PRIMARY KEY (doc_id, start));
CREATE INDEX IF NOT EXISTS ix_book_statements_date ON book_statements(date);
CREATE TABLE IF NOT EXISTS book_relations (doc_id INTEGER NOT NULL, start INTEGER NOT NULL, subj TEXT NOT NULL, verb TEXT NOT NULL,
    obj TEXT NOT NULL, negated INTEGER, page INTEGER, sentence TEXT, PRIMARY KEY (doc_id, start, subj, verb, obj));
CREATE TABLE IF NOT EXISTS book_units (doc_id INTEGER NOT NULL, unit INTEGER NOT NULL, title TEXT, page_from INTEGER,
    page_to INTEGER, PRIMARY KEY (doc_id, unit));
"""

MONTHS = {m: i + 1 for i, m in enumerate("january february march april may june july august september october november december".split())}
MONTH = r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
DATES = [  # (regex on normalised text, precision)
    (re.compile(rf"\b(\d{{1,2}})\s+({MONTH})\s+((?:19|20)\d\d)\b"), "day"),          # 12 march 2014
    (re.compile(rf"\b({MONTH})\s+(\d{{1,2}}),?\s+((?:19|20)\d\d)\b"), "day"),          # march 12, 2014
    (re.compile(rf"\b({MONTH})\s+((?:19|20)\d\d)\b"), "month"),                          # march 2014
    (re.compile(r"\b((?:19|20)\d\d)\b"), "year"),
]
# a sentence ends at . ! ? – also when an endnote number or a footnote mark is glued to it ('infrastructure.112 In',
# 'region.* The') – before a footnote mark that starts a note (' † Importers'), and at an empty line
SENTENCE_END = re.compile(r"[.!?](?:\d{1,3})?[*†‡]*\s+(?=[A-Z0-9\"'“‘(•])|\s[*†‡]+\s+(?=[A-Z])|\n\s*\n")

# who did what to whom: verbs a relation between two actors may be stated with (lemmas); published with every relation
RELATION_VERBS = frozenset("""fund finance sponsor pay arm supply equip train recruit order command direct lead control own
back support aid help assist host shelter harbour harbor protect attack target hack strike bomb invade occupy kill
assassinate kidnap sanction designate accuse blame attribute expel arrest charge indict prosecute ally cooperate
collaborate partner coordinate meet negotiate infiltrate spy recruit create found establish replace succeed absorb
merge split oppose fight threaten pressure coerce bribe launder smuggle sell buy""".split())


def init() -> None:
    from . import actors, books
    books.init_structure()
    actors.init()
    with db.session() as con:
        con.executescript(SCHEMA)


def _words(text: str) -> list[str]:
    return [w for w in topics._WORD.findall(topics.normalize(text)) if len(w) >= 3 and w not in STOP and not w.isdigit()]


def document_frequency(con) -> tuple[dict[str, int], int]:
    """How many documents of the full-text index hold each word (fts5vocab), and how many documents there are."""
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.rz_vocab USING fts5vocab(main, doc_text, row)")
    df = dict(con.execute("SELECT term, doc FROM temp.rz_vocab"))
    n = con.execute("SELECT COUNT(*) FROM doc_text").fetchone()[0]
    return df, max(n, 1)


def distinctive_terms(text: str, df: dict[str, int], n_docs: int, k: int = TERMS) -> list[tuple[str, int, float]]:
    """[(word, times in the text, tf–idf score)] of the words the text uses far more than the library does."""
    counts: dict[str, int] = {}
    for w in _words(text):
        counts[w] = counts.get(w, 0) + 1
    scored = [(w, c, round(c * math.log((n_docs + 1) / (df.get(w, 0) + 1)), 2)) for w, c in counts.items() if c >= 3]
    return sorted(scored, key=lambda x: -x[2])[:k]


def sentences(text: str, base: int = 0) -> list[tuple[int, str]]:
    """[(start offset, sentence)] – split at a full stop, ! or ? before a capital, and at empty lines."""
    out, pos = [], 0
    for m in SENTENCE_END.finditer(text):
        cut = m.start() + (1 if text[m.start()] in ".!?" else 0)          # the full stop stays with its sentence
        piece = text[pos:cut]
        if piece.strip():
            out.append((base + pos + len(piece) - len(piece.lstrip()), " ".join(piece.split())))
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        out.append((base + pos, " ".join(tail.split())))
    return out


def key_sentences(sents: list[tuple[int, str]], terms: set[str], k: int = KEY_SENTENCES) -> list[tuple[int, str, list[str]]]:
    """The k most central sentences (TextRank: a sentence is central when it shares words with other central ones;
    similarity = shared words ÷ (log len a + log len b)), in reading order, each with the distinctive terms it holds."""
    cands = [(s, t) for s, t in sents if 8 <= len(t.split()) <= 60 and not is_reference(t) and not is_table(t)]
    if len(cands) > MAX_SENTENCES:
        step = len(cands) / MAX_SENTENCES
        cands = [cands[int(i * step)] for i in range(MAX_SENTENCES)]
    if not cands:
        return []
    bags = [set(_words(t)) for _, t in cands]
    n = len(cands)
    weights = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            shared = len(bags[i] & bags[j])
            if shared and len(bags[i]) > 1 and len(bags[j]) > 1:
                w = shared / (math.log(len(bags[i])) + math.log(len(bags[j])))
                weights[i][j] = weights[j][i] = w
    totals = [sum(row) or 1.0 for row in weights]
    score = [1.0] * n
    for _ in range(30):
        score = [0.15 + 0.85 * sum(weights[j][i] / totals[j] * score[j] for j in range(n) if weights[j][i]) for i in range(n)]
    top = sorted(range(n), key=lambda i: -score[i])[:k]
    return [(cands[i][0], cands[i][1], sorted(bags[i] & terms)) for i in sorted(top)]


def dates_in(sentence: str) -> list[tuple[str, str]]:
    """[(date as YYYY[-MM[-DD]], precision)] a sentence names, in reading order; a day or month wins over the year inside it."""
    s = topics.normalize(sentence)
    out, taken = [], []
    for rx, prec in DATES:
        for m in rx.finditer(s):
            if any(a <= m.start() < b for a, b in taken):
                continue
            g = m.groups()
            if prec == "day":
                day, month, year = (g[0], g[1], g[2]) if g[0].isdigit() else (g[1], g[0], g[2])
                if not 1 <= int(day) <= 31:
                    continue
                date = f"{year}-{MONTHS[month]:02d}-{int(day):02d}"
            elif prec == "month":
                date = f"{g[1]}-{MONTHS[g[0]]:02d}"
            else:
                date = g[0]
            out.append((m.start(), date, prec))
            taken.append((m.start(), m.end()))
    return [(d, p) for _, d, p in sorted(out)]


_nlp = {"model": None, "tried": False}


def parser():
    """spaCy's small English model, or None when spaCy is not installed (pip install spacy and en_core_web_sm)."""
    if not _nlp["tried"]:
        _nlp["tried"] = True
        try:
            import spacy
            _nlp["model"] = spacy.load("en_core_web_sm", disable=["ner"])
        except Exception as e:  # noqa: BLE001 - optional: no spaCy, no relations
            log.info("spaCy not available (%s): stated relations are skipped", e)
    return _nlp["model"]


REFERENCE = re.compile(r"(?i:[“\"][^”\"]{8,}[”\"].*\b(?:19|20)\d\d\b|\bet al\.|https?://|www\.|\baccessed\b|^Translation;|\bibid\b)"
                       # an endnote ends with its date, and perhaps its pages: '…, December 25, 2023.' '…, May 2024, 23.'
                       r"|,\s*(?:[A-Z][a-z]+\.?\s+(?:\d{1,2},\s+)?)?(?:19|20)\d\d(?:,\s*[\dxvi–-]+)*\.?$"
                       # a list of sources ('…, May 1, 2024; Alan Rappeport, …') or one beginning with its author and title
                       r"|\b(?:19|20)\d\d(?:,\s*[\dxvi–-]+)*;\s|^[A-Z][a-z]+(?: [A-Z]\.)? [A-Z][a-z]+(?:,? and [A-Z][a-z]+ [A-Z][a-z]+)?, [“\"]")


def is_table(sentence: str) -> bool:
    """A table, a figure or a contents page read as text: dot leaders ('Recommendations ......... iii'), a caption
    ('Figure 1: …', 'Table 2: …', 'Source: …'), or digits making more than 15 % of its characters."""
    return ("....." in sentence or "…………" in sentence or bool(re.search(r"\b(?:Figure|Table|Chart|Map)\s+\d+[.:]|^Source:", sentence))
            or sum(c.isdigit() for c in sentence) > 0.15 * len(sentence))


def is_reference(sentence: str) -> bool:
    """A source citation ('Allen, “Japan and the Netherlands Announce …,” CSIS, April 10, 2023') – not the book's own
    statement: its date is the source's publication date, its verbs are the source's title."""
    return bool(REFERENCE.search(sentence))


def relations_in(doc, spans: list[tuple[int, int, str]]) -> list[tuple[str, str, str, bool]]:
    """[(subject actor, verb, object actor, negated)] in one parsed sentence. `spans` are the actors' character ranges
    within the sentence. The subject is the actor that is the verb's own subject (nsubj) or the "by …" of a passive;
    the object the one that is its direct object, the subject of a passive, or the object of "against". A name of
    several words reaches the verb through its last word; a demonym ('Polish ambassador') does not stand for its
    country, a possessor ('Russia's army') not for the possessed."""
    def actor_of(tok):
        for a, b, key in spans:
            if a <= tok.idx < b:
                return key
        return None

    def heads(tok):                 # the parts of a name reach the verb through its last word
        while tok.dep_ in ("compound", "flat", "det") and tok.head.i != tok.i:
            tok = tok.head
        return tok

    out = []
    for verb in (t for t in doc if t.pos_ in ("VERB", "AUX") and t.lemma_.lower() in RELATION_VERBS):
        negated = any(c.dep_ == "neg" for c in verb.children)
        subj = obj = None
        for tok in doc:
            key = actor_of(tok)
            if not key:
                continue
            h = heads(tok)
            # (tokens are compared by position: spaCy makes a new Token object on every access)
            if h.head.i == verb.i:
                dep = h.dep_
            elif h.dep_ == "pobj" and h.head.head.i == verb.i and (h.head.dep_ == "agent" or h.head.lower_ == "against"):
                dep = "agent" if h.head.dep_ == "agent" else "against"
            else:
                continue
            if dep in ("nsubj", "agent") and not subj:
                subj = key
            elif dep in ("dobj", "nsubjpass", "against", "dative") and not obj:
                obj = key
        if subj and obj and subj != obj:
            out.append((subj, verb.lemma_.lower(), obj, negated))
    return out


def build(doc_id: int | None = None) -> dict:
    """Terms, key sentences, dated statements and (with spaCy) stated relations of every book, or one."""
    init()
    stats = {"books": 0, "units": 0, "statements": 0, "relations": 0, "parser": None}
    nlp = parser()
    stats["parser"] = "spaCy en_core_web_sm" if nlp else "not installed – relations skipped"
    with db.session() as con:
        df, n_docs = document_frequency(con)
        rows = con.execute(f"""SELECT b.doc_id, b.chapters, t.body, i.pages FROM books b JOIN doc_text t ON t.rowid=b.doc_id
                               JOIN doc_index i ON i.doc_id=b.doc_id {'WHERE b.doc_id=?' if doc_id else ''}""",
                           (doc_id,) if doc_id else ()).fetchall()
        for r in rows:
            stats["books"] += 1
            body, offsets = r["body"] or "", json.loads(r["pages"] or "[]")
            if not offsets:
                continue
            page_of = lambda pos: bisect.bisect_right(offsets, pos)        # noqa: E731 - 1-based page of an offset
            chapters = [c for c in json.loads(r["chapters"] or "[]") if c.get("level", 0) == 0] or []
            if len(chapters) >= 2:
                units = [(c["title"], c["page"], (chapters[i + 1]["page"] - 1) if i + 1 < len(chapters) else len(offsets))
                         for i, c in enumerate(chapters)]
            else:
                units = [("", 1, len(offsets))]
            # a long unit (a book without chapters, a 600-page part) is read in blocks of BLOCK pages under its title
            split = []
            for title, p0, p1 in units:
                if p1 - p0 + 1 <= 2 * BLOCK:
                    split.append((title or f"pp. {p0}–{p1}", p0, p1))
                    continue
                for q in range(p0, p1 + 1, BLOCK):
                    pages_ = f"pp. {q}–{min(q + BLOCK - 1, p1)}"
                    split.append((f"{title} ({pages_})" if title else pages_, q, min(q + BLOCK - 1, p1)))
            units = split
            for t in ("book_terms", "book_sentences", "book_statements", "book_relations", "book_units"):
                con.execute(f"DELETE FROM {t} WHERE doc_id=?", (r["doc_id"],))
            for u, (title, p0, p1) in enumerate(units):
                if p1 < p0:
                    continue
                a = offsets[p0 - 1]
                b = offsets[p1] if p1 < len(offsets) else len(body)
                text = body[a:b]
                con.execute("INSERT INTO book_units VALUES(?,?,?,?,?)", (r["doc_id"], u, title, p0, p1))
                terms = distinctive_terms(text, df, n_docs)
                con.executemany("INSERT INTO book_terms VALUES(?,?,?,?,?)", [(r["doc_id"], u, w, c, s) for w, c, s in terms])
                for rank, (start, sent, why) in enumerate(key_sentences(sentences(text, a), {w for w, _, _ in terms}), 1):
                    con.execute("INSERT INTO book_sentences VALUES(?,?,?,?,?,?)",
                                (r["doc_id"], u, rank, page_of(start), sent, json.dumps(why)))
                stats["units"] += 1
            # the actors' places in the text (the actor index) → the sentences they are named in
            spans = []
            for a in con.execute("""SELECT da.actor_key, da.spans, ac.kind FROM doc_actors da JOIN actors ac ON ac.key=da.actor_key
                                    WHERE da.doc_id=?""", (r["doc_id"],)):
                spans += [(s, e, a["actor_key"]) for s, e in json.loads(a["spans"] or "[]")]
            spans.sort()
            sents = sentences(body)
            starts = [s for s, _ in sents]
            by_sentence: dict[int, list] = {}
            for s, e, key in spans:
                i = bisect.bisect_right(starts, s) - 1
                if i >= 0:
                    by_sentence.setdefault(i, []).append((s, e, key))
            for i, found in by_sentence.items():
                start, sent = sents[i]
                if len(sent) > 600 or is_reference(sent) or is_table(sent):
                    continue                                    # a run-on line, a source citation or a table: no statement
                keys = sorted({k for _, _, k in found})
                dated = dates_in(sent)
                if dated:
                    best = dated[0]          # the date it names first: "In 2022, … found … by June 2024" is about 2022
                    con.execute("INSERT OR REPLACE INTO book_statements VALUES(?,?,?,?,?,?,?)",
                                (r["doc_id"], start, page_of(start), best[0], best[1], sent, json.dumps(keys)))
                    stats["statements"] += 1
                if nlp and len(keys) >= 2:
                    doc = nlp(sent)
                    rel_spans = [(s - start, e - start, k) for s, e, k in found]
                    for subj, verb, obj, neg in relations_in(doc, rel_spans):
                        con.execute("INSERT OR IGNORE INTO book_relations VALUES(?,?,?,?,?,?,?,?)",
                                    (r["doc_id"], start, subj, verb, obj, int(neg), page_of(start), sent))
                        stats["relations"] += 1
    log.info("book meanings: %s", stats)
    return stats


def of_book(doc_id: int) -> dict:
    """What the book page shows: per unit its terms and key sentences; the dated statements and relations (counts and
    the first ones; the full lists have their own pages)."""
    init()
    with db.session() as con:
        units = [dict(u) for u in con.execute("SELECT * FROM book_units WHERE doc_id=? ORDER BY unit", (doc_id,))]
        for u in units:
            u["terms"] = [dict(t) for t in con.execute("SELECT term, n, score FROM book_terms WHERE doc_id=? AND unit=? ORDER BY score DESC",
                                                       (doc_id, u["unit"]))]
            u["sentences"] = [dict(s) | {"why": json.loads(s["why"] or "[]")} for s in con.execute(
                "SELECT rank, page, sentence, why FROM book_sentences WHERE doc_id=? AND unit=? ORDER BY page", (doc_id, u["unit"]))]
        n_statements = con.execute("SELECT COUNT(*) FROM book_statements WHERE doc_id=?", (doc_id,)).fetchone()[0]
        n_relations = con.execute("SELECT COUNT(*) FROM book_relations WHERE doc_id=?", (doc_id,)).fetchone()[0]
    return {"units": units, "n_statements": n_statements, "n_relations": n_relations, "parser": bool(parser())}


def statements(doc_id: int, offset: int, limit: int, actor: str = "") -> tuple[int, list[dict]]:
    init()
    where, args = "doc_id=?", [doc_id]
    if actor:
        where += " AND actors LIKE ?"; args.append(f'%"{actor}"%')
    with db.session() as con:
        total = con.execute(f"SELECT COUNT(*) FROM book_statements WHERE {where}", args).fetchone()[0]
        rows = [dict(r) | {"actors": json.loads(r["actors"])} for r in con.execute(
            f"SELECT * FROM book_statements WHERE {where} ORDER BY date, page LIMIT ? OFFSET ?", (*args, limit, offset))]
        labels = dict(con.execute("SELECT key, label FROM actors WHERE key IN (%s)" % ",".join("?" * len({k for r in rows for k in r["actors"]}) or "''"),
                                  sorted({k for r in rows for k in r["actors"]}))) if rows else {}
    for r in rows:
        r["actors"] = [(k, labels.get(k, k)) for k in r["actors"]]
    return total, rows


def relations(doc_id: int, offset: int, limit: int) -> tuple[int, list[dict]]:
    init()
    with db.session() as con:
        total = con.execute("SELECT COUNT(*) FROM book_relations WHERE doc_id=?", (doc_id,)).fetchone()[0]
        rows = [dict(r) for r in con.execute(
            """SELECT r.*, a.label subj_label, b.label obj_label FROM book_relations r LEFT JOIN actors a ON a.key=r.subj
               LEFT JOIN actors b ON b.key=r.obj WHERE r.doc_id=? ORDER BY r.page LIMIT ? OFFSET ?""", (doc_id, limit, offset))]
    return total, rows
