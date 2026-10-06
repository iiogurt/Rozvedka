"""Datasets: the whole library in a few files, to back it up or hand it to someone else – no crawling needed.

    python -m rozvedka export DIR [--no-files] [--since 2026-10-01] [--part-size 2G] [--name LABEL]
    python -m rozvedka import PATH [--check] [--prefer local|dataset] [--no-index]

A dataset is one tar stream cut into parts (`<base>.tar.001`, `.002` …, 2 GB each by default, so they fit the usual
file-transfer services; joined they are an ordinary tar) and `<base>.manifest.json` – who made it, when, with which
app version, how fresh the data is, and the SHA-256 of every part. Inside: the manifest, a consistent copy of the
database (gzip), the report files, logos, the actor gazetteer and the lists the portal writes (series, watchlist,
reviews of actor matches).

Import checks every part, then compares the dataset with this library – newer or older, overall and per source –
and what it would add or change (`--check` stops there). An empty library is restored from the dataset; an
existing one is merged: sources, pages and reports are matched by key and address (ids differ between
installations), missing reports, files, text and OCR are added, the more recent crawl dates kept, and conflicting
hand edits listed (local wins unless `--prefer dataset`). Reports whose file is not in the dataset are marked for
download. The database is copied to data/backups/ first.
"""
import datetime as dt
import gzip
import hashlib
import json
import logging
import shutil
import tarfile
import tempfile
import uuid
from pathlib import Path

import yaml

from . import __version__, config, db, progress

log = logging.getLogger("rozvedka.dataset")
FORMAT = "rozvedka-dataset"
FORMAT_VERSION = 1
PART_SIZE = 2_000_000_000
CHUNK = 1 << 20
PORTAL_LISTS = ("series.yaml", "watchlist.yaml", "actor_reviews.yaml", "year_reviews.yaml")     # written by the portal: merged on import


Cancelled = progress.Cancelled


def _tick(phase: str, done: int = 0, total: int = 0, final: bool = False) -> None:
    """Report progress (and give a running job the chance to stop); `final` marks the point of no return."""
    progress.tick(phase, done, total, final)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def installation() -> dict:
    """This installation's identity (data/installation.json) – kept out of the database, so a restored database
    does not take over the exporter's identity."""
    path = config.DATA / "installation.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    config.DATA.mkdir(parents=True, exist_ok=True)
    info = {"id": uuid.uuid4().hex[:12], "created": _now()}
    path.write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def _sources_dir() -> Path:
    return config.ROOT / "sources"


def _gazetteer_dir() -> Path:
    from . import actor_sources
    return actor_sources.GAZETTEER.parent


def _logos_dir() -> Path:
    from . import logos
    return logos.LOGOS


def freshness(con) -> dict:
    """How fresh a library is: overall and per source (by registry key)."""
    one = lambda sql: con.execute(sql).fetchone()[0]   # noqa: E731
    per = {r[0]: {"last_crawl": r[1], "documents": r[2], "last_discovered": r[3]} for r in con.execute(
        """SELECT s.key, (SELECT MAX(last_crawled) FROM pages p WHERE p.source_id=s.id),
                  (SELECT COUNT(*) FROM documents d WHERE d.source_id=s.id),
                  (SELECT MAX(discovered_at) FROM documents d WHERE d.source_id=s.id) FROM sources s""")}
    return {"last_crawl": one("SELECT MAX(last_crawled) FROM pages"),
            "last_download": one("SELECT MAX(downloaded_at) FROM documents"),
            "last_discovered": one("SELECT MAX(discovered_at) FROM documents"),
            "documents": one("SELECT COUNT(*) FROM documents"),
            "downloaded": one("SELECT COUNT(*) FROM documents WHERE status='downloaded' AND local_path IS NOT NULL"),
            "sources": per}


# ------------------------------------------------------------------ parts: a tar stream cut into files

class _PartWriter:
    """File-like: writes a stream into <base>.tar.001, .002 … of at most `size` bytes, hashing each part."""

    def __init__(self, base: Path, size: int, expected: int = 0):
        self.base, self.size, self.parts, self._f, self._n, self._h = base, size, [], None, 0, None
        self.written, self.expected = 0, expected

    def _open(self):
        self._close()
        path = self.base.with_name(f"{self.base.name}.tar.{len(self.parts) + 1:03d}")
        self._f, self._n, self._h = open(path, "wb"), 0, hashlib.sha256()
        self.parts.append({"name": path.name})

    def _close(self):
        if self._f:
            self._f.close()
            self.parts[-1].update(size=self._n, sha256=self._h.hexdigest())
            self._f = None

    def write(self, b) -> int:
        b, total = memoryview(b), len(b)
        while len(b):
            if self._f is None or self._n >= self.size:
                self._open()
            take = min(len(b), self.size - self._n)
            self._f.write(b[:take]); self._h.update(b[:take]); self._n += take
            b = b[take:]
        self.written += total
        _tick("Writing the dataset", self.written, self.expected)
        return total

    def remove(self):
        """Delete the parts written so far (a cancelled or failed export)."""
        self._close()
        for p in self.parts:
            self.base.with_name(p["name"]).unlink(missing_ok=True)

    def close(self):
        self._close()


