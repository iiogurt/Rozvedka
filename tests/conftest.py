"""Shared test setup.

- Jobs never start real indexer processes in tests (`python -m rozvedka index-topics|ocr|…`): a process outlives the
  test's temporary library and could work on the real one.
- A job started in the background by one test (e.g. indexing after an upload) finishes before the next test starts.
"""
import os
import time

import pytest

os.environ.setdefault("ROZVEDKA_ALLOWED_HOSTS", "testserver")   # the host name FastAPI's TestClient uses

from rozvedka import jobs


@pytest.fixture(autouse=True)
def no_indexer_processes(monkeypatch):
    monkeypatch.setattr(jobs, "index_steps", lambda steps: {cmd: "skipped in tests" for _, cmd in steps})
    yield
    end = time.time() + 60
    while jobs.running() and time.time() < end:
        time.sleep(0.05)
