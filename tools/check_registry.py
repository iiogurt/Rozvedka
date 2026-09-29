"""Check every page URL in the registry: HTTP status, redirects, and number of PDF links found."""
import concurrent.futures as cf, re, ssl, sys, urllib.error, urllib.request, yaml

UA = "Mozilla/5.0 (X11; Linux aarch64; rv:128.0) Gecko/20100101 Firefox/128.0"
STRICT = ssl.create_default_context()
LENIENT = ssl.create_default_context(); LENIENT.check_hostname = False; LENIENT.verify_mode = ssl.CERT_NONE

def check(job):
    src, page = job
    ctx = LENIENT if src.get("access") == "tls-lenient" else STRICT
    try:
        req = urllib.request.Request(page["url"], headers={"User-Agent": UA, "Accept": "text/html,*/*", "Accept-Language": "en"})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            body = r.read(3_000_000).decode("utf-8", "replace")
            pdfs = len(set(re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', body, re.I)))
            return src, page, r.status, r.geturl(), pdfs
    except urllib.error.HTTPError as e:
        return src, page, e.code, page["url"], 0
    except Exception as e:
        return src, page, type(e).__name__, page["url"], 0

srcs = yaml.safe_load(open(sys.argv[1] if len(sys.argv) > 1 else "sources/registry.yaml"))
jobs = [(s, p) for s in srcs for p in s["pages"]]
bad = 0
with cf.ThreadPoolExecutor(12) as ex:
    for src, page, status, final, pdfs in ex.map(check, jobs):
        ok = status == 200
        expected_fail = src.get("access") == "manual" or page.get("verified") is False
        flag = "OK  " if ok else ("SKIP" if expected_fail else "ERR ")
        bad += (not ok and not expected_fail)
        moved = "" if final.rstrip("/") == page["url"].rstrip("/") else f" -> {final}"
        print(f"{flag} {status!s:>5} pdf={pdfs:<3} {src['country']:<5} {src['agency'][:18]:<18} {page['lang']:<6} {page['kind']:<8} {page['url']}{moved}")
print(f"\n{len(srcs)} sources, {len(jobs)} pages, {bad} unexpected failures")
