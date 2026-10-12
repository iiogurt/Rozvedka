"""Optional systemd user service for the portal (deploy/rozvedka-web.service).

Nothing here is automatic: `install` writes the unit file and reloads systemd, it never enables or starts the service,
and nothing in the project calls it. Without `loginctl enable-linger` (needs sudo, not done by this project) a user
service runs only while that user is logged in."""
import shutil
import subprocess
from pathlib import Path

from .config import DATA, ROOT

TEMPLATE = ROOT / "deploy" / "rozvedka-web.service"
UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
DEFAULT = {"name": "rozvedka-web", "host": "0.0.0.0", "port": 8080}


def render(host: str = DEFAULT["host"], port: int = DEFAULT["port"], root: Path = ROOT, data: Path = DATA) -> str:
    """The unit with the folder and address filled in (the data folder is listed too when it lies outside the project)."""
    inside = str(data.resolve()).startswith(str(root.resolve()))
    text = TEMPLATE.read_text(encoding="utf-8")
    for key, value in (("@ROZVEDKA_DIR@", str(root)), ("@DATA_DIR@", "" if inside else str(data)),
                       ("@HOST@", host), ("@PORT@", str(port))):
        text = text.replace(key, value)
    return text.replace("ReadWritePaths=" + str(root) + "  ", "ReadWritePaths=" + str(root) + " ")      # no gap when DATA_DIR is empty


def path_of(name: str = DEFAULT["name"], unit_dir: Path | None = None) -> Path:
    return (unit_dir or UNIT_DIR) / f"{name}.service"


def install(name: str = DEFAULT["name"], host: str = DEFAULT["host"], port: int = DEFAULT["port"],
            unit_dir: Path | None = None, reload: bool = True) -> dict:
    """Write the unit file (and `systemctl --user daemon-reload`). The service is neither enabled nor started."""
    target = path_of(name, unit_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(host, port), encoding="utf-8")
    reloaded = _systemctl("daemon-reload") if reload and unit_dir is None else None
    return {"written": str(target), "reloaded": reloaded, "enabled": False, "started": False,
            "next": [f"systemctl --user start {name}", f"systemctl --user enable {name}   # also start it at every login"]}


def uninstall(name: str = DEFAULT["name"], unit_dir: Path | None = None) -> dict:
    """Remove the unit file; refuses while the service is running or enabled (stop or disable it first)."""
    target = path_of(name, unit_dir)
    if unit_dir is None:
        state = status(name)
        if state["active"] == "active" or state["enabled"] == "enabled":
            return {"error": f"{name} is {state['active']} / {state['enabled']}: run `systemctl --user disable --now {name}` first"}
    removed = target.exists()
    if removed:
        target.unlink()
    return {"removed": removed, "reloaded": _systemctl("daemon-reload") if removed and unit_dir is None else None}


def status(name: str = DEFAULT["name"], unit_dir: Path | None = None) -> dict:
    """Installed? enabled? active? ("unknown" when systemd's user manager is not reachable)."""
    out = {"unit_file": str(path_of(name, unit_dir)), "installed": path_of(name, unit_dir).exists()}
    for key, verb in (("enabled", "is-enabled"), ("active", "is-active")):
        out[key] = _systemctl(verb, name) or "unknown"
    return out


def verify(name: str = DEFAULT["name"], unit_dir: Path | None = None) -> str:
    """`systemd-analyze --user verify` on the installed file: empty = no complaints."""
    exe = shutil.which("systemd-analyze")
    if not exe:
        return "systemd-analyze not found"
    r = subprocess.run([exe, "--user", "verify", str(path_of(name, unit_dir))], capture_output=True, text=True, timeout=30)
    return (r.stdout + r.stderr).strip()


def _systemctl(*args: str) -> str | None:
    exe = shutil.which("systemctl")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--user", *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or (None if r.returncode == 0 else r.stderr.strip() or None)
