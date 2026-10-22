# Security policy

## Supported versions

Only the **latest release** ([releases](https://github.com/iiogurt/Rozvedka/releases/latest)) gets security fixes.
Fixes land on `main` and ship in the next release; older versions are not patched – update instead.
The pinned dependencies (`requirements*.txt`) and the CI actions are watched by Dependabot (security fixes as soon as
an advisory is out, version updates monthly), and GitHub CodeQL scans the Python and JavaScript code.

## Reporting a vulnerability

Report it **privately** through GitHub's private vulnerability reporting:
**<https://github.com/iiogurt/Rozvedka/security/advisories/new>**

Please **do not open a public issue, pull request or discussion** for a vulnerability. Include what you found, the
version (`python -m rozvedka --version` or the portal footer), the steps to reproduce it and what an attacker could do.

What to expect:

- an acknowledgement within about a week – this is a one-maintainer project, run in spare time;
- an assessment, and questions if something is unclear, in the advisory thread;
- a fix in a new release, the advisory published once the release is out, and credit if you want it.

## How Rozvedka is meant to be deployed

Rozvedka is a portal for **one person on one computer or a trusted home network**. It has **no login**, by design.

- `serve` listens on `127.0.0.1` by default; `--host 0.0.0.0` (or `ROZVEDKA_HOST`) opens it to the local network.
- Anyone who can reach the portal can use all of it: start crawls and downloads, add documents by URL (which makes the
  portal fetch that URL), import and export datasets, review matches and edit records.
- It must **never be exposed to the internet** (no port forwarding, no public server, no reverse proxy without
  authentication). For remote access use a VPN.

So "an unauthenticated user on the network can control the portal" is **documented behaviour, not a vulnerability**.
Reports about it will be closed unless they show a way around the protections below.

## What the portal does protect against

These are in scope – a way around any of them is a vulnerability worth reporting:

- **Cross-site requests and DNS rebinding** (`rozvedka/guard.py`): requests that change something are refused when the
  browser says they come from another site, and the portal answers only to IP addresses, `localhost`, local names
  (`*.local`, `*.lan`, `*.home.arpa`), the machine's own name and names in `ROZVEDKA_ALLOWED_HOSTS`. Responses forbid
  framing by other sites, MIME sniffing and cross-site referrers.
- **File system access** (`rozvedka/folders.py`): the Data exchange folder picker lists only `/media`, `/mnt`,
  `/run/media`, `/Volumes`, the home folder of the user running the portal and the folders in `ROZVEDKA_EXCHANGE_DIRS`;
  PDFs, logos and pictures are served only from `data/`.
- **Untrusted datasets** (`rozvedka/dataset.py`): an import checks every file's SHA-256, writes report files only below
  `data/files/`, reads part files only from the manifest's folder and shows manifest values only as text and numbers.
- **Untrusted content from agency sites**: agency logos (which may be SVG) are served with a policy that forbids
  scripts; report text and titles are escaped by the templates.

## Outbound connections

Rozvedka fetches, only when you run an update or a `fetch-…` command: the agencies' and think tanks' sites (robots.txt
respected, one request per host every 2 s), Wikidata, Wikipedia, Wikimedia Commons, MITRE ATT&CK, Our World in Data, the
World Bank, and the official sanctions and lobbying registers. No telemetry, no accounts, no CDN at runtime; the map's
street tiles are loaded by the viewer's browser from OpenStreetMap.

The few JavaScript-only report pages are rendered by **headless Chromium without its sandbox** (needed under some
service managers) – keep Chromium updated with the system. Python dependencies are pinned in `requirements.txt` and
checked with `pip-audit`.