class _PartReader:
    """File-like: reads the parts one after the other as one stream."""

    def __init__(self, paths: list[Path], phase: str = "Reading the dataset", total: int = 0):
        self.paths, self.i, self.f = list(paths), 0, None
        self.phase, self.total, self.done = phase, total, 0

    def read(self, n: int = -1) -> bytes:
        out = bytearray()
        while n < 0 or len(out) < n:
            if self.f is None:
                if self.i >= len(self.paths):
                    break
                self.f = open(self.paths[self.i], "rb")
                self.i += 1
            chunk = self.f.read(CHUNK if n < 0 else n - len(out))
            if not chunk:
                self.f.close()
                self.f = None
                continue
            out += chunk
        self.done += len(out)
        _tick(self.phase, self.done, self.total)
        return bytes(out)

    def close(self):
        if self.f:
            self.f.close()


def _add_bytes(tar, name: str, data: bytes):
    info = tarfile.TarInfo(name)
    info.size, info.mtime = len(data), int(dt.datetime.now().timestamp())
    import io
    tar.addfile(info, io.BytesIO(data))


def _sha256(path: Path, phase: str = "", offset: int = 0, total: int = 0) -> str:
    h, done = hashlib.sha256(), 0
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
            done += len(chunk)
            if phase:
                _tick(phase, offset + done, total)
    return h.hexdigest()


# ------------------------------------------------------------------ export

