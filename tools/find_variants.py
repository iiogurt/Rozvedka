"""For each registry source, fetch its page and list candidate language versions and archive links."""
import concurrent.futures as cf, re, ssl, sys, urllib.request, yaml
from urllib.parse import urljoin
UA = "Mozilla/5.0 (X11; Linux aarch64; rv:128.0) Gecko/20100101 Firefox/128.0"
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
ARCH = re.compile(r'archiv|archive|older|previous|earlier|starsi|ältere|tidigare|aiemm|ankstesn|agrāk|eerdere|precedent|jaarverslagen|annual-reports|vyrocni-zpravy|lagebild|reports', re.I)

def run(src):
    url = src["publications_url"]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html", "Accept-Language": "en"})
        body = urllib.request.urlopen(req, timeout=25, context=ctx).read(3_000_000).decode("utf-8", "replace")
    except Exception as e:
        return src, [f"  ! {e}"]
    out = []
    for tag in re.findall(r'<link[^>]+hreflang[^>]*>', body, re.I):
        h = re.search(r'href="([^"]+)"', tag); l = re.search(r'hreflang="([^"]+)"', tag)
        if h and l: out.append(f"  hreflang {l.group(1):<6} {urljoin(url, h.group(1))}")
    for href, text in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>\s*([^<]{1,40})\s*</a>', body, re.I):
        t = text.strip()
        if re.fullmatch(r'(EN|ENG|English|DE|Deutsch|FR|Français|NL|Nederlands|SV|Svenska|FI|Suomi|ET|Eesti|LV|Latviešu|LT|Lietuvių|CS|Česky|Čeština|SK|Slovensky|PL|Polski|DA|Dansk|RU|Русский)', t, re.I):
            out.append(f"  langlink {t:<6} {urljoin(url, href)}")
        elif ARCH.search(href) and len(out) < 40:
            out.append(f"  archive? {t[:30]:<30} {urljoin(url, href)}")
    return src, sorted(set(out))

srcs = yaml.safe_load(open("sources/registry.yaml"))
with cf.ThreadPoolExecutor(12) as ex:
    for src, lines in ex.map(run, srcs):
        print(f"== {src['country']} {src['agency']}  {src['publications_url']}")
        print("\n".join(lines[:30]))
