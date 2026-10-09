"""Official attributions: statements in which a government body names a cyber threat group (and the state body behind it).

Hand-written in sources/attributions.yaml, each with a verbatim quote. `fetch-attributions` downloads every page (robots.txt
respected, one request per host every 2 s) and checks that the quote and the aliases listed in `names` are on it; the result
(data/gazetteer/attributions.json, with the retrieval date) is what the portal shows next to each statement. An entry that
is not confirmed is shown as such, never hidden."""
import datetime as dt
import html
import json
import logging
import re
import unicodedata
from functools import lru_cache

import yaml

from . import actors, db, fetch
from .config import DATA, ROOT

log = logging.getLogger(__name__)
FILE = ROOT / "sources" / "attributions.yaml"
CHECKS = DATA / "gazetteer" / "attributions.json"


def normalise(text: str) -> str:
    """Quotes, dashes, spaces and case compared loosely, so a typographic apostrophe does not fail a quote."""
    text = html.unescape(text or "")
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[‘’‚′`´]", "'", text)
    text = re.sub(r"[“”„″]", '"', text)
    text = re.sub(r"[‐‑‒–—―−]", "-", text)
    return " ".join(text.split()).casefold()


def page_text(body: str) -> str:
    body = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", body or "")
    return normalise(re.sub(r"<[^>]+>", " ", body))


def load(path=None) -> list[dict]:
    path = path or FILE
    rows = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("attributions", []) if path.exists() else []
    return sorted((r for r in rows if isinstance(r, dict)), key=lambda r: str(r["date"]), reverse=True)


def check_page(entry: dict, text: str) -> dict:
    """Is the quote (and every alias in `names`) on the page?"""
    quote_ok = normalise(entry["quote"]) in text
    missing = [n for n in entry.get("names", []) if normalise(n) not in text]
    return {"quote": quote_ok, "names_missing": missing, "ok": quote_ok and not missing}


def fetch_all(path=None) -> dict:
    out, bad = {}, 0
    for e in load(path):
        try:
            r = fetch.get(e["url"])
            res = {"status": r.status, **(check_page(e, page_text(r.text)) if r.status == 200 else {"ok": False})}
        except Exception as ex:      # blocked by robots.txt, network error …
            res = {"status": 0, "ok": False, "error": str(ex)[:120]}
        res["checked"] = dt.date.today().isoformat()
        out[e["url"]] = res
        bad += not res["ok"]
        log.info("%s %s", "ok " if res["ok"] else "NOT CONFIRMED", e["url"])
    CHECKS.parent.mkdir(parents=True, exist_ok=True)
    CHECKS.write_text(json.dumps(out, indent=1), encoding="utf-8")
    _checks.cache_clear()
    return {"entries": len(out), "confirmed": len(out) - bad, "not_confirmed": bad}


@lru_cache(maxsize=1)
def _checks_cached(mtime: float) -> dict:
    return json.loads(CHECKS.read_text(encoding="utf-8"))


def _checks() -> dict:
    return _checks_cached(CHECKS.stat().st_mtime) if CHECKS.exists() else {}


_checks.cache_clear = _checks_cached.cache_clear


def _labels(keys: set[str]) -> dict[str, dict]:
    if not keys:
        return {}
    with db.session() as con:
        actors.init()
        return {r["key"]: dict(r) for r in con.execute(
            f"SELECT key, label, kind FROM actors WHERE key IN ({','.join('?' * len(keys))})", list(keys))}


def _decorate(rows: list[dict]) -> list[dict]:
    checks = _checks()
    info = _labels({k for r in rows for k in r["actors"]})
    out = []
    for r in rows:
        c = checks.get(r["url"], {})
        out.append({**r, "date": str(r["date"]),
                    "actor_info": [info[k] for k in r["actors"] if k in info],
                    "check": c, "confirmed": bool(c.get("ok")), "checked": c.get("checked")})
    return out


def of_actor(key: str) -> list[dict]:
    return _decorate([r for r in load() if key in r.get("actors", [])])


def overview() -> dict:
    rows = _decorate(load())
    return {"rows": rows, "n": len(rows), "confirmed": sum(r["confirmed"] for r in rows),
            "checked": max((r["checked"] for r in rows if r["checked"]), default=None)}
