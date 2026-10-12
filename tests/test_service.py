"""The optional systemd user service: the unit is filled in correctly and installing never enables or starts it."""
from pathlib import Path

from rozvedka import service


def test_unit_is_filled_in(tmp_path):
    text = service.render("127.0.0.1", 8099, root=tmp_path / "proj", data=tmp_path / "proj" / "data")
    assert not any(k in text for k in ("@ROZVEDKA_DIR@", "@HOST@", "@PORT@", "@DATA_DIR@"))
    assert f"WorkingDirectory={tmp_path}/proj\n" in text
    assert f"ExecStart={tmp_path}/proj/.venv/bin/python -m rozvedka serve\n" in text
    assert "ROZVEDKA_HOST=127.0.0.1 ROZVEDKA_PORT=8099" in text
    # with ProtectSystem=strict the portal must be allowed to write in its own folder (database, reports, review files)
    assert f"ReadWritePaths={tmp_path}/proj -/media" in text and "  " not in text.split("ReadWritePaths=")[1].split("\n")[0]


def test_data_folder_outside_the_project_is_writable_too(tmp_path):
    text = service.render(root=tmp_path / "proj", data=tmp_path / "elsewhere" / "data")
    assert f"ReadWritePaths={tmp_path}/proj {tmp_path}/elsewhere/data -/media" in text


def test_install_writes_the_file_and_nothing_else(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_systemctl", lambda *a: calls.append(a))
    r = service.install("t", "0.0.0.0", 8080, unit_dir=tmp_path)
    assert (tmp_path / "t.service").read_text().startswith("# systemd USER unit")
    assert r["enabled"] is False and r["started"] is False and r["reloaded"] is None and calls == []
    assert service.uninstall("t", tmp_path) == {"removed": True, "reloaded": None} and not (tmp_path / "t.service").exists()
    assert service.uninstall("t", tmp_path)["removed"] is False
    assert calls == []          # into another folder: systemd is not asked at all


def test_no_timer_is_shipped():
    deploy = Path(service.TEMPLATE).parent
    assert [p.name for p in deploy.iterdir()] == ["rozvedka-web.service"]      # the owner declined periodic jobs
