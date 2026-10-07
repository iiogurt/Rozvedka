"""Request checks of the login-free portal: host names (DNS rebinding), cross-site changes (CSRF), headers."""
from fastapi.testclient import TestClient

from rozvedka import app as app_module
from rozvedka import guard


def test_host_names():
    for ok in ("127.0.0.1:8080", "192.168.1.20:8080", "[::1]:8080", "localhost:8080", "rozvedka.local", "pi.lan",
               "testserver"):
        assert guard.allowed_host(ok), ok
    for bad in ("evil.example.com", "evil.example.com:8080", "localhost.evil.com", ""):
        assert not guard.allowed_host(bad), bad


def test_same_site():
    assert guard.same_site("GET", "pi.local:8080", "https://evil.com", None)            # reading is not changing
    assert guard.same_site("POST", "pi.local:8080", "http://pi.local:8080", None)
    assert guard.same_site("POST", "192.168.1.5:8080", None, "http://192.168.1.5:8080/update")
    assert guard.same_site("POST", "pi.local:8080", None, None)                           # curl, scripts
    assert not guard.same_site("POST", "pi.local:8080", "https://evil.com", None)
    assert not guard.same_site("POST", "pi.local:8080", None, "https://evil.com/page")
    assert not guard.same_site("POST", "pi.local:8080", "null", None)


def test_middleware():
    client = TestClient(app_module.app)
    r = client.get("/api/version")
    assert r.status_code == 200 and r.headers["x-frame-options"] == "SAMEORIGIN" and "nosniff" in r.headers["x-content-type-options"]
    assert client.get("/api/version", headers={"host": "rebind.attacker.example"}).status_code == 421
    assert client.post("/api/job/cancel", headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/job/cancel", headers={"origin": "http://testserver"}).status_code == 200


def test_crafted_dataset_cannot_escape(tmp_path, monkeypatch):
    import json
    import pytest
    from rozvedka import config, dataset, folders
    monkeypatch.setattr(config, "FILES", tmp_path / "files")
    (tmp_path / "files").mkdir()
    assert dataset.safe_target("CZ/BIS/report.pdf") == (tmp_path / "files" / "CZ/BIS/report.pdf").resolve()
    for bad in ("../../.bashrc", "/etc/passwd", "CZ/../../x", "CZ\\..\\x", "", None):
        assert dataset.safe_target(bad) is None, bad
    m = tmp_path / "x.manifest.json"
    m.write_text(json.dumps({"format": dataset.FORMAT, "parts": [{"name": "../secret", "size": 1}],
                             "freshness": {"documents": "<img src=x onerror=alert(1)>"}}))
    with pytest.raises(ValueError, match="invalid part"):
        dataset.verify(m)
    s = folders._dataset_summary(m)
    assert s["documents"] is None and s["parts"] == 0           # markup is not a number; the bad part is ignored


def test_map_tiles_send_a_referer():
    """The portal sends no Referer to other sites, but OpenStreetMap blocks tile requests without one."""
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "rozvedka" / "static" / "map.js").read_text(encoding="utf-8")
    assert 'referrerPolicy: "strict-origin-when-cross-origin"' in js and "Referrer-Policy" in guard.HEADERS
