"""Export and import jobs started from the portal (Sources → Data exchange): one at a time, in a background thread,
with progress by phase, a log file (data/logs/) and cancelling while the library is still unchanged.

The page polls `state()`; the job's log is kept in memory (last lines) and in the file, which also captures what the
indexers log during an import.
"""
import datetime as dt
import logging
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from . import config, dataset, folders

_lock = threading.Lock()
_job: dict | None = None
LOG_LINES = 400


class _Lines(logging.Handler):
    def __init__(self, keep: deque):
        super().__init__(logging.INFO)
        self.keep = keep
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))

    def emit(self, record):
        self.keep.append(self.format(record))


def logs_dir() -> Path:
    return config.DATA / "logs"


def state() -> dict | None:
    """The current (or last) job, without internals – for the page."""
    with _lock:
        if _job is None:
            return None
        j = {k: v for k, v in _job.items() if not k.startswith("_")}
        j["log"] = list(_job["_lines"])[-80:]
        now = time.time()
        j["elapsed"] = round((j.get("finished") or now) - j["started"])
        p = j["progress"]
        if p["total"] and p["done"] and p.get("since") and not j.get("finished"):
            rate = (p["done"] - p.get("done0", 0)) / max(now - p["since"], 0.001)
            j["eta"] = round((p["total"] - p["done"]) / rate) if rate > 0 else None
            j["rate"] = rate
        return j


def running() -> bool:
    with _lock:
        return bool(_job and _job["status"] == "running")


def cancel() -> bool:
    with _lock:
        if _job and _job["status"] == "running" and _job["cancellable"]:
            _job["cancel"] = True
            _job["_lines"].append(f"{dt.datetime.now():%H:%M:%S} cancel requested – stopping at the next step")
            return True
    return False


def _hook(phase: str, done: int, total: int, final: bool) -> None:
    with _lock:
        j = _job
        if j is None:
            return
        if final:
            j["cancellable"] = False
        if j.get("cancel") and j["cancellable"]:
            raise dataset.Cancelled()
        p = j["progress"]
        if p["phase"] != phase:
            j["phases"].append(phase)
            j["progress"] = {"phase": phase, "done": done, "total": total, "since": time.time(), "done0": done}
        else:
            p.update(done=done, total=total)


def start(kind: str, run, **params) -> dict:
    """Start a job (kind 'export', 'check' or 'import'); `run` is called with **params in a thread."""
    global _job
    with _lock:
        if _job and _job["status"] == "running":
            return {"error": "another export or import is running – wait for it or cancel it"}
        logs_dir().mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        logfile = logs_dir() / f"{kind}-{stamp}.log"
        _job = {"id": stamp, "kind": kind, "params": {k: str(v) for k, v in params.items()}, "status": "running",
                "started": time.time(), "finished": None, "cancellable": True, "cancel": False, "phases": [],
                "progress": {"phase": "Starting", "done": 0, "total": 0}, "result": None, "error": None,
                "log_file": logfile.name, "_lines": deque(maxlen=LOG_LINES)}
        job = _job

    def target():
        root = logging.getLogger("rozvedka")
        fh = logging.FileHandler(logfile, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        lines = _Lines(job["_lines"])
        level = root.level
        root.setLevel(logging.INFO)
        root.addHandler(fh); root.addHandler(lines)
        dataset._hook = _hook
        log = logging.getLogger("rozvedka.datajobs")
        log.info("%s started: %s", kind, job["params"])
        try:
            result = run(**params)
            status, error = ("failed", result["error"]) if isinstance(result, dict) and result.get("error") else ("done", None)
            if isinstance(result, dict) and kind != "export" and "dataset" in result:
                result = {**result, "text": dataset.describe(result, cli=False)}
            with _lock:
                job.update(status=status, result=result, error=error)
            log.info("%s %s%s", kind, status, f": {error}" if error else "")
            if isinstance(result, dict) and result.get("text"):
                for line in result["text"].splitlines():
                    log.info("  %s", line)
        except dataset.Cancelled:
            msg = "cancelled – the partial dataset was removed" if kind == "export" else "cancelled – nothing was changed"
            with _lock:
                job.update(status="cancelled", error=msg)
            log.warning("%s %s", kind, msg)
        except Exception as e:  # noqa: BLE001 - shown on the page and in the log
            with _lock:
                job.update(status="failed", error=f"{type(e).__name__}: {e}")
            log.exception("%s failed", kind)
        finally:
            with _lock:
                job["finished"] = time.time()
            dataset._hook = None
            root.removeHandler(fh); root.removeHandler(lines)
            root.setLevel(level)
            fh.close()

    threading.Thread(target=target, name=f"rozvedka-{kind}", daemon=True).start()
    return {"started": job["id"]}


def export(dest: str, files: bool, since: str | None, part_size: int, name: str) -> dict:
    folder = folders.check(dest, writable=True)
    return start("export", dataset.export, out_dir=folder, files=files, since=since or None, part_size=part_size, name=name)


def check(manifest: str) -> dict:
    path = folders.check(manifest, file=True)
    return start("check", dataset.import_dataset, path=path, check=True)


def import_(manifest: str, prefer: str) -> dict:
    path = folders.check(manifest, file=True)
    return start("import", _import_and_index, path=path, prefer=prefer if prefer in ("local", "dataset") else "local")


INDEXERS = (("Matching topics in the new reports", "index-topics"), ("Dating the new reports", "date-documents"),
            ("Matching actors in the new reports", "index-actors"))


def _import_and_index(path, prefer: str) -> dict:
    """Import, then index in separate processes: the indexers start worker processes, which must not be forked
    from the portal's threads."""
    result = dataset.import_dataset(path, prefer=prefer, index=False)
    if result.get("error"):
        return result
    from . import actor_sources
    log = logging.getLogger("rozvedka.datajobs")
    result["index"] = {}
    env = {**os.environ, "ROZVEDKA_DATA": str(config.DATA)}
    for phase, cmd in INDEXERS:
        if cmd == "index-actors" and not actor_sources.GAZETTEER.exists():
            continue
        dataset._tick(phase)
        proc = subprocess.Popen([sys.executable, "-m", "rozvedka", cmd], cwd=config.ROOT, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in proc.stdout:
            if line.strip():
                log.info("%s: %s", cmd, line.rstrip())
        result["index"][cmd] = "ok" if proc.wait() == 0 else f"failed (exit {proc.returncode}) – run python -m rozvedka {cmd}"
    return result


def log_path(name: str) -> Path | None:
    p = (logs_dir() / name).resolve()
    return p if p.parent == logs_dir().resolve() and p.suffix == ".log" and p.exists() else None
