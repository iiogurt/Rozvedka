"""Document types: what kind of publication a file is – annual report, assessment, strategy, bulletin, guide,
another report, or not a report at all (statement, law or regulation, finance table, form). Found by transparent
rules on the title and file name (words in the languages of the library), series membership and page count; each
file keeps the rule that typed it. Hand corrections in sources/doc_types.yaml win over the rules.

Statements, laws and regulations, finance tables and forms stay in the library and on Documents, but the counts,
charts and dashboards leave them out by default (trends.LISTED), as they leave out hidden files."""
import datetime as dt
import logging
import re
from pathlib import Path

import yaml

from . import db, topics
from .config import ROOT

log = logging.getLogger("rozvedka.doctypes")

TYPES = {   # key → (label, counted as a report)
    "annual": ("Annual / periodic report", True),
    "assessment": ("Threat / risk assessment", True),
    "strategy": ("Strategy / white paper", True),
    "bulletin": ("Bulletin / warning", True),
    "guide": ("Guide / factsheet", True),
    "report": ("Other report", True),
    "statement": ("Statement / press release", False),
    "legal": ("Law / regulation", False),
    "finance": ("Budget / accounts table", False),
    "form": ("Form", False),
}
NOT_REPORTS = tuple(k for k, (_, counted) in TYPES.items() if not counted)
# SQL: a file counted as a report (untyped files count, so nothing disappears before typing has run)
COUNTED = f"(d.doc_type IS NULL OR d.doc_type NOT IN ({','.join(repr(k) for k in NOT_REPORTS)}))"

# Rules in order; the first that matches the folded title + file name wins. Words are matched at a word start.
RULES = [
    ("form", r"\b(form(ular|ulaire|ulario|ulář|ularz)?|obrazac|lomake|blankett|application form|antrag)\b"),
    ("legal", r"^\d{1,3}/\d{2}[,.]? \||\b(zakon|zakona|zakonu|uredba|uredbe|pravilnik\w*|naredb\w*|odluk[aeu] o|nn ?\d{1,3} \d{2,4}|"
              r"narodne novine|uradni list|gesetz|umsetzungsgesetz|verordnung|richtlinie \(eu\)|directive \(eu\)|"
              r"regulation \(eu\)|act on the|decreto|real decreto|ley organica|zakon o|zakonik|ustawa|rozporzadzeni\w*|"
              r"zakon c|vyhlask\w*|narizeni vlady|nariadeni\w* vlady|loi n|loi relative|arrete|wetsvoorstel|besluit)\b"),
    ("finance", r"\b(budget|rozpocet|rozpoct\w*|zaverecn\w* uc\w*|vykaz\w*|ukazovatel\w*|tabulka|tab \d|financial statement|"
                r"accounts|jahresrechnung|haushalt\w*|bilancio|presupuesto|begroting|talousarvio|zaverecny_ucet|"
                r"audited annual report|poseur.\d+|poci.\d+|pt.20\d\d.fsi|ficha de projeto)\b"),
    ("statement", r"\b(press (release|notice|statement|conference)|statement|remarks|speech|"
                  r"tiskov\w* zprav\w*|pressemitteilung|communique|persbericht|comunicado|komunikat|"
                  r"verklaring|motie|stemming|kamerbrief|toespraak|discours|written ministerial statement|wms)\b"),
    ("assessment", r"\b(threat assessment|risk assessment|risk analysis|national risk|risk profile|threat landscape|"
                   r"lagebild|lagebericht|gefahrdungs\w*|risikoanalyse|risicoanalyse|risicobeeld|dreigingsbeeld|"
                   r"cybersecuritybeeld|dreigings\w*|trusselsvurdering|trusselvurdering|trusselbilde|hotbild|"
                   r"hotbedomning|uhkakuva|ohu\w* hinnang|evaluation de la menace|etat de la menace|panorama de la "
                   r"(cyber)?menace|valutazione (del|della) (rischio|minaccia)|evaluacion de riesgo\w*|"
                   r"analisis de riesgo\w*|ocena zagrozen|ocen\w* rizik\w*|hodnoceni hrozeb|analyza rizik|"
                   r"riskbedomning|risikovurdering|riskikuva|kockazat\w*|procjen\w* rizik\w*|ocena tveganj|"
                   r"te.sat|iocta|soc ta|horizon scan\w*|threat outlook|security outlook|global trends|"
                   r"annual threat|worldwide threat|homeland threat|threat report|risikobilde|nasjonalt risikobilde)\b"),
    ("annual", r"\b(annual report|annual review|year in review|yearbook|vyrocni zprav\w*|vyrocn\w*|jahresbericht|"
               r"verfassungsschutzbericht|rapport annuel|rapport d.activite\w*|informe anual|memoria anual|"
               r"relazione annuale|relazione sulla politica|relatorio anual|relatorio de atividades|jaarverslag|"
               r"raport roczny|raport vjetor|raport de activitate|sprawozdanie|vuosikertomus|arsrapport|arsberetning|"
               r"arsredovisning|aastaraamat|aastaulevaade|parskats|metine|godisnje izvjesce|letno porocilo|"
               r"annual|vyrocni|godisnj\w*|evkonyv|white paper on|hakusho|halbjahresbericht|semi.annual|polrocn\w*)\b|白書"),
    ("strategy", r"\b(strateg(y|ies|ie|ia|ias|ija|ije|iji|iju|ii|i|iei)|white paper|white book|weissbuch|livre blanc|libro blanco|libro bianco|witboek|"
                 r"bialej ksiegi|biala ksiega|bila kniha|national security policy|defence policy|"
                 r"doctrine|konzeption|koncepc\w*)\b"),
    ("bulletin", r"\b(bulletin|warning|varovani|advisory|alert|newsletter|flash|situation report|sitrep|"
                 r"reporte (preliminar|complementario|de situacion)|quarter\w*|quartal\w*|ctvrtlet\w*|kwartaal\w*|"
                 r"monthly|mensual|monatlich|week(ly)?)\b"),
    ("guide", r"\b(guide\w*|guidance|handbook|manual|leitfaden|ratgeber|prirucka|handreichung|merkblatt|checklist|"
              r"factsheet|fact sheet|faktenblatt|flyer|leaflet|brochure|broschure|infographic|poster|tips|"
              r"recommendation\w*|doporuceni|empfehlung\w*|best practice\w*|faq|guia|vodic|vadovas|opas|vejledning|"
              r"veiledning|handbok|what is|was macht)\b"),
]
_RULES = [(k, re.compile(rx)) for k, rx in RULES]
SHORT = 4          # pages: below this, an untyped file is not called a report on page count alone
TYPES_FILE = ROOT / "sources" / "doc_types.yaml"
HEADER = """# Document types set by hand – corrections to the rules in rozvedka/doctypes.py. Each entry: the report (official
# URL), the type and when it was set. Written by the portal (report page → type); editable by hand.
"""


