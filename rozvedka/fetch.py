"""HTTP fetching: browser-like headers, per-host rate limit, robots.txt, curl fallback."""
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .config import HOST_DELAY, TIMEOUT, USER_AGENT

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "en,cs;q=0.8,*;q=0.5",
}

_lock = threading.Lock()
_last: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


class Blocked(Exception):
    """robots.txt disallows the URL."""


@dataclass
class Response:
    url: str
    status: int
    content_type: str
    body: bytes = b""

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


def _wait(host: str):
    with _lock:
        now = time.monotonic()
        delay = _last.get(host, 0) + HOST_DELAY - now
        _last[host] = max(now, _last.get(host, 0) + HOST_DELAY)
    if delay > 0:
        time.sleep(delay)


def _client(lenient: bool) -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True, verify=not lenient, http2=False)


def allowed(url: str, lenient: bool = False) -> bool:
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            with _client(lenient) as c:
                r = c.get(base + "/robots.txt", timeout=15)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except Exception:
            rp.parse([])
        _robots[base] = rp
    rp = _robots[base]
    return rp.can_fetch(USER_AGENT, url) if rp else True


def _curl(url: str, dest: Path | None, lenient: bool) -> Response:
    """Fallback for servers that reject Python's TLS handshake (seen on bund.de sites)."""
    tmp = None
    if dest is None:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
    target = Path(tmp.name) if tmp else dest
    cmd = ["curl", "-sL", "--max-time", str(int(TIMEOUT * 3)), "-A", USER_AGENT,
           "-H", f"Accept: {HEADERS['Accept']}", "-H", f"Accept-Language: {HEADERS['Accept-Language']}",
           "-w", "%{http_code}\n%{content_type}\n%{url_effective}", "-o", str(target)]
    if lenient:
        cmd.append("-k")
    try:
        out = subprocess.run(cmd + [url], capture_output=True, timeout=TIMEOUT * 3 + 10)
        if out.returncode != 0:
            raise RuntimeError(f"curl exit {out.returncode}: {out.stderr.decode()[:200]}")
        status, ctype, final = (out.stdout.decode().split("\n") + ["", "", ""])[:3]
        body = target.read_bytes() if tmp else b""
        return Response(final or url, int(status or 0), ctype, body)
    finally:
        if tmp:
            Path(tmp.name).unlink(missing_ok=True)


def get(url: str, lenient: bool = False, check_robots: bool = True) -> Response:
    if check_robots and not allowed(url, lenient):
        raise Blocked(url)
    _wait(urlsplit(url).netloc)
    try:
        with _client(lenient) as c:
            r = c.get(url)
        return Response(str(r.url), r.status_code, r.headers.get("content-type", ""), r.content)
    except (httpx.TransportError, httpx.TimeoutException) as e:
        if shutil.which("curl"):
            return _curl(url, None, lenient)
        raise e


CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
_render_lock = threading.Semaphore(1)   # one browser at a time – the Pi has limited RAM


def render(url: str, budget_ms: int = 15000) -> Response:
    """Render a JavaScript-built page with headless Chromium and return the final DOM."""
    if not CHROMIUM:
        raise RuntimeError("no chromium available for JavaScript rendering")
    if not allowed(url):
        raise Blocked(url)
    _wait(urlsplit(url).netloc)
    with _render_lock, tempfile.TemporaryDirectory() as profile:
        out = subprocess.run(
            [CHROMIUM, "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
             f"--user-data-dir={profile}", f"--user-agent={USER_AGENT}",
             f"--virtual-time-budget={budget_ms}", "--dump-dom", url],
            capture_output=True, timeout=budget_ms / 1000 + 90)
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError(f"chromium failed: {out.stderr.decode()[-200:]}")
    return Response(url, 200, "text/html", out.stdout)


def looks_like_js_shell(resp: Response) -> bool:
    """Heuristic: an HTML page that needs JavaScript before it shows any links."""
    if "html" not in resp.content_type:
        return False
    t = resp.text
    return (t.count("<a ") < 15 and ("enable javascript" in t.lower() or "loading application" in t.lower())) \
        or ('id="__next"' in t and t.count("<a ") < 15)


def download(url: str, dest: Path, lenient: bool = False, max_bytes: int = 200 * 2**20) -> Response:
    """Stream url to dest. Returns Response without body."""
    if not allowed(url, lenient):
        raise Blocked(url)
    _wait(urlsplit(url).netloc)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _client(lenient) as c, c.stream("GET", url) as r:
            size = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(65536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise RuntimeError("file too large")
                    f.write(chunk)
            return Response(str(r.url), r.status_code, r.headers.get("content-type", ""))
    except (httpx.TransportError, httpx.TimeoutException):
        if shutil.which("curl"):
            return _curl(url, dest, lenient)
        raise
