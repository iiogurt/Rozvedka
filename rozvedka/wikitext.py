"""Links between subjects stated in the text of their English Wikipedia articles.

The infobox of an article (rozvedka/connections.py) names leaders, founders and allies; the text says much more: "X is a
member of [[Y]]", "split from [[Z]] in 2014", "funded by [[W]]". A sentence of an actor's article that links to the article of
another known actor or person becomes a link of the network (layer "wikitext"), with the sentence, the section, the article
and its revision as evidence. Who is meant is certain – the sentence links to that article (redirects included); what the
relation is comes from the words of the sentence and its section ("member", "founded", "split", "funded" …), a keyword rule
shown with every link; a sentence without such a word is kept as "named in the article". Countries are not linked, nor
sentences of the See also, References and similar sections.

    python -m rozvedka fetch-wikitext     # network: the articles of the actors the reports name (a few minutes)

The articles are not kept, only the linking sentences, in data/gazetteer/wikitext_links.json (CC BY-SA 4.0, attributed with
article and revision).
"""
import datetime as dt
import json
import logging
import re
import urllib.parse

from . import actor_sources, db
from .config import DATA

log = logging.getLogger("rozvedka.wikitext")
FILE = DATA / "gazetteer" / "wikitext_links.json"
BATCH = 20                  # articles per request (the API returns the full text of each)
MAX_TARGETS = 15            # a sentence linking more known subjects is a list, not a statement about them
SKIP_SECTIONS = {"see also", "references", "notes", "further reading", "external links", "bibliography", "sources",
                 "citations", "footnotes", "notes and references", "works cited", "gallery", "literature"}
RELATIONS = [   # (relation, words) – the first that the sentence or its section heading contains decides
    ("membership", r"\bmembers?\b|\bmembership\b|\bjoined\b|\bjoining\b|\benlisted\b|\brecruit"),
    ("founding", r"\bfound(?:ed|er|ers|ing)\b|\bco-?found|\bestablished\b|\bformed by\b"),
    ("split or affiliate", r"\bsplinter|\bsplit\b|\bbroke away|\boffshoot|\bfaction\b|\bwing\b|\bbranch\b|\baffiliat|\bsubsidiar"
                           r"|\bfront (?:organi[sz]ation|group|company)|\bproxy|\bproxies"),
    ("succession or merger", r"\bmerged?\b|\bmerger\b|\bsuccessor\b|\bpredecessor\b|\brenamed\b|\bformerly\b|\bsucceeded\b"),
    ("leadership", r"\bled\b|\bheads\b|\bleaders?\b|\bcommanders?\b|\bheaded\b|\bchief\b|\bchairman\b|\bdirector\b|\bemir\b"),
    ("support or funding", r"\bfund(?:ed|ing|s)?\b|\bfinanc|\bsponsor|\bbacked\b|\bsupport(?:ed|s|ing|er|ers)?\b|\barmed by\b"
                           r"|\bsuppl(?:ied|ies|ier)\b|\btrain(?:ed|ing)\b|\bweapons\b|\bsafe haven\b"),
    ("alliance or cooperation", r"\ball(?:y|ies|ied|iance)\b|\bcooperat|\bco-operat|\bcollaborat|\bcoordinat|\bpartner"
                                r"|\bjoint\b|\bworked with\b|\bties\b|\bconnections?\b|\bassociat"),
    ("conflict", r"\battack|\bfought\b|\bfight|\bclash|\bwar\b|\brival|\benem(?:y|ies)\b|\bopposed\b|\btarget|\bassassinat"
                 r"|\bkill|\bbomb|\bhostil|\bconflict|\bagainst\b|\bcrackdown|\barrest"),
]
GENERIC = "named in the article"
_REL = [(name, re.compile(rx, re.I)) for name, rx in RELATIONS]


NEAR = 60                   # characters around the linked name in which the relation word must stand