def export(out_dir: str | Path, files: bool = True, since: str | None = None, part_size: int = PART_SIZE,
           name: str = "") -> dict:
    """Write a dataset into out_dir; returns its manifest."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    me = installation()
    created = _now()
    base = out / ("rozvedka-dataset-" + created[:19].replace("-", "").replace(":", "").replace("T", "-")
                  + (f"-{''.join(c for c in name if c.isalnum() or c in '-_')[:30]}" if name else ""))
    with tempfile.TemporaryDirectory(dir=out, prefix=".rozvedka-export-") as tmp:
        snap = Path(tmp) / "rozvedka.db"
        src = db.connect()
        log.info("export to %s (files: %s, since: %s, parts of %s bytes)", out, files, since, part_size)
        try:
            dst = __import__("sqlite3").connect(snap)
            ps = src.execute("PRAGMA page_size").fetchone()[0]
            src.backup(dst, pages=4096,           # a consistent copy while the portal may be running
                       progress=lambda status, remaining, total: _tick("Copying the database", (total - remaining) * ps, total * ps))
            dst.close()
            fresh = freshness(src)
            docs = [dict(r) for r in src.execute(
                """SELECT d.id, d.local_path, d.sha256, d.size, d.discovered_at, d.downloaded_at FROM documents d
                   WHERE d.local_path IS NOT NULL AND d.status='downloaded'""")]
            logo_rows = [dict(r) for r in src.execute("SELECT key, logo_path FROM sources WHERE logo_path IS NOT NULL")]
        finally:
            src.close()
        gz = Path(tmp) / "rozvedka.db.gz"
        size, done = snap.stat().st_size, 0
        with open(snap, "rb") as f, gzip.open(gz, "wb", compresslevel=6) as g:
            while chunk := f.read(CHUNK):
                g.write(chunk)
                done += len(chunk)
                _tick("Compressing the database", done, size)
        log.info("database copied and compressed: %d → %d bytes", size, gz.stat().st_size)
        db_sha = _sha256(snap)
        chosen = [d for d in docs if files and (not since or max(d["discovered_at"] or "", d["downloaded_at"] or "") >= since)]
        chosen = [d for d in chosen if (config.FILES / d["local_path"]).exists()]
        need = sum(d["size"] or 0 for d in chosen) + gz.stat().st_size + (30 << 20)
        free = shutil.disk_usage(out).free
        if need > free:
            raise OSError(f"not enough space in {out}: the dataset needs about {need / 1e9:.1f} GB, {free / 1e9:.1f} GB free")
        manifest = {
            "format": FORMAT, "format_version": FORMAT_VERSION, "dataset_id": uuid.uuid4().hex[:12], "created": created,
            "name": name, "app_version": __version__, "installation": me,
            "scope": {"files": files, "since": since, "files_included": len(chosen),
                      "files_bytes": sum(d["size"] or 0 for d in chosen), "documents_with_file": len(docs)},
            "database": {"member": "db/rozvedka.db.gz", "sha256": db_sha, "size": snap.stat().st_size},
            "freshness": fresh,
            "lists": [n for n in PORTAL_LISTS if (_sources_dir() / n).exists()],
            "files": [d["local_path"] for d in chosen],
            "gazetteer": _gazetteer_meta(_gazetteer_dir()),
        }
        writer = _PartWriter(base, part_size, expected=need - (30 << 20))
        log.info("writing %d report files (%.2f GB) into parts of %.2f GB", len(chosen),
                 manifest["scope"]["files_bytes"] / 1e9, part_size / 1e9)
        try:
            _write_stream(writer, manifest, gz, logo_rows, chosen)
        except BaseException:
            writer.remove()                       # no half-written dataset is left behind
            raise
        writer.close()
        manifest["parts"] = writer.parts
        manifest["bytes"] = sum(p["size"] for p in writer.parts)
    mpath = base.with_name(base.name + ".manifest.json")
    mpath.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    log.info("dataset %s written: %d parts, %d bytes – %s", manifest["dataset_id"], len(writer.parts), manifest["bytes"], mpath)
    _record_run("export", {"dataset_id": manifest["dataset_id"], "manifest": str(mpath), "parts": len(writer.parts),
                           "bytes": manifest["bytes"], "files": len(chosen), "since": since, "with_files": files})
    return {**manifest, "manifest_path": str(mpath)}


def _write_stream(writer, manifest: dict, gz: Path, logo_rows: list, chosen: list) -> None:
    """The tar stream: manifest, database, lists, gazetteer, logos, then the report files."""
    with tarfile.open(fileobj=writer, mode="w|", format=tarfile.PAX_FORMAT) as tar:
        _add_bytes(tar, "manifest.json", json.dumps({**manifest, "parts": "see the manifest file"}, indent=1).encode())
        tar.add(gz, arcname="db/rozvedka.db.gz")
        for n in sorted(p.name for p in _sources_dir().glob("*.yaml")):
            tar.add(_sources_dir() / n, arcname=f"sources/{n}")
        for p in sorted(_gazetteer_dir().glob("*.json")) if _gazetteer_dir().exists() else []:
            tar.add(p, arcname=f"gazetteer/{p.name}")
        for r in logo_rows:
            p = _logos_dir() / r["logo_path"]
            if p.exists():
                tar.add(p, arcname=f"logos/{r['key'].replace('/', '__')}{p.suffix}")
        for d in chosen:
            tar.add(config.FILES / d["local_path"], arcname=f"files/{d['local_path']}")


def _gazetteer_meta(folder: Path) -> dict | None:
    p = folder / "actors.json"
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            head = json.load(f)
        return {"retrieved": head.get("retrieved"), "config_hash": head.get("config_hash")}
    except Exception:  # noqa: BLE001
        return None


def _record_run(kind: str, summary: dict) -> None:
    with db.session() as con:
        con.execute("INSERT INTO runs(kind, started_at, finished_at, summary) VALUES(?,?,?,?)",
                    (kind, _now(), _now(), json.dumps(summary, ensure_ascii=False)))


# ------------------------------------------------------------------ import: find, verify, open

def find_manifest(path: str | Path) -> Path:
    p = Path(path)
    if p.is_dir():
        found = sorted(p.glob("*.manifest.json"))
        if len(found) != 1:
            raise FileNotFoundError(f"{p}: expected one *.manifest.json, found {len(found)}")
        return found[0]
    if p.name.endswith(".manifest.json"):
        return p
    if ".tar." in p.name:                                  # a part: <base>.tar.001
        return p.with_name(p.name.split(".tar.")[0] + ".manifest.json")
    raise FileNotFoundError(f"{p}: not a dataset manifest, part or folder")


def verify(manifest_path: Path) -> dict:
    """Check that every part is there, with its size and SHA-256."""
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    if m.get("format") != FORMAT:
        raise ValueError(f"{manifest_path.name} is not a Rozvedka dataset")
    if m.get("format_version", 0) > FORMAT_VERSION:
        raise ValueError(f"dataset format {m['format_version']} is newer than this app understands ({FORMAT_VERSION}) – update the app")
    problems, total, done = [], sum(p["size"] for p in m["parts"]), 0
    log.info("verifying %d parts (%d bytes) of dataset %s", len(m["parts"]), total, m.get("dataset_id"))
    for part in m["parts"]:
        p = manifest_path.with_name(part["name"])
        if not p.exists():
            problems.append(f"missing: {part['name']}")
        elif p.stat().st_size != part["size"]:
            problems.append(f"incomplete: {part['name']} ({p.stat().st_size} of {part['size']} bytes)")
        elif _sha256(p, "Checking the parts", done, total) != part["sha256"]:
            problems.append(f"damaged: {part['name']} (checksum differs)")
        done += part["size"]
        _tick("Checking the parts", done, total)
    for pr in problems:
        log.warning("part problem: %s", pr)
    return {"manifest": m, "problems": problems}


def _open_db(manifest_path: Path, m: dict, work: Path) -> tuple[Path, "tarfile.TarFile", "_PartReader"]:
    """Read the stream up to the database; return the database and the open stream (for the files after it)."""
    reader = _PartReader([manifest_path.with_name(p["name"]) for p in m["parts"]], "Reading the dataset's database",
                         m["parts"][0]["size"])
    tar = tarfile.open(fileobj=reader, mode="r|")
    dbfile = None
    for member in tar:
        if member.name == m["database"]["member"]:
            dbfile = work / "dataset.db"
            with tar.extractfile(member) as src, gzip.open(src) as g, open(dbfile, "wb") as out:
                shutil.copyfileobj(g, out, CHUNK)
            break
    if dbfile is None or _sha256(dbfile) != m["database"]["sha256"]:
        raise ValueError("the dataset's database is missing or damaged")
    return dbfile, tar, reader


def _version(v: str) -> tuple:
    return tuple(int(x) for x in v.split("+")[0].split(".")[:3] if x.isdigit())


# ------------------------------------------------------------------ comparison

def compare(con, m: dict) -> dict:
    """This library against the dataset (attached as `ds`): freshness and what an import would add or change."""
    here = freshness(con)
    there = m["freshness"]
    newer = lambda a, b: (a or "") > (b or "")   # noqa: E731
    per = {"dataset newer": [], "library newer": [], "same": [], "only in dataset": [], "only here": []}
    for key, d in there["sources"].items():
        h = here["sources"].get(key)
        if h is None:
            per["only in dataset"].append(key)
        elif newer(d["last_crawl"], h["last_crawl"]):
            per["dataset newer"].append(key)
        elif newer(h["last_crawl"], d["last_crawl"]):
            per["library newer"].append(key)
        else:
            per["same"].append(key)
    per["only here"] = [k for k in here["sources"] if k not in there["sources"]]
    from . import registry
    try:
        known = {registry.source_key(s) for s in registry.load()}       # this app's registry, not only the database
    except Exception:  # noqa: BLE001
        known = set(here["sources"])
    unknown = sorted(k for k in there["sources"] if k not in known and k not in here["sources"])
    local = {r["url"]: dict(r) for r in con.execute("SELECT d.*, s.key skey FROM documents d JOIN sources s ON s.id=d.source_id")}
    ds_docs = [dict(r) for r in con.execute("SELECT d.*, s.key skey FROM ds.documents d JOIN ds.sources s ON s.id=d.source_id")]
    included = set(m.get("files") or [])
    with_file = lambda d: d["status"] == "downloaded" and d["local_path"] in included   # noqa: E731
    stats = {"only_in_dataset": 0, "only_here": 0, "in_both": 0, "files_to_add": 0, "years_to_fill": 0,
             "conflicts": 0, "text_to_add": 0}
    ds_urls = set()
    has_text = {r[0] for r in con.execute("SELECT doc_id FROM doc_index WHERE chars > 0")}
    ds_text = {r[0] for r in con.execute("SELECT doc_id FROM ds.doc_index WHERE chars > 0")}
    for d in ds_docs:
        ds_urls.add(d["url"])
        h = local.get(d["url"])
        if h is None:
            stats["only_in_dataset"] += 1
            continue
        stats["in_both"] += 1
        if with_file(d) and not (with_file(h) and (config.FILES / h["local_path"]).exists()):
            stats["files_to_add"] += 1
        if h["year"] is None and d["year"] is not None:
            stats["years_to_fill"] += 1
        if d["id"] in ds_text and h["id"] not in has_text:
            stats["text_to_add"] += 1
        stats["conflicts"] += len(_conflicts(h, d))
    stats["only_here"] = sum(1 for u in local if u not in ds_urls)
    adds = stats["only_in_dataset"] or stats["files_to_add"] or stats["years_to_fill"] or stats["text_to_add"]
    if per["dataset newer"] and per["library newer"]:
        verdict = "mixed"                  # each side crawled some sources more recently
    elif per["dataset newer"] or per["only in dataset"] or newer(there["last_discovered"], here["last_discovered"]):
        verdict = "newer"
    elif per["library newer"] and not adds:
        verdict = "older"
    elif adds:
        verdict = "complements"            # the same crawl state, but the dataset holds what this library lacks
    else:
        verdict = "same"
    return {"verdict": verdict, "here": {k: v for k, v in here.items() if k != "sources"},
            "dataset": {k: v for k, v in there.items() if k != "sources"},
            "sources": {k: len(v) for k, v in per.items()}, "sources_only_in_dataset": unknown,
            "documents": stats, "empty_here": here["documents"] == 0}


def _conflicts(h: dict, d: dict) -> list[str]:
    """Hand edits that disagree: both years set by hand, hidden/visible, title or language changed."""
    out = []
    if h["year"] is not None and d["year"] is not None and h["year"] != d["year"]:
        if (h["year_source"] == "set by hand") or (d["year_source"] == "set by hand"):
            out.append("year")
    if h["hidden"] != d["hidden"]:
        out.append("hidden")
    if (h["title"] or "") != (d["title"] or ""):
        out.append("title")
    if (h["lang"] or "") != (d["lang"] or ""):
        out.append("lang")
    return out


# ------------------------------------------------------------------ import

def import_dataset(path: str | Path, check: bool = False, prefer: str = "local", index: bool = True) -> dict:
    mpath = find_manifest(path)
    v = verify(mpath)
    m = v["manifest"]
    if v["problems"]:
        return {"error": "the dataset is incomplete or damaged", "problems": v["problems"], "dataset": _about(m)}
    db.init()
    from . import collect
    collect.init()
    work_root = config.DATA / "imports"
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work_root, prefix=f"{m['dataset_id']}-") as tmp:
        dbfile, tar, reader = _open_db(mpath, m, Path(tmp))
        try:
            con = db.connect()
            con.execute("ATTACH DATABASE ? AS ds", (str(dbfile),))
            _tick("Comparing with this library")
            report = {"dataset": _about(m), "app_version": __version__, "compare": compare(con, m), "check": check}
            log.info("comparison: %s", {k: v for k, v in report["compare"].items() if k in ("verdict", "documents", "sources")})
            if _version(m["app_version"])[:2] > _version(__version__)[:2]:
                report["warning"] = (f"made with Rozvedka {m['app_version']}, this is {__version__}: update the app "
                                     f"to import everything the dataset holds")
            if check:
                con.close()
                return report
            _tick("Saving a safety copy of the database", 0, 0, final=True)     # from here on the library changes
            backup = _safety_copy(con)
            log.info("safety copy: %s", backup)
            report["safety_copy"] = str(backup)
            if report["compare"]["empty_here"]:
                con.execute("DETACH DATABASE ds")
                plan = _restore(con, dbfile, m)
                report["mode"] = "restore"
            else:
                plan = _merge(con, m, prefer)
                report["mode"] = "merge"
                con.commit()
                con.execute("DETACH DATABASE ds")
            con.commit()
            con.close()
            reader.phase, reader.total = "Writing report files", m.get("bytes") or sum(p["size"] for p in m["parts"])
            log.info("%s: %s", report["mode"], {k: v for k, v in plan["applied"].items() if k != "conflicts"})
            report["files"] = _extract(tar, plan, m)
            log.info("files: %s", {k: v for k, v in report["files"].items() if k != "missing"})
        finally:
            tar.close()
            reader.close()
    report["lists"] = _merge_lists(mpath, m)
    report["applied"] = plan["applied"]
    _after_import(m, report, plan)
    if index:
        report["index"] = _reindex()
    _record_run("import", {"dataset_id": m["dataset_id"], "mode": report["mode"], "from": m["installation"],
                           "created": m["created"], "verdict": report["compare"]["verdict"], **plan["applied"],
                           "files": report["files"]})
    out = work_root / f"{m['dataset_id']}-{_now()[:19].replace(':', '')}.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    report["report_path"] = str(out)
    return report


def _about(m: dict) -> dict:
    return {"id": m["dataset_id"], "created": m["created"], "name": m.get("name"), "app_version": m["app_version"],
            "installation": m["installation"], "scope": m["scope"], "bytes": m.get("bytes")}


def _safety_copy(con) -> Path:
    folder = config.DATA / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"pre-import-{_now()[:19].replace(':', '')}.db"
    dst = __import__("sqlite3").connect(path)
    con.backup(dst)
    dst.close()
    for old in sorted(folder.glob("pre-import-*.db"))[:-3]:      # keep the last three
        old.unlink()
    return path


def _restore(con, dbfile: Path, m: dict) -> dict:
    """Empty library: the dataset's database becomes this library's."""
    src = __import__("sqlite3").connect(dbfile)
    src.backup(con)
    src.close()
    db.init()
    con.execute("UPDATE documents SET dataset=? WHERE dataset IS NULL", (m["dataset_id"],))
    wanted = {}
    for r in con.execute("SELECT id, local_path, sha256 FROM documents WHERE status='downloaded' AND local_path IS NOT NULL"):
        wanted[r["local_path"]] = {"doc": r["id"], "sha256": r["sha256"], "target": r["local_path"]}
    logos = {r["key"]: r["id"] for r in con.execute("SELECT id, key FROM sources")}
    n = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    return {"wanted": wanted, "logos": logos, "applied": {"documents_added": n, "documents_updated": 0, "conflicts": []}}


def _merge(con, m: dict, prefer: str) -> dict:
    """Existing library: add what is missing, keep the more recent crawl state, list conflicting hand edits."""
    cols = lambda schema, t: [r[1] for r in con.execute(f"PRAGMA {schema}.table_info({t})")]   # noqa: E731
    doc_cols = [c for c in cols("ds", "documents") if c in set(cols("main", "documents")) and c != "id"]
    applied = {"documents_added": 0, "documents_updated": 0, "sources_added": [], "pages_added": 0, "files_wanted": 0,
               "to_download": 0, "duplicates": 0, "conflicts": [], "years_filled": 0, "text_added": 0}
    # sources by registry key
    src_map = {}
    for s in con.execute("SELECT * FROM ds.sources").fetchall():
        row = con.execute("SELECT id FROM sources WHERE key=?", (s["key"],)).fetchone()
        if row is None:
            keep = [c for c in cols("ds", "sources") if c in set(cols("main", "sources")) and c not in ("id", "logo_path")]
            cur = con.execute(f"INSERT INTO sources({','.join(keep)}) VALUES({','.join('?' * len(keep))})", [s[c] for c in keep])
            src_map[s["id"]] = cur.lastrowid
            applied["sources_added"].append(s["key"])
        else:
            src_map[s["id"]] = row["id"]
    # pages by (source, url): keep the most recent crawl
    page_map = {}
    for p in con.execute("SELECT * FROM ds.pages").fetchall():
        sid = src_map[p["source_id"]]
        row = con.execute("SELECT id, last_crawled FROM pages WHERE source_id=? AND url=?", (sid, p["url"])).fetchone()
        if row is None:
            cur = con.execute("""INSERT INTO pages(source_id,url,lang,kind,note,verified,last_crawled,last_status,active)
                                 VALUES(?,?,?,?,?,?,?,?,?)""", (sid, p["url"], p["lang"], p["kind"], p["note"], p["verified"],
                                                              p["last_crawled"], p["last_status"], p["active"]))
            page_map[p["id"]] = cur.lastrowid
            applied["pages_added"] += 1
        else:
            page_map[p["id"]] = row["id"]
            if (p["last_crawled"] or "") > (row["last_crawled"] or ""):
                con.execute("UPDATE pages SET last_crawled=?, last_status=? WHERE id=?", (p["last_crawled"], p["last_status"], row["id"]))
    local_sha = {r["sha256"]: r["id"] for r in con.execute(
        "SELECT id, sha256 FROM documents WHERE sha256 IS NOT NULL AND status='downloaded' AND local_path IS NOT NULL")}
    used_paths = {r[0] for r in con.execute("SELECT local_path FROM documents WHERE local_path IS NOT NULL")}
    has_text = {r[0] for r in con.execute("SELECT doc_id FROM doc_index WHERE chars > 0")}
    wanted = {}
    included = set(m.get("files") or [])
    ds_docs = [dict(r) for r in con.execute("SELECT * FROM ds.documents ORDER BY id")]
    for n, d in enumerate(ds_docs, 1):
        if n % 50 == 0 or n == len(ds_docs):
            _tick("Merging reports", n, len(ds_docs))
        h = con.execute("SELECT * FROM documents WHERE url=?", (d["url"],)).fetchone()
        file_ok = d["status"] == "downloaded" and d["local_path"] in included
        if h is None:
            vals = {c: d[c] for c in doc_cols}
            vals["source_id"], vals["page_id"] = src_map[d["source_id"]], page_map.get(d["page_id"])
            vals["dataset"] = m["dataset_id"]
            if file_ok and d["sha256"] in local_sha:          # the same file is here under another address
                vals.update(status="duplicate", local_path=None, error=f"same file as document #{local_sha[d['sha256']]} (imported)")
                applied["duplicates"] += 1
                file_ok = False
            elif file_ok:
                target = _free_path(d["local_path"], used_paths)
                vals["local_path"] = target
                used_paths.add(target)
            elif d["status"] == "downloaded":                  # downloaded there, file not in this dataset
                vals.update(status="new", local_path=None, error=f"file not in dataset {m['dataset_id']} – download again")
                applied["to_download"] += 1
            cur = con.execute(f"INSERT INTO documents({','.join(vals)}) VALUES({','.join('?' * len(vals))})", list(vals.values()))
            new_id = cur.lastrowid
            _copy_text(con, d["id"], new_id)
            up = con.execute("SELECT * FROM ds.uploads WHERE doc_id=?", (d["id"],)).fetchone()
            if up:
                con.execute("INSERT OR IGNORE INTO uploads(doc_id,added_at,via,original_name,official) VALUES(?,?,?,?,?)",
                            (new_id, up["added_at"], up["via"], up["original_name"], up["official"]))
            if file_ok:
                wanted[d["local_path"]] = {"doc": new_id, "sha256": d["sha256"], "target": vals["local_path"]}
            applied["documents_added"] += 1
            continue
        h = dict(h)
        changes = {}
        here_file = h["status"] == "downloaded" and h["local_path"] and (config.FILES / h["local_path"]).exists()
        if file_ok and not here_file:
            target = h["local_path"] if h["local_path"] and h["local_path"] == d["local_path"] else _free_path(d["local_path"], used_paths)
            used_paths.add(target)
            changes.update(status="downloaded", local_path=target, sha256=d["sha256"], size=d["size"],
                           pages_count=d["pages_count"], mime=d["mime"], downloaded_at=d["downloaded_at"], error=None)
            wanted[d["local_path"]] = {"doc": h["id"], "sha256": d["sha256"], "target": target}
        if h["year"] is None and d["year"] is not None:
            changes.update(year=d["year"], year_source=d["year_source"])
            applied["years_filled"] += 1
        elif d["year_source"] == "set by hand" and h["year_source"] != "set by hand" and d["year"] != h["year"]:
            changes.update(year=d["year"], year_source="set by hand")      # a hand correction beats a rule
        if (d["discovered_at"] or "9") < (h["discovered_at"] or "9"):
            changes["discovered_at"] = d["discovered_at"]                  # known since the earlier date
        for c in [c for c in _conflicts(h, d) if not (c == "year" and "year" in changes)]:
            applied["conflicts"].append({"url": d["url"], "field": c, "here": h[c], "dataset": d[c],
                                         "kept": "dataset" if prefer == "dataset" else "here"})
            if prefer == "dataset":
                changes[c] = d[c]
                if c == "year":
                    changes["year_source"] = d["year_source"]
        if h["id"] not in has_text and con.execute("SELECT 1 FROM ds.doc_index WHERE doc_id=? AND chars > 0", (d["id"],)).fetchone():
            _copy_text(con, d["id"], h["id"])
            applied["text_added"] += 1
        if changes:
            con.execute(f"UPDATE documents SET {', '.join(f'{k}=?' for k in changes)} WHERE id=?", (*changes.values(), h["id"]))
            applied["documents_updated"] += 1
    # "checked, nothing new" dates: the later one
    for c in con.execute("SELECT s.key, c.checked_at, c.note FROM ds.collect_checks c JOIN ds.sources s ON s.id=c.source_id").fetchall():
        sid = con.execute("SELECT id FROM sources WHERE key=?", (c["key"],)).fetchone()
        if sid:
            con.execute("""INSERT INTO collect_checks(source_id,checked_at,note) VALUES(?,?,?)
                           ON CONFLICT(source_id) DO UPDATE SET checked_at=excluded.checked_at, note=excluded.note
                           WHERE excluded.checked_at > collect_checks.checked_at""", (sid["id"], c["checked_at"], c["note"]))
    applied["files_wanted"] = len(wanted)
    logos = {s["key"]: src_map[s["id"]] for s in con.execute("SELECT id, key FROM ds.sources")
             if not con.execute("SELECT logo_path FROM sources WHERE id=?", (src_map[s["id"]],)).fetchone()["logo_path"]}
    return {"wanted": wanted, "logos": logos, "applied": applied}


def _free_path(rel: str, used: set) -> str:
    """The dataset's file path, or a variant of it when another report here already has that path."""
    if rel not in used and not (config.FILES / rel).exists():
        return rel
    stem, dot, ext = rel.rpartition(".")
    for i in range(2, 1000):
        cand = f"{stem}_{i}.{ext}" if dot else f"{rel}_{i}"
        if cand not in used and not (config.FILES / cand).exists():
            return cand
    raise RuntimeError(f"no free file name for {rel}")


