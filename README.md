# Rozvedka

A local library of the public reports that European intelligence, cyber-security, civil-protection and police agencies publish, plus reports from EU bodies and NATO. It runs on this Raspberry Pi.

- `sources/registry.yaml` lists the agencies and their report pages (language + current/archive). Edit it by hand.
- `sources/sources.md` is the readable version of the registry. Rebuild it with `python3 tools/build_sources_md.py`.
- `data/rozvedka.db` is the SQLite catalogue of sources, pages and documents.
- `data/files/<country>/<agency>/<year>_<lang>_<name>.pdf` holds the downloaded reports.

## Commands

```bash
.venv/bin/python -m rozvedka sync-registry            # load registry.yaml into the DB
.venv/bin/python -m rozvedka crawl [--country CZ] [--agency BIS]   # find documents (no download)
.venv/bin/python -m rozvedka download [--country CZ] [--limit N] [--retry-failed]
.venv/bin/python -m rozvedka update                   # crawl + download (what the weekly timer runs)
.venv/bin/python -m rozvedka serve                    # portal on http://<pi>:8080
.venv/bin/python -m rozvedka stats
.venv/bin/python -m rozvedka fetch-logos [--refresh]  # agency logos from home pages -> data/logos/
.venv/bin/python -m rozvedka improve-titles           # poor titles -> title stored in the PDF
python3 tools/check_registry.py                       # check that every registry URL still loads
```

## How sources are fetched (`access` in the registry)

| access | behaviour |
|---|---|
| `auto` | plain HTTP fetch |
| `browser-ua` | same, with curl fallback for servers that reject Python's TLS handshake |
| `tls-lenient` | skip certificate verification (server sends an incomplete chain) |
| `browser-js` | page is rendered with headless Chromium (`/usr/bin/chromium`) |
| `manual` | bot-protected; add documents in the portal (Sources → "Add a document by URL") |

Pages that turn out to be empty JavaScript shells are rendered with Chromium automatically.
Fetching is polite: it waits 2 s between requests to the same host and respects robots.txt.

## Setup

```bash
git clone https://github.com/iiogurt/Rozvedka.git ~/Documents/Projects/Rozvedka
cd ~/Documents/Projects/Rozvedka
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

`data/` is not in git. It is created on first run and holds the database and the downloaded PDFs. Back it up separately.

## Run as a service (systemd user units, no root needed)

```bash
systemctl --user link "$PWD/deploy/rozvedka-web.service" "$PWD/deploy/rozvedka-update.service" "$PWD/deploy/rozvedka-update.timer"
systemctl --user daemon-reload
systemctl --user enable --now rozvedka-web.service rozvedka-update.timer
sudo loginctl enable-linger "$USER"      # keep user services running without a login session
```

The portal has no login. It listens on your LAN (port 8080), so don't expose it to the internet.

## Git workflow

- `main` always holds working code. Make changes on a branch (`feat/…`, `fix/…`, `sources/…`) and merge through a pull request.
- Never commit `data/`, `.env` or credentials. `.gitignore` covers these.
- Edits to the registry go in their own commits (e.g. `sources: add Latvian SAB reports page`), so the list of sources has a clear history.

## Agency profiles, flags and logos

- Every registry entry has `name_local` (official name in the original language), `name_en` (official English name),
  `homepage` and a short `description` of what its reports cover.
- Flags in `rozvedka/static/flags/` come from [flag-icons](https://github.com/lipis/flag-icons) (MIT, see
  `LICENSE.flag-icons`). `nato.svg` and `other.svg` were drawn for this project.
- Logos are the agencies' own marks. `fetch-logos` downloads them into `data/logos/`, which is not committed. When the
  automatic pick is wrong, set `logo: "https://…"` on the registry entry and run `fetch-logos --refresh`.
  Agencies without a logo show an initials badge.

## World map (`/map`)

- A pin marks each agency's headquarters, coloured by agency type. Solid pins are an exact building address. Hollow
  pins are street or city level, used where the house number didn't match or the service doesn't publish its address.
- Countries are shaded by number of reports. Clicking a country opens its documents, and clicking a pin shows the
  agency's profile. Agencies in the same city are grouped into clusters.
- `/map#s-<id>` zooms to one agency (linked from each card on the Sources page). `/map?tiles=0` hides the street map,
  and the country outlines still work offline.
- Addresses are the publicly listed headquarters or contact addresses, stored in the registry as
  `hq: {address, lat, lon, precision}`. Coordinates were geocoded once with OpenStreetMap Nominatim, and the portal
  makes no geocoding calls at runtime.
- Third-party code and data in `rozvedka/static/`: Leaflet 1.9.4 (BSD-2), Leaflet.markercluster 1.5.3 (MIT) and Natural
  Earth country outlines (public domain). Street tiles load from the OpenStreetMap tile servers in the viewer's browser,
  under the OSM tile usage policy (© OpenStreetMap contributors).
