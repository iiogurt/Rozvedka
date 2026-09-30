"""Render sources/registry.yaml as a readable Markdown overview (sources/sources.md)."""
import yaml
NAMES = {"CZ":"Czechia","SK":"Slovakia","PL":"Poland","DE":"Germany","AT":"Austria","EE":"Estonia","LV":"Latvia",
 "LT":"Lithuania","FI":"Finland","SE":"Sweden","DK":"Denmark","NL":"Netherlands","BE":"Belgium","FR":"France",
 "IT":"Italy","ES":"Spain","PT":"Portugal","HU":"Hungary","RO":"Romania","BG":"Bulgaria","HR":"Croatia",
 "SI":"Slovenia","GR":"Greece","CY":"Cyprus","LU":"Luxembourg","IE":"Ireland","MT":"Malta",
 "EU":"European Union bodies","NATO":"NATO","OTHER":"Other (outside EU/NATO)"}
srcs = yaml.safe_load(open("sources/registry.yaml"))
out = ["# Rozvedka – official security report sources\n",
       f"Generated from `sources/registry.yaml` — {len(srcs)} sources, {sum(len(s['pages']) for s in srcs)} pages.\n",
       "Link label = `language · kind` (current = latest edition, archive = older editions, series = one report series). "
       "⚠ = bot-protected, open in browser.\n"]
cur = None
for s in srcs:
    if s["country"] != cur:
        cur = s["country"]
        out += [f"\n## {NAMES.get(cur, cur)}\n", "| Agency | What they publish | Reports | Links |", "|---|---|---|---|"]
    links = " · ".join(f"[{p['lang']} {p['kind']}{' ⚠' if p.get('verified') is False else ''}]({p['url']})" for p in s["pages"])
    if s.get("url_pattern"):
        up = s["url_pattern"]; links += f"<br>pattern: `{up['template']}` {up['years'][0]}–{up['years'][1]}"
    notes = f"<br>_{s['notes']}_" if s.get("notes") else ""
    home = f"<br>[{s['homepage'].split('//')[1].rstrip('/')}]({s['homepage']})" if s.get("homepage") else ""
    local = f"<br>_{s['name_local']}_" if s.get("name_local") and s.get("name_local") != s.get("name_en") else ""
    out.append(f"| **{s['agency']}** – {s.get('name_en', '')}{local}{home} | {s.get('description', '')} | "
               f"{', '.join(s['report_types'])}{notes} | {links} |")
open("sources/sources.md", "w").write("\n".join(out) + "\n")
print("wrote sources/sources.md")