def text_of(title: str, url: str) -> str:
    """Folded title and file name, separators turned into spaces (…/Spionage-Faktenblatt-de.pdf → spionage faktenblatt de)."""
    from urllib.parse import unquote, urlsplit
    name = unquote(urlsplit(url or "").path).rsplit("/", 1)[-1]
    name = re.sub(r"\.(pdf|docx?|epub|html?)$", "", name, flags=re.I)
    return topics.normalize(f"{title or ''} | {re.sub(r'[-_.]+', ' ', name)}")


def classify(title: str, url: str, pages: int | None, series_per_year: int | None = None) -> tuple[str, str]:
    """(type, why) for one file."""
    text = text_of(title, url)
    for key, rx in _RULES:
        m = rx.search(text)
        if m:
            if key == "annual" and m.group(0) in ("annual", "vyrocni") and pages is not None and pages < SHORT:
                continue        # "annual" alone on a 2-page file: a notice about the annual report, not the report
            return key, f"“{m.group(0)}” in the title or file name"
    if series_per_year:
        return ("annual" if series_per_year <= 4 else "bulletin"), f"an edition of a report series ({series_per_year}× a year)"
    if pages is not None and pages < SHORT:
        return "report", f"no rule matched; {pages} page{'s' if pages != 1 else ''}"
    return "report", "no rule matched"


def load_hand(path: Path | None = None) -> dict[str, dict]:
    path = path or TYPES_FILE
    if not path.exists():
        return {}
    return {r["url"]: r for r in (yaml.safe_load(path.read_text(encoding="utf-8")) or []) if isinstance(r, dict) and r.get("url")}


def save_hand(rows: dict[str, dict], path: Path | None = None) -> None:
    path = path or TYPES_FILE
    path.write_text(HEADER + yaml.safe_dump(list(rows.values()), allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def set_by_hand(doc_id: int, doc_type: str) -> bool:
    if doc_type not in TYPES:
        return False
    with db.session() as con:
        r = con.execute("SELECT url FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not r:
            return False
        con.execute("UPDATE documents SET doc_type=?, doc_type_why='set by hand' WHERE id=?", (doc_type, doc_id))
    rows = load_hand()
    rows[r["url"]] = {"url": r["url"], "type": doc_type, "set": dt.datetime.now().isoformat(" ", "seconds")}
    save_hand(rows)
    return True


def type_documents() -> dict:
    """Type every file (cheap: titles and addresses only); hand corrections win."""
    from . import series
    per_year = {}
    for doc_id, e in series.doc_index().items():
        s = series.get(e["id"])
        per_year[doc_id] = s.get("per_year", 1) if s else 1
    hand = load_hand()
    counts: dict[str, int] = {}
    with db.session() as con:
        rows = con.execute("SELECT id, title, url, pages_count FROM documents").fetchall()
        out = []
        for r in rows:
            if r["url"] in hand and hand[r["url"]].get("type") in TYPES:
                t, why = hand[r["url"]]["type"], "set by hand"
            else:
                t, why = classify(r["title"], r["url"], r["pages_count"], per_year.get(r["id"]))
            out.append((t, why, r["id"]))
            counts[t] = counts.get(t, 0) + 1
        con.executemany("UPDATE documents SET doc_type=?, doc_type_why=? WHERE id=?", out)
    log.info("typed %s", counts)
    return counts
