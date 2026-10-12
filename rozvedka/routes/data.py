"""Data exchange: export, check and import of the library."""
import json
import re
from pathlib import Path
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from .. import dataset, db, folders, jobs as jobrunner
from ..config import FILES
from ..web import tpl

router = APIRouter()


@router.get("/data")
def data_page(request: Request):
    """Data exchange: this installation, how fresh its data is, and the datasets exported or imported."""
    with db.session() as con:
        fresh = dataset.freshness(con)
        runs = [dict(r) for r in con.execute(
            "SELECT kind, started_at, summary FROM runs WHERE kind IN ('export','import') ORDER BY id DESC LIMIT 50")]
    for r in runs:
        try:
            r["summary"] = json.loads(r["summary"])
        except (TypeError, ValueError):
            r["summary"] = {}
    size = sum(f.stat().st_size for f in FILES.rglob("*") if f.is_file()) if FILES.exists() else 0
    logs = sorted(jobrunner.logs_dir().glob("*.log"), reverse=True)[:15] if jobrunner.logs_dir().exists() else []
    last_dir = next((str(Path(r["summary"]["manifest"]).parent) for r in runs
                     if r["kind"] == "export" and r["summary"].get("manifest")
                     and folders.allowed(Path(r["summary"]["manifest"]).parent)
                     and Path(r["summary"]["manifest"]).parent.is_dir()), "")
    return tpl.TemplateResponse(request, "data.html", {"me": dataset.installation(), "fresh": fresh, "runs": runs,
                                                      "files_bytes": size, "logs": [p.name for p in logs], "last_dir": last_dir,
                                                      "roots": [str(r) for r in folders.roots()]})


def _api_error(e: Exception, status: int = 400):
    return JSONResponse({"error": str(e)}, status_code=status)


@router.get("/api/data/folders")
def api_data_folders(path: str = ""):
    try:
        return folders.listing(path)
    except (PermissionError, FileNotFoundError, OSError) as e:
        return _api_error(e)


@router.post("/api/data/folders")
def api_data_mkdir(parent: str = Form(...), name: str = Form(...)):
    try:
        return {"path": str(folders.make(parent, name))}
    except (PermissionError, FileNotFoundError, ValueError, OSError) as e:
        return _api_error(e)


@router.get("/api/data/estimate")
def api_data_estimate(what: str = "all", since: str = ""):
    """About how many bytes an export will need (report files + compressed database)."""
    with db.session() as con:
        if what == "catalogue":
            files_bytes, n = 0, 0
        else:
            row = con.execute("""SELECT COALESCE(SUM(size),0), COUNT(*) FROM documents WHERE status='downloaded'
                                 AND local_path IS NOT NULL AND (? = '' OR MAX(COALESCE(discovered_at,''), COALESCE(downloaded_at,'')) >= ?)""",
                              (since if what == "since" else "", since if what == "since" else "")).fetchone()
            files_bytes, n = row[0], row[1]
    db_bytes = int(db.DB_PATH.stat().st_size * 0.35) if db.DB_PATH.exists() else 0
    return {"files": n, "files_bytes": files_bytes, "database_bytes": db_bytes, "total": files_bytes + db_bytes + (30 << 20)}


@router.post("/api/data/export")
def api_data_export(dest: str = Form(...), what: str = Form("all"), since: str = Form(""), part_size: str = Form("2000"),
                    name: str = Form("")):
    try:
        size_mb = int(part_size)
        if not 50 <= size_mb <= 100_000:
            raise ValueError("part size must be between 50 MB and 100 GB")
        if what == "since" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
            raise ValueError("choose the day from which report files are included")
        r = jobrunner.export(dest, files=what != "catalogue", since=since if what == "since" else None,
                            part_size=size_mb * 1_000_000, name=name.strip())
    except (PermissionError, FileNotFoundError, ValueError) as e:
        return _api_error(e)
    return r if "error" not in r else JSONResponse(r, status_code=409)


@router.post("/api/data/check")
def api_data_check(manifest: str = Form(...)):
    try:
        r = jobrunner.check(manifest)
    except (PermissionError, FileNotFoundError) as e:
        return _api_error(e)
    return r if "error" not in r else JSONResponse(r, status_code=409)


@router.post("/api/data/import")
def api_data_import(manifest: str = Form(...), prefer: str = Form("local")):
    try:
        r = jobrunner.import_(manifest, prefer)
    except (PermissionError, FileNotFoundError) as e:
        return _api_error(e)
    return r if "error" not in r else JSONResponse(r, status_code=409)


@router.post("/api/data/cancel")
def api_data_cancel():
    return {"cancelled": jobrunner.cancel()}


@router.get("/api/data/job")
def api_data_job():
    return {"job": jobrunner.state()}


@router.get("/data/logs/{name}")
def data_log(name: str):
    p = jobrunner.log_path(name)
    if p is None:
        raise HTTPException(404, "no such log")
    return PlainTextResponse(p.read_text(encoding="utf-8", errors="replace"))
