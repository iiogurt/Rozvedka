"""Progress points for long jobs started from the portal (update, export, import).

Code that runs long calls `tick(phase, done, total)`; the job runner (rozvedka/jobs.py) installs a hook that records
the progress and raises `Cancelled` when the job was cancelled – only while `final` has not been passed, i.e. while
stopping leaves nothing half-done. Outside a job, tick() does nothing.
"""


class Cancelled(Exception):
    """Raised at a progress point when the running job was cancelled."""


hook = None          # set by the job runner: hook(phase, done, total, final, note)


def tick(phase: str, done: int = 0, total: int = 0, final: bool = False, note: str = "") -> None:
    if hook:
        hook(phase, done, total, final, note)
