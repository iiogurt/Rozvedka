"""Request checks for a portal without login (it is meant for one machine or a home network).

- **Host names**: a request must address the portal by an IP address, `localhost`, a `.local` / `.lan` / `.home.arpa`
  name, this machine's host name, or a name listed in ROZVEDKA_ALLOWED_HOSTS (comma-separated). Other names are
  refused: a web page could otherwise point its own domain at this machine (DNS rebinding) and read the portal.
- **Other sites**: a request that changes something (anything but GET / HEAD / OPTIONS) is refused when the browser
  says it comes from another site (Origin or Referer header), so a page elsewhere cannot start updates, imports or
  downloads through the visitor's browser (cross-site request forgery). Tools that send neither header still work.
- **Headers** on every response: no framing by other sites, no MIME sniffing, no referrer sent to other sites.
"""
import ipaddress
import os
import socket
from functools import lru_cache
from urllib.parse import urlsplit

LOCAL_SUFFIXES = (".localhost", ".local", ".lan", ".home.arpa")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "SAMEORIGIN",
    "Content-Security-Policy": "frame-ancestors 'self'; base-uri 'self'; object-src 'none'; form-action 'self'",
}


def _host_only(host: str) -> str:
    """'example.org:8080' → 'example.org', '[::1]:8080' → '::1'; lowercase, without a trailing dot."""
    host = host.strip().lower()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else host
    if host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return host.rstrip(".")


@lru_cache(maxsize=1)
def _own_names() -> frozenset[str]:
    names = {"localhost"}
    try:
        h = socket.gethostname().lower()
        names |= {h, h.split(".")[0], socket.getfqdn().lower()}
    except OSError:
        pass
    return frozenset(n for n in names if n)


def allowed_host(host: str) -> bool:
    h = _host_only(host)
    if not h:
        return False
    try:
        ipaddress.ip_address(h)
        return True                       # an address cannot be re-pointed by someone else's DNS
    except ValueError:
        pass
    extra = {_host_only(x) for x in os.environ.get("ROZVEDKA_ALLOWED_HOSTS", "").split(",") if x.strip()}
    return h in _own_names() or h in extra or h.endswith(LOCAL_SUFFIXES)


def same_site(method: str, host: str, origin: str | None, referer: str | None) -> bool:
    """False when a state-changing request comes from a page on another host."""
    if method.upper() in SAFE_METHODS:
        return True
    source = origin if origin and origin != "null" else referer
    if origin == "null":                  # sandboxed frames and some redirects: no way to tell – refuse
        return False
    if not source:
        return True                       # not from a browser page (curl, scripts)
    return _host_only(urlsplit(source).netloc) == _host_only(host) and bool(urlsplit(source).netloc)