def relation(sentence: str, section: str = "", label: str = "") -> tuple[str, str]:
    """(relation, the word that decided it). The word must stand near the linked name (`label`, as the sentence writes it):
    in "brother of MEK leader Massoud Rajavi" the word "leader" is Massoud Rajavi's, not the brother's link with him – such a
    sentence is only "named in the article". A list item takes its section heading ("Members")."""
    window = sentence
    if label and label in sentence:
        i = sentence.index(label)
        window = sentence[max(0, i - NEAR):i + len(label) + NEAR]
    for name, rx in _REL:
        m = rx.search(window)
        if m:
            return name, m.group(0).lower()
    if len(sentence) < 40:                       # a list item: the section says what the list is
        for name, rx in _REL:
            m = rx.search(section or "")
            if m:
                return name, m.group(0).lower()
    return GENERIC, ""


def norm_title(t: str) -> str:
    t = urllib.parse.unquote(t or "").replace("_", " ").split("#", 1)[0].strip()
    return t[:1].upper() + t[1:] if t else ""


# ── wikitext → sentences with links ──
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_REF = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_LINK = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]")
_EXT = re.compile(r"\[https?://[^\s\]]+\s*([^\]]*)\]")
_HEADING = re.compile(r"^(=+)\s*(.*?)\s*\1\s*$")
_SENT = re.compile(r"(?<=[.!?])[\"”’)]?\s+(?=[A-Z\"“(\[])")


def _bare(s: str) -> str:
    """Plain text: bold and italic marks and stray link brackets (of nested links) removed, spaces collapsed."""
    s = s.replace("[[", "").replace("]]", "")
    return " ".join(s.replace("'''", "").replace("''", "").split())


def _strip_templates(text: str) -> str:
    """Remove {{templates}} and {| tables |}, nested ones included."""
    out, depth, i = [], 0, 0
    while i < len(text):
        two = text[i:i + 2]
        if two in ("{{", "{|"):
            depth += 1
            i += 2
        elif depth and two in ("}}", "|}"):
            depth -= 1
            i += 2
        else:
            if not depth:
                out.append(text[i])
            i += 1
    return "".join(out)


def sentences(wikitext: str) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """[(section heading, sentence as plain text, [(link target, its text in the sentence)])] of an article's prose and lists."""
    text = _strip_templates(_REF.sub("", _COMMENT.sub("", wikitext or "")))
    out, section, skip = [], "", False
    for line in text.split("\n"):
        h = _HEADING.match(line.strip())
        if h:
            section = _LINK.sub(lambda m: m.group(2) or m.group(1), h.group(2)).strip()
            skip = section.lower() in SKIP_SECTIONS
            continue
        if skip or not line.strip():
            continue
        line = re.sub(r"\[\[(?:File|Image|Category|Datei|Fichier):[^\]]*(?:\[\[[^\]]*\]\][^\]]*)*\]\]", "", line, flags=re.I)
        line = _EXT.sub(r"\1", _TAG.sub("", line)).lstrip("*#:; ")
        for s in _SENT.split(line):
            targets = [(norm_title(m.group(1)), _bare(m.group(2) or m.group(1))) for m in _LINK.finditer(s) if ":" not in m.group(1)]
            if not targets:
                continue
            plain = _bare(_LINK.sub(lambda m: m.group(2) or m.group(1), s))
            if len(plain) >= 3:            # a list item under "Members" is just the name
                out.append((section, plain, targets))
    return out


# ── fetching ──
def _known(con) -> tuple[dict[str, str], dict[str, str]]:
    """Wikipedia title → actor or connected entity key; and the titles of the articles to read (actors in the reports)."""
    from . import actors
    titles, read = {}, {}
    gaz = actors.load_gazetteer()
    for a in gaz["actors"]:
        t = norm_title(((a.get("wikipedia") or {}).get("title")) or "")
        if t and a["kind"] != "country":
            titles.setdefault(t, a["key"])
    for qid, url in con.execute("SELECT qid, wikipedia FROM link_entities WHERE wikipedia LIKE 'https://en.wikipedia.org/wiki/%'"):
        titles.setdefault(norm_title(url.rsplit("/wiki/", 1)[1]), qid)
    named = {r[0] for r in con.execute("SELECT DISTINCT actor_key FROM doc_actors")}
    for a in gaz["actors"]:
        t = norm_title(((a.get("wikipedia") or {}).get("title")) or "")
        if t and a["key"] in named and a["kind"] != "country":
            read[a["key"]] = t
    return titles, read


