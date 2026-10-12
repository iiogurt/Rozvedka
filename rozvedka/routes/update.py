"""Update page and the background job."""
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse
from .. import dataset, db, jobs as jobrunner, paging, updater
from ..web import COUNTRY_NAMES, tpl


router = APIRouter()


@router.get("/update")
def update_page(request: Request, country: str = "", state: str = "", q: str = "", page: str = "1", per_page: str = ""):
    """Check the agencies for new reports: what to do, which sources, progress, and every source's last check."""
    rows = updater.sources_status(country, state, q)
    allrows = updater.sources_status() if (country or state or q) else rows
    size = paging.per_page_of(per_page, 200)       # usually every source on one page, so all can be ticked
    pg = paging.paginate(len(rows), page, size, "/update", {"country": country, "state": state, "q": q,
                         "per_page": size if size != 200 else ""}, anchor="#sources", default=200)
    with db.session() as con:
        fresh = dataset.freshness(con)
        counts = dict(con.execute("""SELECT d.status, COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                     WHERE d.hidden=0 AND s.active=1 GROUP BY d.status""").fetchall())
    from collections import Counter
    logs = sorted(jobrunner.logs_dir().glob("update-*.log"), reverse=True)[:10] if jobrunner.logs_dir().exists() else []
    return tpl.TemplateResponse(request, "update.html", {
        "rows": rows[pg["offset"]:pg["offset"] + size], "pg": pg, "f": {"country": country, "state": state, "q": q},
        "states": Counter(r["state"] for r in allrows), "stale_n": sum(1 for r in allrows if r["stale"] and r["state"] != "manual"),
        "countries": sorted({r["country"] for r in allrows}, key=lambda k: COUNTRY_NAMES.get(k, k)),
        "fresh": fresh, "counts": counts, "history": updater.history(), "logs": [p.name for p in logs],
        "since": _since(),
        "actions": updater.ACTIONS, "plan": updater.plan()})


def _since() -> str | None:
    with db.session() as con:
        return updater.all_checked_since(con)


def _update_form(action: str, scope: str, country: str, sources: str, stale_days: str, retry_failed: str) -> dict:
    ids = [int(x) for x in sources.split(",") if x.strip().isdigit()]
    days = int(stale_days) if stale_days.strip().isdigit() else 7
    return {"action": action, "scope": scope, "country": country, "sources": ids, "stale_days": days,
            "retry_failed": retry_failed in ("1", "true", "on")}


@router.get("/api/update/plan")
def api_update_plan(action: str = "full", scope: str = "all", country: str = "", sources: str = "", stale_days: str = "7",
                    retry_failed: str = ""):
    return updater.plan(**_update_form(action, scope, country, sources, stale_days, retry_failed))


@router.post("/api/update")
def api_update(action: str = Form("full"), scope: str = Form("all"), country: str = Form(""), sources: str = Form(""),
               stale_days: str = Form("7"), retry_failed: str = Form("")):
    f = _update_form(action, scope, country, sources, stale_days, retry_failed)
    if scope == "sources" and not f["sources"]:
        return JSONResponse({"error": "tick the sources to check in the table"}, status_code=400)
    if scope == "country" and not country:
        return JSONResponse({"error": "choose a country"}, status_code=400)
    r = jobrunner.update(**f)
    return r if "error" not in r else JSONResponse(r, status_code=409)


@router.get("/api/job")
def api_job():
    return {"job": jobrunner.state()}


@router.post("/api/job/cancel")
def api_job_cancel():
    return {"cancelled": jobrunner.cancel()}
