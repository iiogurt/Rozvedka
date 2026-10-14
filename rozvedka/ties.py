"""The connection graph – one table of entities (actors, listed people and companies, vessels, malware, campaigns …)
and one of ties between them, every tie with the layer it comes from and its evidence.

    python -m rozvedka build-graph     # local: rebuilt from what is already downloaded (a minute on the Pi)

Layers (nothing is guessed here; every tie is something a source states):
  - us        US Treasury OFAC SDN list: "Linked To: …" in an entry's remarks, the name resolved on the same list
  - uk, un, eu  the narrative of a listing (UK statement of reasons, UN comments, EU remarks) naming another entry of
              the same list by its full name – the sentence is the evidence
  - wikidata, wikipedia  the actor gazetteer's connections (statements and infobox fields, rozvedka/connections.py)
  - attack    MITRE ATT&CK: a group or campaign using malware or a tool, a campaign attributed to a group
  - reports   two actors (not countries) named in one passage of at least MIN_TOGETHER reports

A list entry that the sanctions matching tied to an actor (rozvedka/sanctions.py, by exact name) *is* that actor's
node, and an ATT&CK group is the actor that carries its ATT&CK number – that is where the layers meet. Entries of
different lists are not merged with each other yet.
"""
import datetime as dt
import json
import logging
import re

from collections import Counter

from . import actors, db, identity, paging, sanctions, techniques, trends
from .actors import PAIR_FOUNDED

log = logging.getLogger("rozvedka.ties")

LAYERS = {
    "us": {"name": "US Treasury: “Linked To”", "group": "official",
           "about": "OFAC's SDN list: an entry's remarks name the entry it is linked to"},
    "uk": {"name": "UK Sanctions List", "group": "official",
           "about": "a designation's statement of reasons names another designation; its parent companies, subsidiaries, ship owners"},
    "un": {"name": "UN Security Council: listing narratives", "group": "official",
           "about": "the comments of a UN Security Council listing name another listed person or entity"},
    "eu": {"name": "EU: remarks", "group": "official",
           "about": "the remarks of an EU listing (associated entities, reasons) name another EU listing"},
    "ids": {"name": "Shared details", "group": "official",
            "about": "list entries giving the same street address, e-mail, website, telephone number or crypto wallet – linked through it"},
    "wikidata": {"name": "Wikidata statements", "group": "reference",
                 "about": "statements such as member of, founded by, parent organisation – with their references"},
    "wikipedia": {"name": "Wikipedia infoboxes", "group": "reference",
                  "about": "infobox fields of the actor's English Wikipedia article (leaders, allies, parent …)"},
    "attack": {"name": "MITRE ATT&CK", "group": "reference",
               "about": "groups and campaigns using malware and tools; campaigns attributed to groups"},
    "reports": {"name": "Named together in the reports", "group": "reports",
                "about": "two actors named in one passage (600 characters) of at least two reports – a co-mention, not a stated tie"},
}
GROUPS = {"official": "Official lists", "reference": "Reference data", "reports": "The library's reports"}
LIST_LAYER = {"US": "us", "UK": "uk", "UN": "un", "EU": "eu"}
SHAPES = {"Individual": "person", "Entity": "org", "Vessel": "vessel", "Ship": "vessel", "Aircraft": "aircraft"}
KINDS = {**actors.KINDS, "person": "Person", "org": "Company or organisation", "vessel": "Vessel", "aircraft": "Aircraft",
         "malware": "Malware", "tool": "Tool", "campaign": "Campaign", "address": "Address", "email": "E-mail address",
         "website": "Website", "phone": "Telephone number", "wallet": "Crypto wallet"}
LABEL_ORDER = ("UK", "EU", "UN", "US")
DETAIL_BACK = {"address": "address of", "email": "e-mail address of", "website": "website of", "phone": "telephone number of",
               "wallet": "crypto wallet of"}