def _redirects(titles: list[str]) -> dict[str, str]:
    """Redirect title → the title it leads to, for the known titles (so [[Hizbollah]] is Hezbollah)."""
    out = {}
    for chunk in actor_sources._chunks(titles, 50):
        params = {"action": "query", "prop": "redirects", "rdlimit": "max", "rdnamespace": 0, "titles": "|".join(chunk),
                  "format": "json", "formatversion": 2}
        while True:
            d = actor_sources._get(actor_sources.WP_API, params)
            for p in d.get("query", {}).get("pages", []):
                for r in p.get("redirects", []):
                    out[norm_title(r["title"])] = p["title"]
            for n in d.get("query", {}).get("normalized", []):
                out[norm_title(n["from"])] = n["to"]
            if "continue" not in d:
                break
            params = {**params, **d["continue"]}
    return out


def fetch() -> dict:
    with db.session() as con:
        titles, read = _known(con)
    log.info("wikitext: %d articles to read, %d known titles", len(read), len(titles))
    redirects = _redirects(sorted(titles))
    resolve = {**{r: titles[norm_title(t)] for r, t in redirects.items() if norm_title(t) in titles}, **titles}
    articles = {}
    keys = sorted(read)
    for i, chunk in enumerate(actor_sources._chunks(keys, BATCH)):
        d = actor_sources._get(actor_sources.WP_API, {"action": "query", "prop": "revisions", "rvprop": "content|ids",
                                                      "rvslots": "main", "titles": "|".join(read[k] for k in chunk),
                                                      "redirects": 1, "format": "json", "formatversion": 2})
        q = d.get("query", {})
        back = {norm_title(read[k]): k for k in chunk}
        for m in q.get("normalized", []) + q.get("redirects", []):
            if norm_title(m["from"]) in back:
                back[norm_title(m["to"])] = back[norm_title(m["from"])]
        for p in q.get("pages", []):
            key = back.get(norm_title(p.get("title", "")))
            rev = (p.get("revisions") or [{}])[0]
            text = ((rev.get("slots") or {}).get("main") or {}).get("content")
            if not key or not text:
                continue
            links, seen = [], set()
            for section, s, targets in sentences(text):
                found = {}
                for t, label in targets:
                    k = resolve.get(t)
                    if k and k != key and k not in found:
                        found[k] = label
                if not found or len(found) > MAX_TARGETS:
                    continue
                for k, label in found.items():
                    rel, word = relation(s, section, label)
                    if (k, rel) in seen:
                        continue
                    seen.add((k, rel))
                    links.append({"to": k, "relation": rel, "word": word, "section": section, "sentence": s[:600]})
            articles[key] = {"title": p["title"], "revision": rev.get("revid"), "links": links}
        log.info("wikitext %d/%d articles", min((i + 1) * BATCH, len(keys)), len(keys))
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"meta": {"retrieved": dt.date.today().isoformat(), "api": actor_sources.WP_API,
                                         "licence": "CC BY-SA 4.0", "redirects": len(redirects)},
                                "articles": articles}, ensure_ascii=False), encoding="utf-8")
    n = sum(len(a["links"]) for a in articles.values())
    by = {}
    for a in articles.values():
        for l in a["links"]:
            by[l["relation"]] = by.get(l["relation"], 0) + 1
    return {"articles": len(articles), "links": n, "by_relation": by}


def stored() -> dict:
    return json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {"meta": None, "articles": {}}


def wiki_rev(title: str, revision) -> str:
    return f"https://en.wikipedia.org/w/index.php?title={urllib.parse.quote(title.replace(' ', '_'))}&oldid={revision}"
