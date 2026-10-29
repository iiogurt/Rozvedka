"""HTTP fetching: browser-like headers, per-host rate limit, robots.txt, curl fallback."""
import json
import re
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
_unreadable: dict[str, str] = {}      # sites whose robots.txt could not be read this run, and why


class Blocked(Exception):
    """robots.txt disallows the URL, or could not be read (then nothing on the site is fetched)."""

    def __init__(self, reason: str = "blocked by robots.txt"):
        super().__init__(reason)


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
        # 200: its rules; 4xx: the site has none; a 5xx or no answer at all: fetch nothing (a failed robots.txt is
        # not a permission – this once let a retry download from a site whose robots.txt forbids it)
        rp = urllib.robotparser.RobotFileParser()
        try:
            try:
                with _client(lenient) as c:
                    r = c.get(base + "/robots.txt", timeout=15)
                status, text = r.status_code, r.text
            except (httpx.TransportError, httpx.TimeoutException):
                if not shutil.which("curl"):
                    raise
                r = _curl(base + "/robots.txt", None, lenient)       # the TLS fallback, as for the pages themselves
                status, text = r.status, r.text
            if status == 200:
                rp.parse(text.splitlines())
            elif 400 <= status < 500:
                rp.parse([])
            else:
                raise RuntimeError(f"http {status}")
        except Exception as e:  # noqa: BLE001 - any failure means: do not fetch
            _unreadable[base] = f"{type(e).__name__}: {e}"[:120]
            rp.parse(["User-agent: *", "Disallow: /"])
        _robots[base] = rp
    rp = _robots[base]
    return rp.can_fetch(USER_AGENT, url) if rp else True


def blocked(url: str) -> Blocked:
    """The Blocked error for a URL that allowed() refused, saying whether the rules or an unreadable file refused it."""
    parts = urlsplit(url)
    why = _unreadable.get(f"{parts.scheme}://{parts.netloc}")
    return Blocked(f"robots.txt could not be read ({why}) – not fetched" if why else "blocked by robots.txt")


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
        raise blocked(url)
    _wait(urlsplit(url).netloc)
    try:
        with _client(lenient) as c:
            r = c.get(url)
        return Response(str(r.url), r.status_code, r.headers.get("content-type", ""), r.content)
    except (httpx.TransportError, httpx.TimeoutException) as e:
        if shutil.which("curl"):
            return _curl(url, None, lenient)
        raise e


FIREFOX = shutil.which("firefox") or shutil.which("firefox-esr")
CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
_render_lock = threading.Semaphore(1)   # one browser at a time – the Pi has limited RAM


def render(url: str, budget_ms: int = 15000) -> Response:
    """Render a JavaScript-built page with a headless browser and return the final DOM. Firefox comes first: since
    October 2026 headless Chromium on Raspberry Pi OS loads remote pages but never finishes the navigation."""
    if not (FIREFOX or CHROMIUM):
        raise RuntimeError("no firefox or chromium available for JavaScript rendering")
    if not allowed(url):
        raise blocked(url)
    _wait(urlsplit(url).netloc)
    with _render_lock:
        return _firefox(url, budget_ms) if FIREFOX else _chromium(url, budget_ms)


def _firefox(url: str, budget_ms: int) -> Response:
    """Headless Firefox driven over WebDriver BiDi: open the page, let its scripts run, read the DOM."""
    from websockets.sync.client import connect     # comes with uvicorn[standard]
    with tempfile.TemporaryDirectory() as profile:
        Path(profile, "user.js").write_text(f'user_pref("general.useragent.override", "{USER_AGENT}");\n')
        proc = subprocess.Popen([FIREFOX, "--headless", "--no-remote", "--profile", profile, "--remote-debugging-port=0"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            endpoint = next((m.group(1) for line in proc.stderr
                             if (m := re.search(r"WebDriver BiDi listening on (ws://\S+)", line))), None)
            if not endpoint:
                raise RuntimeError("firefox did not open its WebDriver BiDi port")
            threading.Thread(target=proc.stderr.read, daemon=True).start()   # keep the pipe from filling up
            with connect(endpoint + "/session", max_size=200 * 2**20) as ws:
                ids = iter(range(1, 100))

                def call(method: str, **params):
                    n = next(ids)
                    ws.send(json.dumps({"id": n, "method": method, "params": params}))
                    while True:
                        msg = json.loads(ws.recv(timeout=budget_ms / 1000 + 90))
                        if msg.get("id") == n:
                            if msg.get("type") == "error":
                                raise RuntimeError(f"firefox: {msg.get('error')}: {msg.get('message', '')[:200]}")
                            return msg["result"]

                call("session.new", capabilities={})
                context = call("browsingContext.getTree")["contexts"][0]["context"]
                # "interactive" (the document is parsed), not "complete": some sites keep one resource loading forever
                final = call("browsingContext.navigate", context=context, url=url, wait="interactive").get("url") or url
                time.sleep(min(budget_ms, 5000) / 1000)   # lists that scripts fill in after that
                html = call("script.evaluate", expression="document.documentElement.outerHTML",
                            target={"context": context}, awaitPromise=False)["result"]["value"]
                call("session.end")
        finally:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
    return Response(final, 200, "text/html", html.encode())


def _chromium(url: str, budget_ms: int) -> Response:
    with tempfile.TemporaryDirectory() as profile:
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
        raise blocked(url)
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
