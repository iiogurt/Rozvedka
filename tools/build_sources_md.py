"""Render sources/registry.yaml as a readable Markdown overview (sources/sources.md)."""
import sys
from pathlib import Path

import yaml
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rozvedka import countries  # noqa: E402

NAMES = countries.names()
srcs = yaml.safe_load(open("sources/registry.yaml"))
out = ["# Rozvedka – report sources: official agencies and ◆ independent think tanks\n",
       f"Generated from `sources/registry.yaml` — {len(srcs)} sources, {sum(len(s['pages']) for s in srcs)} pages.\n",
       "Link label = `language · kind` (current = latest edition, archive = older editions, series = one report series). "
       "⚠ = bot-protected, open in browser.\n"]
official = [s for s in srcs if s.get("publisher", "official") == "official"]
independent = [s for s in srcs if s.get("publisher") == "independent"]


def row(s, country=False):
    links = " · ".join(f"[{p['lang']} {p['kind']}{' ⚠' if p.get('verified') is False else ''}]({p['url']})" for p in s["pages"])
    if s.get("url_pattern"):
        up = s["url_pattern"]; links += f"<br>pattern: `{up['template']}` {up['years'][0]}–{up['years'][1]}"
    notes = f"<br>_{s['notes']}_" if s.get("notes") else ""
    home = f"<br>[{s['homepage'].split('//')[1].rstrip('/')}]({s['homepage']})" if s.get("homepage") else ""
    local = f"<br>_{s['name_local']}_" if s.get("name_local") and s.get("name_local") != s.get("name_en") else ""
    where = f"{NAMES.get(s['country'], s['country'])} | " if country else ""
    return (f"| {where}**{s['agency']}** – {s.get('name_en', '')}{local}{home} | {s.get('description', '')} | "
            f"{', '.join(s['report_types'])}{notes} | {links} |")


cur = None
for s in official:
    if s["country"] != cur:
        cur = s["country"]
        tags = " · ".join(f"{countries.coalitions()[k]['short']} ({y})" for k, y in countries.memberships(cur).items())
        out += [f"\n## {NAMES.get(cur, cur)}\n", *([f"_{tags}_\n"] if tags else []),
                "| Agency | What they publish | Reports | Links |", "|---|---|---|---|"]
    out.append(row(s))
if independent:
    out += ["\n## ◆ Independent publishers – think tanks\n",
            "_Not run by a state; marked ◆ in every view of the portal and left out by “Official agencies only”._\n",
            "| Country | Publisher | What they publish | Reports | Links |", "|---|---|---|---|---|"]
    out += [row(s, country=True) for s in sorted(independent, key=lambda s: (NAMES.get(s["country"], s["country"]), s["agency"]))]
open("sources/sources.md", "w").write("\n".join(out) + "\n")
print("wrote sources/sources.md")
