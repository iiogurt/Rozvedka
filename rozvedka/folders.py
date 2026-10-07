"""The folder picker of the Data exchange page: browse, create and check folders – only below a few roots.

The portal has no login, so it never lists the whole file system: only removable media (/media, /mnt, /run/media),
the home folder of the user running the portal, and the folders in ROZVEDKA_EXCHANGE_DIRS (separated by ":").
"""
import json
import os
import shutil
from pathlib import Path

MANIFEST = ".manifest.json"


def roots() -> list[Path]:
    extra = [Path(p) for p in os.environ.get("ROZVEDKA_EXCHANGE_DIRS", "").split(":") if p]
    cands = extra + [Path("/media"), Path("/mnt"), Path("/run/media"), Path.home()]
    out = []
    for c in cands:
        try:
            r = c.resolve()
        except OSError:
            continue
        if r.is_dir() and os.access(r, os.R_OK | os.X_OK) and r not in out:
            out.append(r)
    return out


def allowed(path: str | Path) -> Path | None:
    """The resolved path if it lies under one of the roots, else None (symlinks cannot lead out)."""
    try:
        p = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    return p if any(p == r or p.is_relative_to(r) for r in roots()) else None


def check(path: str, writable: bool = False, file: bool = False) -> Path:
    p = allowed(path)
    if p is None:
        raise PermissionError(f"{path}: outside the folders the portal may use ({', '.join(map(str, roots()))})")
    if file:
        if not p.is_file():
            raise FileNotFoundError(f"{p}: no such file")
    elif not p.is_dir():
        raise FileNotFoundError(f"{p}: no such folder")
    elif writable and not os.access(p, os.W_OK):
        raise PermissionError(f"{p}: the portal may not write here")
    return p


def _plain_name(name) -> bool:
    return isinstance(name, str) and bool(name) and Path(name).name == name and name not in (".", "..")


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _dataset_summary(manifest: Path) -> dict:
    try:
        m = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"manifest": str(manifest), "name": manifest.name, "error": "not readable"}
    # a manifest is someone else's file: part names must be plain file names beside it, numbers must be numbers
    parts = [p for p in (m.get("parts") or []) if isinstance(p, dict) and _plain_name(p.get("name"))]
    present = [p for p in parts if (manifest.parent / p["name"]).exists()]
    complete = len(present) == len(parts) and all((manifest.parent / p["name"]).stat().st_size == p["size"] for p in present)
    return {"manifest": str(manifest), "name": manifest.name, "id": m.get("dataset_id"), "created": m.get("created"),
            "label": m.get("name"), "app_version": m.get("app_version"), "installation": (m.get("installation") or {}).get("id"),
            "bytes": _int(m.get("bytes")), "parts": len(parts), "parts_present": len(present), "complete": complete,
            "files": _int((m.get("scope") or {}).get("files_included")), "with_files": (m.get("scope") or {}).get("files") is not False,
            "since": (m.get("scope") or {}).get("since"), "documents": _int((m.get("freshness") or {}).get("documents")),
            "last_crawl": (m.get("freshness") or {}).get("last_crawl")}


def listing(path: str = "") -> dict:
    """A folder's subfolders and datasets, its free space, and the way back up – or the list of roots."""
    rs = roots()
    if not path:
        return {"path": "", "roots": [_entry(r) for r in rs], "dirs": [], "datasets": [], "parents": []}
    p = allowed(path)
    if p is None or not p.is_dir():
        raise PermissionError(f"{path}: not a folder the portal may use")
    dirs, datasets = [], []
    try:
        for c in sorted(p.iterdir(), key=lambda c: c.name.lower()):
            if c.name.startswith("."):
                continue
            if c.is_dir() and os.access(c, os.R_OK | os.X_OK) and allowed(c):   # no symlinks out of the roots
                dirs.append({"name": c.name, "path": str(c)})
            elif c.name.endswith(MANIFEST):
                datasets.append(_dataset_summary(c))
    except PermissionError:
        pass
    root = next(r for r in rs if p == r or p.is_relative_to(r))
    parents, cur = [], p
    while True:
        parents.insert(0, {"name": cur.name or str(cur), "path": str(cur)})
        if cur == root:
            break
        cur = cur.parent
    usage = shutil.disk_usage(p)
    return {"path": str(p), "writable": os.access(p, os.W_OK), "free": usage.free, "total": usage.total,
            "dirs": dirs, "datasets": datasets, "parents": parents, "roots": [_entry(r) for r in rs]}


def _entry(r: Path) -> dict:
    try:
        u = shutil.disk_usage(r)
        return {"name": str(r), "path": str(r), "free": u.free, "total": u.total}
    except OSError:
        return {"name": str(r), "path": str(r)}


def make(parent: str, name: str) -> Path:
    """Create a subfolder (a plain name, no path separators)."""
    p = check(parent, writable=True)
    name = name.strip()
    if not name or name in (".", "..") or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("a folder name without slashes, not starting with a dot")
    new = p / name
    new.mkdir(exist_ok=True)
    return new
