"""Data exchange page: the folder picker stays inside its roots; export, check and import run as jobs with
progress, a log file and cancelling (only while nothing has changed)."""
import time

import pytest
from fastapi.testclient import TestClient

from rozvedka import dataset, datajobs, db, folders
from test_dataset import a, export, use  # noqa: F401 - fixtures and helpers of the dataset tests


@pytest.fixture
def roots(tmp_path, monkeypatch):
    box = tmp_path / "exchange"
    box.mkdir()
    monkeypatch.setenv("ROZVEDKA_EXCHANGE_DIRS", str(box))
    monkeypatch.setattr(folders, "roots", lambda: [box.resolve()])
    return box


def wait(timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        j = datajobs.state()
        if j and j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_folders_stay_inside_their_roots(roots, tmp_path):
    (roots / "usb").mkdir()
    (roots / "escape").symlink_to("/etc")
    assert folders.allowed(roots / "usb") == (roots / "usb").resolve()
    assert folders.allowed("/etc") is None and folders.allowed(roots / "escape") is None      # symlinks cannot lead out
    assert folders.allowed(roots / ".." / "exchange" / "usb") is not None
    with pytest.raises(PermissionError):
        folders.listing("/etc")
    d = folders.listing(str(roots))
    assert [x["name"] for x in d["dirs"]] == ["usb"] and d["writable"] and d["free"] > 0      # the symlink to /etc is not listed as usable
    for bad in ("../x", "a/b", ".hidden", ""):
        with pytest.raises(ValueError):
            folders.make(str(roots), bad)
    assert folders.make(str(roots), "rozvedka").is_dir()


def test_export_check_import_as_jobs(a, roots, tmp_path, monkeypatch):  # noqa: F811
    from rozvedka.app import app
    client = TestClient(app)
    assert client.post("/api/data/export", data={"dest": "/etc", "what": "all"}).status_code == 400
    r = client.post("/api/data/export", data={"dest": str(roots), "what": "all", "part_size": "50", "name": "t"})
    assert r.json() == {"started": r.json()["started"]}
    j = wait()
    assert j["status"] == "done" and j["kind"] == "export" and "Writing the dataset" in j["phases"]
    assert j["result"]["scope"]["files_included"] == 2 and j["log_file"].startswith("export-")
    log = client.get(f"/data/logs/{j['log_file']}").text
    assert "dataset" in log and "written" in log
    assert client.get("/data/logs/..%2F..%2Frozvedka.db").status_code == 404
    listing = client.get("/api/data/folders", params={"path": str(roots)}).json()
    ds = listing["datasets"][0]
    assert ds["complete"] and ds["label"] == "t" and ds["parts"] == ds["parts_present"]
    # check against an empty installation, then import
    use(monkeypatch, tmp_path / "B")
    client.post("/api/data/check", data={"manifest": ds["manifest"]})
    j = wait()
    assert j["kind"] == "check" and j["status"] == "done" and j["result"]["compare"]["empty_here"]
    assert "Choose below" in j["result"]["text"]
    client.post("/api/data/import", data={"manifest": ds["manifest"], "prefer": "local"})
    j = wait(60)
    assert j["status"] == "done" and j["result"]["mode"] == "restore" and not j["cancellable"]
    with db.session() as con:
        assert con.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 3
    assert "Data exchange" in client.get("/data").text


def test_cancel_only_before_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(datajobs, "logs_dir", lambda: tmp_path / "logs")

    def slow(final_after=None):
        for i in range(400):
            dataset._tick("Working", i, 400, final=(final_after is not None and i >= final_after))
            time.sleep(0.005)
        return {"ok": True}

    datajobs.start("export", slow)
    assert datajobs.start("export", slow)["error"].startswith("another export")              # one job at a time
    time.sleep(0.1)
    assert datajobs.cancel()
    j = wait()
    assert j["status"] == "cancelled" and "removed" in j["error"]
    datajobs.start("import", slow, final_after=5)                                            # past the point of no return
    time.sleep(0.2)
    assert datajobs.cancel() is False
    j = wait()
    assert j["status"] == "done" and j["progress"]["total"] == 400