def _copy_text(con, ds_id: int, here_id: int) -> None:
    """The report's text and its index row (OCR included) – topics and actors are matched again here."""
    row = con.execute("SELECT * FROM ds.doc_index WHERE doc_id=?", (ds_id,)).fetchone()
    if row is None:
        return
    con.execute("DELETE FROM doc_text WHERE rowid=?", (here_id,))
    con.execute("INSERT INTO doc_text(rowid,title,body) SELECT ?, title, body FROM ds.doc_text WHERE rowid=?", (here_id, ds_id))
    keep = [c for c in row.keys() if c in {r[1] for r in con.execute("PRAGMA main.table_info(doc_index)")} and c != "doc_id"]
    vals = {c: row[c] for c in keep}
    vals.update(taxonomy_hash=None, classified_at=None)
    if "actors_hash" in vals:
        vals["actors_hash"] = None
    con.execute("DELETE FROM doc_index WHERE doc_id=?", (here_id,))
    con.execute("DELETE FROM doc_topics WHERE doc_id=?", (here_id,))
    con.execute(f"INSERT INTO doc_index(doc_id,{','.join(vals)}) VALUES(?{',?' * len(vals)})", (here_id, *vals.values()))


def _extract(tar, plan: dict, m: dict) -> dict:
    """Read the rest of the stream: report files that are wanted (checked against their SHA-256), logos, gazetteer."""
    stats = {"written": 0, "bytes": 0, "bad_checksum": 0, "logos": 0, "gazetteer": None}
    wanted, logos = plan["wanted"], plan["logos"]
    gaz_tmp = None
    seen = set()
    for member in tar:
        if not member.isfile():
            continue
        name = member.name
        if name.startswith("files/"):
            rel = name[len("files/"):]
            w = wanted.get(rel)
            if not w:
                continue
            seen.add(rel)
            target = config.FILES / w["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".part")
            h = hashlib.sha256()
            with tar.extractfile(member) as src, open(tmp, "wb") as out:
                while chunk := src.read(CHUNK):
                    out.write(chunk); h.update(chunk)
            if w["sha256"] and h.hexdigest() != w["sha256"]:
                tmp.unlink()
                stats["bad_checksum"] += 1
                continue
            tmp.replace(target)
            stats["written"] += 1
            stats["bytes"] += member.size
        elif name.startswith("logos/"):
            key = Path(name).stem.replace("__", "/")
            if key in logos:
                folder = _logos_dir()
                folder.mkdir(parents=True, exist_ok=True)
                fname = f"{logos[key]}{Path(name).suffix}"
                with tar.extractfile(member) as src, open(folder / fname, "wb") as out:
                    shutil.copyfileobj(src, out)
                with db.session() as con:
                    con.execute("UPDATE sources SET logo_path=? WHERE id=?", (fname, logos[key]))
                stats["logos"] += 1
        elif name.startswith("gazetteer/"):
            gaz_tmp = gaz_tmp or Path(tempfile.mkdtemp(dir=config.DATA / "imports"))
            with tar.extractfile(member) as src, open(gaz_tmp / Path(name).name, "wb") as out:
                shutil.copyfileobj(src, out)
        elif name.startswith("sources/") and Path(name).name in PORTAL_LISTS:
            folder = config.DATA / "imports" / f"{m['dataset_id']}-lists"
            folder.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, open(folder / Path(name).name, "wb") as out:
                shutil.copyfileobj(src, out)
    stats["missing"] = sorted(set(wanted) - seen)
    if gaz_tmp:
        stats["gazetteer"] = _take_gazetteer(gaz_tmp, m)
    return stats


def _take_gazetteer(folder: Path, m: dict) -> str:
    """Use the dataset's gazetteer when there is none here or it is newer (the actors are then matched again)."""
    here_dir = _gazetteer_dir()
    here, there = _gazetteer_meta(here_dir), (m.get("gazetteer") or {})
    try:
        if here and (here.get("retrieved") or "") >= (there.get("retrieved") or ""):
            return f"kept this library's ({here.get('retrieved')}; dataset {there.get('retrieved')})"
        here_dir.mkdir(parents=True, exist_ok=True)
        for p in folder.iterdir():
            shutil.copy2(p, here_dir / p.name)
        return f"taken from the dataset ({there.get('retrieved')}; here {here.get('retrieved') if here else 'none'})"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _merge_lists(mpath: Path, m: dict) -> dict:
    """Merge the portal-written lists: watchlist and reviews by key (a later review wins), series by source and name;
    imported year verdicts are applied by the dating step that follows an import."""
    folder = config.DATA / "imports" / f"{m['dataset_id']}-lists"
    out = {}
    if not folder.exists():
        return out
    try:
        for name in PORTAL_LISTS:
            theirs_p, ours_p = folder / name, _sources_dir() / name
            if not theirs_p.exists():
                continue
            theirs = yaml.safe_load(theirs_p.read_text(encoding="utf-8"))
            if not ours_p.exists():
                shutil.copy2(theirs_p, ours_p)
                out[name] = "taken from the dataset"
                continue
            if name == "watchlist.yaml":
                from . import watch
                ours = watch.load(ours_p)
                have = {i["query"] for i in ours}
                add = [i for i in (theirs or []) if isinstance(i, dict) and i.get("query") not in have]
                if add:
                    watch.save(ours + add, ours_p)
                out[name] = f"{len(add)} searches added"
            elif name == "actor_reviews.yaml":
                from . import review
                ours = {(r["actor"], r["url"]): r for r in review.load(ours_p)}
                added = 0
                for r in theirs or []:
                    k = (r.get("actor"), r.get("url"))
                    if k not in ours or (r.get("checked") or "") > (ours[k].get("checked") or ""):
                        ours[k] = r
                        added += 1
                if added:
                    review.save(list(ours.values()), ours_p)
                out[name] = f"{added} verdicts added or updated"
            elif name == "year_reviews.yaml":
                from . import dating
                ours = {r["url"]: r for r in dating.load_reviews(ours_p)}
                added = 0
                for r in theirs or []:
                    if isinstance(r, dict) and r.get("url") and (
                            r["url"] not in ours or (r.get("checked") or "") > (ours[r["url"]].get("checked") or "")):
                        ours[r["url"]] = r
                        added += 1
                if added:
                    dating.save_reviews(list(ours.values()), ours_p)
                out[name] = f"{added} year verdicts added or updated"
            elif name == "series.yaml":
                from . import series
                ours = series.load(ours_p)
                have = {(s["source"], s["name"]) for s in ours.get("series", [])}
                add = [s for s in (theirs or {}).get("series", []) if (s["source"], s["name"]) not in have]
                rej = [r for r in (theirs or {}).get("rejected", []) if r not in ours.get("rejected", [])]
                if add or rej:
                    ours.setdefault("series", []).extend(add)
                    ours.setdefault("rejected", []).extend(rej)
                    series.save(ours, ours_p)
                out[name] = f"{len(add)} series and {len(rej)} rejections added"
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return out


def _after_import(m: dict, report: dict, plan: dict) -> None:
    """Reports that should have a file but have none here (file not in the dataset, or damaged): download again."""
    with db.session() as con:
        missing = [r["id"] for r in con.execute(
            "SELECT id, local_path FROM documents WHERE status='downloaded' AND local_path IS NOT NULL")
            if not (config.FILES / r["local_path"]).exists()]
        for i in missing:
            con.execute("""UPDATE documents SET status='new', local_path=NULL,
                           error=? WHERE id=?""", (f"file not in dataset {m['dataset_id']} – download again", i))
    report["to_download"] = len(missing)
    from . import registry
    try:
        report["registry"] = registry.sync()        # this app's registry: new sources and pages, inactive old ones
    except Exception as e:  # noqa: BLE001
        report["registry"] = f"not synced: {e}"


def _reindex() -> dict:
    """Topics, dates and actors for the reports that came in (only those whose index rows were reset)."""
    from . import actor_sources, actors, dating, topics
    _tick("Matching topics in the new reports")
    out = {"topics": topics.index()}
    _tick("Dating the new reports")
    out["dates"] = dating.date_documents()
    if actor_sources.GAZETTEER.exists():
        _tick("Matching actors in the new reports")
        out["actors"] = actors.index()
    log.info("indexed: %s", out)
    return out


def describe(r: dict, cli: bool = True) -> str:
    """The import report in plain words (what `python -m rozvedka import` prints)."""
    if "error" in r:
        return "\n".join([f"✗ {r['error']}:"] + [f"  - {p}" for p in r.get("problems", [])])
    d, c = r["dataset"], r["compare"]
    src = d["installation"]
    day = lambda s: ((s[:16].replace("T", " ") + (" UTC" if s.endswith("Z") else "")) if s else "never")   # noqa: E731
    lines = [f"Dataset {d['id']} from installation {src.get('id')}{' (' + d['name'] + ')' if d.get('name') else ''}, "
             f"made {day(d['created'])} with Rozvedka {d['app_version']}"
             f"{'' if d['scope']['files'] else ' – catalogue only, no report files'}"
             f"{' – report files since ' + d['scope']['since'] if d['scope'].get('since') else ''}."]
    if r.get("warning"):
        lines.append("! " + r["warning"])
    verdict = {"newer": "The dataset is NEWER than this library.", "older": "The dataset is OLDER than this library – it adds nothing new.",
               "same": "The dataset and this library are at the same state.",
               "mixed": "The dataset is newer for some sources and older for others.",
               "complements": "The dataset has the same crawl state, but holds what this library lacks."}[c["verdict"]]
    if c["empty_here"]:
        verdict = "This library is empty: the dataset will be its starting point."
    lines += [verdict,
              f"  last crawl      here {day(c['here']['last_crawl'])}   dataset {day(c['dataset']['last_crawl'])}",
              f"  last download   here {day(c['here']['last_download'])}   dataset {day(c['dataset']['last_download'])}",
              f"  reports         here {c['here']['documents']}   dataset {c['dataset']['documents']}",
              "  sources: " + ", ".join(f"{k} {v}" for k, v in c["sources"].items() if v)]
    s = c["documents"]
    lines.append(f"  reports only in the dataset {s['only_in_dataset']}, only here {s['only_here']}, in both {s['in_both']}; "
                 f"files to add {s['files_to_add']}, years to fill {s['years_to_fill']}, text to add {s['text_to_add']}, "
                 f"conflicting edits {s['conflicts']}")
    if c["sources_only_in_dataset"]:
        lines.append("  sources this app does not know (update the app to show them): " + ", ".join(c["sources_only_in_dataset"][:10]))
    if r.get("check"):
        lines.append("Check only – nothing changed. " + ("Run without --check to import." if cli else
                                                          "Choose below whose hand edits win, then import."))
        return "\n".join(lines)
    a = r["applied"]
    lines += [f"Imported ({r['mode']}): {a['documents_added']} reports added, {a['documents_updated']} updated"
              + (f", {a.get('years_filled', 0)} years filled, {a.get('text_added', 0)} texts added" if r["mode"] == "merge" else ""),
              f"  files written {r['files']['written']} ({r['files']['bytes'] / 1e9:.2f} GB), checksum errors {r['files']['bad_checksum']}, "
              f"logos {r['files']['logos']}; reports to download again {r.get('to_download', 0)}"]
    if r["files"].get("gazetteer"):
        lines.append(f"  actor gazetteer: {r['files']['gazetteer']}")
    for k, v in (r.get("lists") or {}).items():
        lines.append(f"  {k}: {v}")
    if a.get("conflicts"):
        lines.append(f"  {len(a['conflicts'])} conflicting edits – kept {'the dataset' if a['conflicts'][0]['kept'] == 'dataset' else 'this library'}'s; "
                     f"listed in the report")
    lines += [f"Safety copy of the database before the import: {r['safety_copy']}", f"Full report: {r.get('report_path')}"]
    return "\n".join(lines)