UN_REF = re.compile(r"\b([A-Z]{2}[ei]\.\d{3})\b")       # a UN listing's reference number: QDe.004, CDi.012
MIN_TOGETHER = 2
MIN_NAME = 6            # characters: shorter names are not looked for in the narratives
QUOTE = 420             # characters of a narrative sentence kept as evidence

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (id TEXT PRIMARY KEY, kind TEXT, label TEXT, actor TEXT, origin TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS ties (                 -- "a rel b"; seen from b it reads "b back a"
    id INTEGER PRIMARY KEY, a TEXT NOT NULL, b TEXT NOT NULL, rel TEXT, back TEXT, layer TEXT, date TEXT,
    weight INTEGER, evidence TEXT);
CREATE INDEX IF NOT EXISTS ix_ties_a ON ties(a, layer);
CREATE INDEX IF NOT EXISTS ix_ties_b ON ties(b, layer);
CREATE TABLE IF NOT EXISTS ties_meta (k TEXT PRIMARY KEY, v TEXT);
"""


def init() -> None:
    with db.session() as con:
        con.executescript(SCHEMA)


# ── building ──
class _Graph:
    def __init__(self, actor_rows: dict):
        self.actors = actor_rows
        self.entities: dict[str, tuple] = {}
        self.ties: dict[tuple, list] = {}

    def actor(self, key: str) -> str:
        a = self.actors[key]
        self.entities.setdefault(key, (a["kind"], a["label"], key, "actors", "{}"))
        return key

    def node(self, id_: str, kind: str, label: str, origin: str, data: dict) -> str:
        self.entities.setdefault(id_, (kind, label, None, origin, json.dumps(data, ensure_ascii=False)))
        return id_

    def tie(self, a: str, b: str, rel: str, back: str, layer: str, evidence: dict, date: str = "", weight: int = 1):
        if a == b:
            return
        k = (a, b, rel, layer)
        if k not in self.ties:
            self.ties[k] = [a, b, rel, back, layer, date or None, weight, json.dumps(evidence, ensure_ascii=False)]


def _canon() -> dict[str, str]:
    """"US:36" → actor key, for list entries the sanctions matching tied to one actor – or to one by the entry's own
    name and others only by its aliases (OFAC's HIZBALLAH is Hezbollah, not the groups named like its aliases)."""
    out, seen = {}, {}
    for key, ms in sanctions.data().get("actors", {}).items():
        for m in ms:
            seen.setdefault(f"{m['list']}:{m['ref']}", {})[key] = m["via"]
    for ref, keys in seen.items():
        own = [k for k, via in keys.items() if via == "name"]
        if len(keys) == 1 or len(own) == 1:
            out[ref] = own[0] if own else next(iter(keys))
    return out


def _target_names(name: str) -> list[str]:
    """OFAC writes a linked person "PATINO FOMEQUE, Victor Julio"; its entries read "Victor Julio PATINO FOMEQUE"."""
    out = [sanctions.normalise(name)]
    if "," in name:
        last, _, first = name.partition(",")
        out.append(sanctions.normalise(f"{first} {last}"))
    return out


def _usable(name: str, entry: dict, alias: bool) -> str:
    """The normalised name if it may be looked for in a narrative, else ''."""
    n = sanctions.normalise(name)
    words = n.split()
    if len(n) < MIN_NAME or actors.is_generic(tuple(words)):
        return ""                           # "Ministry of Defence": which country's?
    if entry["type"] == "person" or len(words) == 1:
        if len(words) < 2 and (entry["type"] != "group" or alias):
            return ""                       # one word: only a group's or company's own primary name (vessels are named after places)
        if alias and words[0] in sanctions.KUNYA and len(words) < 3:
            return ""                       # "Abu Obeida": a nom de guerre many men use
    return n


ABBREV = re.compile(r"(?:^|\W)(?:No|Nos|Mr|Mrs|Ms|Dr|St|Gen|Col|Lt|Maj|Capt|Jr|Sr|Inc|Ltd|Co|Corp|approx|e\.g|i\.e|[A-Z])\.$")


def _sentences(text: str) -> list[str]:
    """Sentences of a listing's narrative; a full stop after "No", "Mr", an initial … does not end one."""
    out = []
    for line in re.split(r"\n+", text or ""):
        for part in re.split(r"(?<=[.;!?])\s+(?=[A-Z“\"(])", line):
            part = " ".join(part.split())
            if not part:
                continue
            if out and out[-1][1] and ABBREV.search(out[-1][0]):
                out[-1][0] += " " + part
            else:
                out.append([part, True])
        if out:
            out[-1][1] = False            # a new line always starts a new sentence
    return [s for s, _ in out]


def _label(lst: str, e: dict) -> str:
    """The entry's name as the list writes it; for the EU list its first original or English name in Latin script."""
    if lst == "EU":
        latin = [n for n in e["names"] if n and sum(c.isascii() for c in n if c.isalpha()) >= 0.8 * sum(c.isalpha() for c in n)]
        if latin:
            return latin[0]
    return e["name"] or e["ref"]


def _capitalised(word: str, sentence: str) -> bool:
    """A one-word name counts only where the text writes it as a name ("Rostec", not "prosperity")."""
    return any(m.group(0)[0].isupper() for m in re.finditer(r"\w+", sentence) if sanctions.normalise(m.group(0)) == word)


def _quote(s: str) -> str:
    return s if len(s) <= QUOTE else s[:QUOTE].rsplit(" ", 1)[0] + " …"


class _Targets:
    """List entries → the target they describe (rozvedka/identity.py): one node per person, company or vessel, whichever
    lists name it; the node of the actor where the sanctions matching tied an entry to one."""

    def __init__(self, g: _Graph, entries: dict[str, dict], canon: dict[str, str]):
        self.g, self.entries, self.canon = g, entries, canon
        self.root, self.reasons = identity.clusters(entries, canon)
        self.members: dict[str, list] = {}
        for k, r in self.root.items():
            self.members.setdefault(r, []).append(k)
        self.node_of: dict[str, str] = {}

    def node(self, key: str) -> str:
        if key in self.node_of:
            return self.node_of[key]
        ms = sorted(self.members[self.root[key]], key=lambda m: identity.LIST_ORDER.index(m.split(":")[0]))
        actor = next((self.canon[m] for m in ms if self.canon.get(m) in self.g.actors), None)
        if actor:
            nid = self.g.actor(actor)
        else:
            first = self.entries[ms[0]]
            lst = ms[0].split(":")[0]
            # the label: UK's name first (English, often in mixed case), written as a name rather than in capitals where one is
            named = [_label(m.split(":")[0], self.entries[m]) for m in sorted(ms, key=lambda m: LABEL_ORDER.index(m.split(":")[0]))]
            label = next((n for n in named if not n.isupper()), named[0])
            data = {"list": lst, "ref": first["ref"], "programme": first["programme"], "date": first["date"],
                    "url": first["url"] or sanctions.LISTS[lst]["page"], "names": first["names"][:12]}
            if len(ms) > 1:
                data["members"] = [{"list": m.split(":")[0], "ref": self.entries[m]["ref"], "name": self.entries[m]["name"],
                                    "programme": self.entries[m]["programme"], "date": self.entries[m]["date"],
                                    "url": self.entries[m]["url"] or sanctions.LISTS[m.split(":")[0]]["page"]} for m in ms]
                data["why"] = self.reasons.get(self.root[key], [])
            det = [self.entries[m]["details"] for m in ms]
            data["dob"] = sorted({x for d in det for x in d["dob"]})
            data["ids"] = sorted({tuple(i) for d in det for i in d["ids"]})[:20]
            data["addresses"] = [a for i, a in enumerate(x for d in det for x in d["addresses"]) if i < 8]
            nid = self.g.node(ms[0], SHAPES.get(first.get("shape"), "person" if first["type"] == "person" else "org"),
                              label, lst.lower(), data)
        for m in ms:
            self.node_of[m] = nid
        return nid


def _entry_node(g: _Graph, targets: _Targets, lst: str, e: dict) -> str:
    return targets.node(f"{lst}:{e['ref']}")


def _from_details(g: _Graph, targets: _Targets, stats: dict) -> None:
    """Shared addresses, e-mails, websites, telephone numbers and wallets; the UK list's parents, subsidiaries, owners."""
    n = 0
    for nid, kind, label, given in identity.detail_nodes(targets.entries, targets.root):
        g.node(nid, kind, label, "ids", {"given_by": len(given)})
        for key, rel in given:
            e = targets.entries[key]
            lst = key.split(":")[0]
            g.tie(targets.node(key), nid, rel, DETAIL_BACK[kind], "ids",
                  {"list": lst, "ref": e["ref"], "url": e["url"] or sanctions.LISTS[lst]["page"], "quote": f"{KINDS[kind]}: {label}"})
            n += 1
    names: dict[str, set] = {}
    bare: dict[str, set] = {}             # without legal forms: the UK list names owners short ("SOVCOMFLOT")
    for key, e in targets.entries.items():
        if e["type"] == "person":
            continue
        for nm in e["names"]:
            names.setdefault(sanctions.normalise(nm), set()).add(targets.root[key])
            if len(identity.bare(nm)) >= 5:
                bare.setdefault(identity.bare(nm), set()).add(targets.root[key])
    unresolved, shared = 0, {}
    for key, e in targets.entries.items():
        if not key.startswith("UK:"):
            continue
        d = e["details"]
        for field, rel, back, what in (("parents", "subsidiary of", "parent company of", "Parent company"),
                                       ("subsidiaries", "parent company of", "subsidiary of", "Subsidiary"),
                                       ("owners", "owned or operated by", "owns or operates", "Current owner/operator")):
            for name in d[field]:
                roots = (names.get(sanctions.normalise(name)) or bare.get(identity.bare(name)) or set()) - {targets.root[key]}
                ev = {"list": "UK", "ref": e["ref"], "url": sanctions.LISTS["UK"]["page"], "quote": f"{what}: {name.strip()}"}
                if len(roots) == 1:
                    g.tie(targets.node(key), targets.node(next(iter(roots))), rel, back, "uk", ev)
                else:
                    unresolved += 1
                    shared.setdefault(sanctions.normalise(name), []).append((key, name.strip(), rel, back, ev, len(roots)))
    for norm, refs in shared.items():          # not on any list, but named by two entries or more: a shared owner or parent
        if len({targets.root[k] for k, *_ in refs}) < 2 or len(norm) < 4:
            continue
        nid = g.node(f"uk-name:{norm}", "org", refs[0][1], "uk", {"named_by": len(refs), "candidates": max(r[5] for r in refs)})
        for key, _, rel, back, ev, _ in refs:
            g.tie(targets.node(key), nid, rel, back, "uk", ev)
    merged = {r: ms for r, ms in targets.members.items() if len(ms) > 1}
    stats["ids"] = {"ties": n, "unresolved_names": unresolved,
                    "targets_merged": len(merged), "entries_merged": sum(len(ms) for ms in merged.values()),
                    "reasons": dict(Counter(" ".join(w.split()[:2]) for v in targets.reasons.values() for _, _, w in v))}


def _from_lists(g: _Graph, stats: dict) -> None:
    canon = _canon()
    per_list = {lst: list(sanctions._entries(sanctions.DIR / spec["file"], lst))
                for lst, spec in sanctions.LISTS.items() if (sanctions.DIR / spec["file"]).exists()}
    targets = _Targets(g, {f"{lst}:{e['ref']}": e for lst, es in per_list.items() for e in es}, canon)
    for lst, spec in sanctions.LISTS.items():
        if lst not in per_list:
            continue
        layer = LIST_LAYER[lst]
        entries = per_list[lst]
        by_ref = {e["ref"]: e for e in entries}
        unresolved = 0
        if lst == "US":
            index: dict[str, set] = {}
            for e in entries:
                for nm in e["names"]:
                    index.setdefault(sanctions.normalise(nm), set()).add(e["ref"])
            for e in entries:
                for target in e["linked"]:
                    refs = next((index[n] for n in _target_names(target) if n in index), set())
                    if len(refs) != 1:
                        unresolved += 1
                        continue
                    other = by_ref[next(iter(refs))]
                    g.tie(_entry_node(g, targets, lst, e), _entry_node(g, targets, lst, other), "linked to", "linked to it", layer,
                          {"list": lst, "ref": e["ref"], "url": e["url"], "quote": f"Linked To: {target}"})
        else:
            names: dict[str, set] = {}
            for e in entries:
                for i, nm in enumerate(e["names"]):
                    n = _usable(nm, e, i >= e["primary"])
                    if n:
                        names.setdefault(n, set()).add(e["ref"])
            first = {n.split()[0] for n in names}
            longest = max((len(n.split()) for n in names), default=0)
            for e in entries:
                if not e["text"]:
                    continue
                own = {sanctions.normalise(nm) for nm in e["names"]}
                for sentence in _sentences(e["text"]):
                    words = sanctions.normalise(sentence).split()
                    found, i = {}, 0
                    while i < len(words):
                        step = 1
                        if words[i] in first:
                            for n in range(min(longest, len(words) - i), 0, -1):
                                gram = " ".join(words[i:i + n])
                                if gram in names and (n > 1 or _capitalised(gram, sentence)):
                                    refs = names[gram]
                                    if len(refs) == 1 and gram not in own:
                                        found.setdefault(next(iter(refs)), gram)
                                    elif len(refs) > 1:
                                        unresolved += 1
                                    step = n
                                    break
                        i += step
                    if lst == "UN":
                        for m in UN_REF.findall(sentence):
                            if m in by_ref:
                                found.setdefault(m, m)
                    for ref, as_ in found.items():
                        if ref == e["ref"]:
                            continue
                        g.tie(_entry_node(g, targets, lst, e), _entry_node(g, targets, lst, by_ref[ref]),
                              "names in its listing", "named in the listing of", layer,
                              {"list": lst, "ref": e["ref"], "url": e["url"] or spec["page"], "quote": _quote(sentence),
                               "found": as_},
                              e["date"])
        stats[layer] = {"entries": len(entries), "unresolved": unresolved}
    _from_details(g, targets, stats)


def _from_gazetteer(g: _Graph, con) -> None:
    ents = {r["qid"]: dict(r) for r in con.execute("SELECT * FROM link_entities")}

    def end(k):
        if k in g.actors:
            return g.actor(k)
        e = ents.get(k)
        if not e:
            return None
        return g.node(k, "person" if e["human"] else "org", e["label"] or k, "wikidata",
                      {"description": e["description"], "wikipedia": e["wikipedia"],
                       "url": f"https://www.wikidata.org/wiki/{k}"})

    for r in con.execute("SELECT * FROM actor_links"):
        a, b = end(r["a"]), end(r["b"])
        src = json.loads(r["source"] or "{}")
        layer = "wikipedia" if src.get("type") == "wikipedia" else "wikidata"
        if a and b:
            ev = {"url": src.get("revision_url") or src.get("url"), "source": src}
            if r["role"]:
                ev["role"] = r["role"]
            g.tie(a, b, r["a_says"], r["b_says"], layer, ev, r["start"] or "")


def _from_attack(g: _Graph) -> int:
    cat = techniques._catalog()
    if not cat.get("relations"):
        return 0
    by_attack = {}
    for k, a in g.actors.items():
        gid = (json.loads(a["data"] or "{}").get("attack") or {}).get("id")
        if gid:
            by_attack[gid] = k
    soft, camps, groups = cat.get("software", {}), cat.get("campaigns", {}), cat.get("groups", {})
    retrieved = (cat.get("meta") or {}).get("retrieved")

    def end(x):
        if x in by_attack:
            return g.actor(by_attack[x])
        if x in soft:
            s = soft[x]
            return g.node(x, s["type"], s["name"], "attack", {"url": s["url"], "aliases": s["aliases"], "attack": x})
        if x in camps:
            c = camps[x]
            return g.node(x, "campaign", c["name"], "attack", {"url": c["url"], "first": c["first"], "last": c["last"], "attack": x})
        if x in groups:
            return g.node(x, "cyber", groups[x], "attack", {"url": f"https://attack.mitre.org/groups/{x}/", "attack": x})
        return None

    n = 0
    for src, rel, dst, text in cat["relations"]:
        a, b = end(src), end(dst)
        if not (a and b):
            continue
        url = (soft.get(src) or camps.get(src) or {}).get("url") or f"https://attack.mitre.org/groups/{src}/"
        if rel == "uses":
            g.tie(a, b, "uses", "used by", "attack", {"url": url, "quote": text, "retrieved": retrieved})
        else:
            g.tie(a, b, "attributed to", "campaigns attributed to it", "attack", {"url": url, "quote": text, "retrieved": retrieved},
                  camps.get(src, {}).get("first", ""))
        n += 1
    return n


def _from_reports(g: _Graph, con) -> None:
    """The same count the pair page shows (rozvedka/actors.py pair_detail without filters)."""
    where, args, _ = trends.scope()
    for r in con.execute(
            f"""SELECT p.a, p.b, COUNT(DISTINCT p.doc_id) n, MIN(d.year) y0 FROM actor_pairs p
                JOIN documents d ON d.id=p.doc_id JOIN sources s ON s.id=d.source_id JOIN doc_index i ON i.doc_id=d.id
                JOIN actors a1 ON a1.key=p.a JOIN actors a2 ON a2.key=p.b
                WHERE {where} AND {PAIR_FOUNDED} AND a1.kind != 'country' AND a2.kind != 'country'
                GROUP BY p.a, p.b HAVING COUNT(DISTINCT p.doc_id) >= ?""", (*args, MIN_TOGETHER)):
        g.tie(g.actor(r["a"]), g.actor(r["b"]), "named together with", "named together with", "reports",
              {"docs": r["n"], "link": f"/actors/{r['a']}/with/{r['b']}"}, str(r["y0"] or ""), r["n"])


def build() -> dict:
    """Rebuild entities and ties from the stored lists, gazetteer, ATT&CK catalog and actor index."""
    init()
    with db.session() as con:
        actors.init()
        g = _Graph({r["key"]: dict(r) for r in con.execute("SELECT key, kind, label, data FROM actors")})
        stats: dict = {}
        _from_lists(g, stats)
        _from_gazetteer(g, con)
        stats["attack"] = {"relations": _from_attack(g)}
        _from_reports(g, con)
        con.execute("DELETE FROM ties")
        con.execute("DELETE FROM entities")
        con.executemany("INSERT INTO entities VALUES (?,?,?,?,?,?)", [(k, *v) for k, v in g.entities.items()])
        con.executemany("INSERT INTO ties(a,b,rel,back,layer,date,weight,evidence) VALUES (?,?,?,?,?,?,?,?)", g.ties.values())
        cat = techniques.meta() or {}
        meta = {"built": dt.datetime.now().isoformat(timespec="seconds"), "stats": stats,
                "retrieved": {**{LIST_LAYER[k]: v for k, v in (sanctions.data().get("retrieved") or {}).items()},
                              "attack": cat.get("retrieved"), **dict.fromkeys(("wikidata", "wikipedia"), actors.stamp().get("gazetteer_retrieved"))}}
        con.execute("INSERT OR REPLACE INTO ties_meta VALUES ('meta', ?)", (json.dumps(meta),))
    counts: dict[str, int] = {}
    for t in g.ties.values():
        counts[t[4]] = counts.get(t[4], 0) + 1
    return {"entities": len(g.entities), "ties": len(g.ties), "by_layer": counts,
            "unresolved": {k: v.get("unresolved") for k, v in stats.items() if "unresolved" in v}}


# ── reading ──
def meta() -> dict:
    with db.session() as con:
        init()
        r = con.execute("SELECT v FROM ties_meta WHERE k='meta'").fetchone()
    return json.loads(r[0]) if r else {}


def ties_url(**params) -> str:
    return "/graph/ties?" + "&".join(f"{k}={v}" for k, v in params.items() if v not in ("", None))


def entity_url(id_: str, actor: str | None = None) -> str:
    return f"/actors/{actor}" if actor else f"/entity/{id_}"


@db.cached
def summary() -> dict:
    """Per layer: ties and entities; the totals."""
    with db.session() as con:
        init()
        rows = {r["layer"]: dict(r) for r in con.execute(
            "SELECT layer, COUNT(*) ties FROM ties GROUP BY layer")}
        ents = {r["layer"]: r["n"] for r in con.execute(
            """SELECT layer, COUNT(*) n FROM (SELECT a e, layer FROM ties UNION SELECT b, layer FROM ties) GROUP BY layer""")}
        total_e = con.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        kinds = dict(con.execute("SELECT kind, COUNT(*) FROM entities GROUP BY kind").fetchall())
        multi = con.execute(
            """SELECT COUNT(*) FROM (SELECT e FROM (SELECT a e, layer FROM ties UNION SELECT b, layer FROM ties)
               GROUP BY e HAVING COUNT(DISTINCT layer) >= 3)""").fetchone()[0]
    layers = [{"key": k, **v, "ties": rows.get(k, {}).get("ties", 0), "entities": ents.get(k, 0),
               "link": ties_url(layer=k)} for k, v in LAYERS.items()]
    return {"layers": layers, "ties": sum(l["ties"] for l in layers), "entities": total_e, "kinds": kinds,
            "multi": multi, "groups": GROUPS}


def _layer_clause(layers) -> tuple[str, list]:
    layers = [l for l in (layers or []) if l in LAYERS]
    if not layers:
        return "1=1", []
    return f"layer IN ({','.join('?' * len(layers))})", layers


@db.cached
def ranking(group: str = "official", kind: str = "", limit: int = 30) -> list[dict]:
    """Entities with the most distinct neighbours in one group of layers (official lists by default)."""
    layers = [k for k, v in LAYERS.items() if v["group"] == group] if group in GROUPS else list(LAYERS)
    cl, args = _layer_clause(layers)
    with db.session() as con:
        init()
        rows = [dict(r) for r in con.execute(
            f"""SELECT x.e id, COUNT(DISTINCT x.o) n, COUNT(*) nt, COUNT(DISTINCT x.layer) nl, e.label, e.kind, e.actor
                FROM (SELECT a e, b o, layer FROM ties WHERE {cl} UNION ALL SELECT b, a, layer FROM ties WHERE {cl}) x
                JOIN entities e ON e.id=x.e WHERE (? = '' OR e.kind = ?)
                GROUP BY x.e ORDER BY n DESC, e.label LIMIT ?""", (*args, *args, kind, kind, limit))]
    for r in rows:
        r["href"] = entity_url(r["id"], r["actor"])
        r["link"] = ties_url(entity=r["id"], group=group if group in GROUPS else "")
    return rows


@db.cached
def crossroads(limit: int = 30) -> list[dict]:
    """Entities tied in the most different layers – where official lists, reference data and the reports meet."""
    with db.session() as con:
        init()
        rows = [dict(r) for r in con.execute(
            """SELECT x.e id, COUNT(DISTINCT x.layer) nl, GROUP_CONCAT(DISTINCT x.layer) layers, COUNT(*) n,
                      e.label, e.kind, e.actor
               FROM (SELECT a e, layer FROM ties UNION ALL SELECT b, layer FROM ties) x JOIN entities e ON e.id=x.e
               GROUP BY x.e HAVING nl >= 3 ORDER BY nl DESC, n DESC LIMIT ?""", (limit,))]
    for r in rows:
        r["layers"] = [l for l in LAYERS if l in r["layers"].split(",")]
        r["href"] = entity_url(r["id"], r["actor"])
        r["link"] = ties_url(entity=r["id"])
    return rows


def _where(entity: str = "", layer: str = "", group: str = "", q: str = "", kind: str = "") -> tuple[str, list]:
    where, args = ["1=1"], []
    if entity:
        where.append("(t.a=? OR t.b=?)"); args += [entity, entity]
    if layer in LAYERS:
        where.append("t.layer=?"); args.append(layer)
    elif group in GROUPS:
        ls = [k for k, v in LAYERS.items() if v["group"] == group]
        where.append(f"t.layer IN ({','.join('?' * len(ls))})"); args += ls
    if q.strip():
        where.append("(ea.label LIKE ? OR eb.label LIKE ?)"); args += [f"%{q.strip()}%"] * 2
    if kind:
        where.append("(ea.kind=? OR eb.kind=?)"); args += [kind, kind]
    return " AND ".join(where), args


FROM = "FROM ties t JOIN entities ea ON ea.id=t.a JOIN entities eb ON eb.id=t.b"


def count(**f) -> int:
    where, args = _where(**f)
    with db.session() as con:
        init()
        return con.execute(f"SELECT COUNT(*) {FROM} WHERE {where}", args).fetchone()[0]


def others(**f) -> int:
    """How many different entities the listed ties lead to (with an entity filter: its neighbours)."""
    where, args = _where(**f)
    e = f.get("entity")
    with db.session() as con:
        init()
        if e:
            return con.execute(f"SELECT COUNT(DISTINCT CASE WHEN t.a=? THEN t.b ELSE t.a END) {FROM} WHERE {where}",
                               (e, *args)).fetchone()[0]
        return con.execute(f"SELECT COUNT(*) FROM (SELECT t.a x {FROM} WHERE {where} UNION SELECT t.b {FROM} WHERE {where})",
                           (*args, *args)).fetchone()[0]


def _row(r, seen_from: str = "") -> dict:
    d = dict(r)
    d["evidence"] = json.loads(d["evidence"] or "{}")
    d["layer_name"] = LAYERS[d["layer"]]["name"]
    d["layer_group"] = LAYERS[d["layer"]]["group"]
    d["a_href"], d["b_href"] = entity_url(d["a"], d["a_actor"]), entity_url(d["b"], d["b_actor"])
    if seen_from and d["b"] == seen_from:            # read from the entity's side: "it <back> other"
        d.update(other=d["a"], other_label=d["a_label"], other_kind=d["a_kind"], other_href=d["a_href"], says=d["back"])
    elif seen_from:
        d.update(other=d["b"], other_label=d["b_label"], other_kind=d["b_kind"], other_href=d["b_href"], says=d["rel"])
    return d


SELECT = """SELECT t.*, ea.label a_label, ea.kind a_kind, ea.actor a_actor, eb.label b_label, eb.kind b_kind,
                   eb.actor b_actor"""


def tie_list(entity: str = "", layer: str = "", group: str = "", q: str = "", kind: str = "", offset: int = 0,
             limit: int = 100) -> list[dict]:
    where, args = _where(entity, layer, group, q, kind)
    with db.session() as con:
        init()
        rows = con.execute(f"""{SELECT} {FROM} WHERE {where}
                               ORDER BY t.layer = 'reports', t.weight DESC, ea.label, eb.label LIMIT ? OFFSET ?""",
                           (*args, limit, offset)).fetchall()
    return [_row(r, entity) for r in rows]


def entity(id_: str) -> dict | None:
    with db.session() as con:
        init()
        r = con.execute("SELECT * FROM entities WHERE id=?", (id_,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["data"] = json.loads(d["data"] or "{}")
    d["kind_name"] = KINDS.get(d["kind"], d["kind"])
    return d


PER_GROUP = 25          # ties shown per layer and relation on an entity or actor page; the rest behind "all"


def neighbours(id_: str, skip=()) -> list[dict]:
    """The entity's ties grouped by layer and by relation as seen from it; each group with its total and list link."""
    with db.session() as con:
        init()
        rows = [_row(r, id_) for r in con.execute(
            f"""{SELECT} {FROM} WHERE (t.a=? OR t.b=?) ORDER BY t.weight DESC, ea.label, eb.label""", (id_, id_))]
    out = []
    for layer, spec in LAYERS.items():
        if layer in skip:
            continue
        mine = [r for r in rows if r["layer"] == layer]
        if not mine:
            continue
        rels: dict[str, list] = {}
        for r in mine:
            rels.setdefault(r["says"], []).append(r)
        out.append({"layer": layer, **spec, "n": len(mine), "link": ties_url(entity=id_, layer=layer),
                    "rels": [{"says": s, "n": len(v), "rows": v[:PER_GROUP]} for s, v in
                             sorted(rels.items(), key=lambda x: -len(x[1]))]})
    return out


def layer_counts(id_: str) -> list[dict]:
    with db.session() as con:
        init()
        got = dict(con.execute("SELECT layer, COUNT(*) FROM ties WHERE a=? OR b=? GROUP BY layer", (id_, id_)).fetchall())
    return [{"layer": k, "name": v["name"], "group": v["group"], "n": got[k], "link": ties_url(entity=id_, layer=k)}
            for k, v in LAYERS.items() if got.get(k)]


def figures() -> list[tuple[str, int, str]]:
    """(label, number, link) of the Network page's numbers, for tools/check_links.py."""
    s = summary()
    out = [(f"layer {l['key']}", l["ties"], l["link"]) for l in s["layers"] if l["ties"]]
    for r in crossroads(10):
        out.append((f"crossroads {r['label']}", r["n"], r["link"]))
    for r in ranking("official", "", 10):
        out.append((f"most linked {r['label']} (others)", -r["n"], r["link"]))      # negative: compare with "others"
    return out


def paged(entity: str = "", layer: str = "", group: str = "", q: str = "", kind: str = "", page="1", per_page="") -> dict:
    size = paging.per_page_of(per_page, 50)
    f = {"entity": entity, "layer": layer, "group": group, "q": q, "kind": kind}
    total = count(**f)
    pg = paging.paginate(total, page, size, "/graph/ties", {**f, "per_page": size if size != 50 else ""}, default=50)
    return {"rows": tie_list(**f, offset=pg["offset"], limit=size), "pg": pg, "total": total, "f": f,
            "others": others(**f) if total else 0,
            "focus": entity_view(entity) if entity else None}


def entity_view(id_: str) -> dict | None:
    e = entity(id_)
    if e:
        e["href"] = entity_url(e["id"], e["actor"])
    return e
