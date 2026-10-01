# Changelog

All notable changes to Rozvedka are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Before 1.0.0, a minor version can change the data model or the
registry format.

Each release is tagged `v<version>` on `main` (e.g. `v0.6.0`). The version shown in the portal footer comes from
`rozvedka/__init__.py`.

## Versioning

From 0.9.1 on, the significance of a change decides which part of `MAJOR.MINOR.PATCH` goes up:

| Level | When | Examples |
|---|---|---|
| **patch** – 0.9.0 → 0.9.**1** | nothing new to learn: fixes, content and small visual changes | bug fix; new or corrected sources in the registry; topic keyword changes; logo/flag updates; styling; docs |
| **minor** – 0.9.1 → 0.**10**.0 | a new capability | new page or view; new filter or search; new command; new field in the registry or database (migrated automatically) |
| **major** – 0.10.0 → **1**.0.0 | an incompatible change | registry or database format that needs manual migration; removed or renamed command; changed URL structure |

- Several changes in one release: the most significant one decides.
- Between releases the portal footer and `python -m rozvedka --version` show the build, e.g. `0.9.1+3.g1a2b3c4`
  (3 commits after v0.9.1, commit `1a2b3c4`; `.dirty` = uncommitted local changes).
- Releases 0.2.0–0.9.0 were numbered before this rule and each raised the minor version.
- To release: `python3 tools/bump_version.py patch|minor|major` moves the notes below into a new version section and
  sets the version; merge, then tag the merge commit `v<version>`.

## [Unreleased]

## [0.9.2] – 2026-10-01

### Fixed
- Report years no longer come from horizon years in titles ("NATO 2030", "Trendanalyse 2035"): years after the
  current one are skipped and the next candidate (filename, upload path) is used. The next crawl corrects years
  stored earlier (6 documents).

## [0.9.1] – 2026-09-30

### Added
- Significance-based versioning (patch / minor / major, table above) and `tools/bump_version.py` to apply it.
- Build identifier from git between releases, shown in the portal footer, at `/api/version` and by `--version`.

## [0.9.0] – 2026-09-30

### Added
- Ukraine: SSSCIP / CERT-UA (half-yearly "Russian Cyber Operations" reports), Center for Countering
  Disinformation, and the National Institute for Strategic Studies. All three are manual: the sites deny
  automated access, or forbid crawling of their files in robots.txt.
- Latin America (new region):
  - **Brazil:** ABIN "Desafios de Inteligência" in Portuguese, Spanish and English.
  - **Colombia:** UNGRD annual management reports 2004–2025; colCERT's cyber-threat trends report.
  - **Peru:** INDECI statistical compendia 1995–2021.
  - **Argentina:** national crime statistics.
  - **Mexico:** CENAPRED socio-economic disaster impact series (manual).
  - **Chile:** CSIRT and SENAPRED (manual).
- The crawler recognises DSpace repository download links (`/bitstreams/<id>/download`).

### Fixed
- Link titles with a file size, such as "report.pdf (77.28 MB)", are cleaned before being judged.
- Citizen-service policies and daily operational bulletins are hidden by default.

## [0.8.0] – 2026-09-30

### Added
- Topic index: 64 topics in 9 categories, with 3,800+ keywords in 28 languages (`sources/topics.yaml`). The
  categories are extremism & terrorism, state threats, war & geopolitics, cyber, crime, migration, disasters &
  climate, resilience & preparedness, and governance. Examples: right-wing extremism, Russia, China,
  disinformation, sabotage, ransomware, floods, energy security, civil defence.
- `index-topics` extracts each report's text (`pdftotext`, first 150 pages) into a full-text index and tags the
  report with its topics. A topic is assigned when the title matches, or when several different keywords appear
  often enough for the document's length. Changing `topics.yaml` re-classifies from the stored text without
  downloading again. The weekly update runs it automatically.
- Documents list: topic filter (several topics = all must match), topic tags on every document, relevance sorting,
  and full-text search inside the reports with highlighted snippets.
- Topics page (`/topics`): every topic with its document, agency and country counts and year range.
- Map: topic filter. Country shading and agency counts then include only reports on that topic.

## [0.7.0] – 2026-09-30

### Added
- Hover card on every HQ pin: logo, flag, names in both languages, agency type, coalitions, the first sentence of
  the description, document count and years, and whether the HQ location is exact. Clicking still opens the full
  card with links.
- Hovering a cluster lists the agencies inside it. Hovering the agency list highlights the pin on the map.

### Changed
- The map page uses a dark theme: dark panel, controls, popups and clusters, pin colours tuned for dark
  backgrounds, and country shading that gets brighter with more reports (with a legend).
- The street map is standard OpenStreetMap, darkened in the browser with a CSS filter. It needs no API key and
  no third-party tile service.
- Coalition tags follow the same order everywhere (EU, NATO, Five Eyes, …).

## [0.6.0] – 2026-09-30

### Added
- Coalition memberships for every country: EU, NATO, Five Eyes, G7, Schengen, AUKUS, Joint Expeditionary Force
  and NATO's Indo-Pacific partners, each with the year the country joined (`sources/countries.yaml`).
- Coalition tags beside each country on the Sources page, and coalition filters on the Sources page, the
  documents list (`/?coalition=NATO`) and the map. The EU and NATO filters also include their own institutions.
- App versioning: `rozvedka.__version__`, `python -m rozvedka --version`, version in the portal footer.
- This changelog, shown in the portal at `/changelog`.

### Changed
- Country names and regions now live in `sources/countries.yaml` instead of Python code.

## [0.5.0] – 2026-09-30

### Added
- 26 agencies from other democracies: United Kingdom, USA, Canada, Australia, New Zealand, Norway, Switzerland,
  Japan, South Korea and Taiwan (665 more reports).
- Sources page grouped by region. The map opens on all agencies and has World, Europe, North America and
  Asia-Pacific buttons.
- `tools/geocode_hq.py` fills in coordinates for new registry entries.
- Optional `domains:` per registry entry for agencies with several official domains.

### Changed
- DIA and ODNI moved from "Other" to the United States.

### Fixed
- The crawler collected third-party PDFs cited in footnotes. Documents must now be on the agency's own
  domains, and 86 existing ones are hidden.
- A HQ address geocoded to a namesake (London, Ontario). Registry tests now check each HQ against its country.
- Two document titles were rewritten on every run.

## [0.4.0] – 2026-09-30

### Added
- World map (`/map`): agency headquarters, clusters, countries shaded by number of reports, filters, search,
  popups with profile and links, `/map#s-<id>` deep links, offline mode `/map?tiles=0`.
- HQ address and coordinates for every agency (precision: address, street or city).
- Registry consistency tests.

### Fixed
- The map froze without a tile layer (markercluster looped with an unbounded max zoom).

## [0.3.0] – 2026-09-30

### Added
- Agency profiles: official original-language and English name, home page, description.
- Country flags. Sources page redesigned as profile cards with a flag bar.
- `fetch-logos`: each agency's logo from its home page, with a no-script CSP for third-party SVGs.
- `improve-titles`: poor link texts replaced by the title stored in the PDF.

### Removed
- The Romanian "SRR" source (`srr.ro` is Radio România, not the foreign intelligence service) and its documents.

## [0.2.0] – 2026-09-30

### Added
- Unit tests for the crawler heuristics.
- Rendering of JavaScript-built pages with headless Chromium, `curl` fallback on timeouts.
- `browser-only` status for sites that serve files only to real browsers.

### Fixed
- Links on sites using `<base href>` (German federal sites) were resolved incorrectly.
- Registry corrections (SAB, BMLV, SOA, BRS, ANSSI, BfV archive). Sites blocked by robots.txt or bot protection
  are set to manual.
- Administrative documents (contracts, recruitment, FOI reports) are now hidden by default.

## [0.1.0] – 2026-09-29

### Added
- Source registry of 84 official publishers (EU27, EU bodies, NATO) with language versions and archives.
- Crawler, polite downloader (robots.txt, per-host delay, PDF check, de-duplication) and FastAPI web portal.
- systemd user units for the portal and a weekly update timer.

[Unreleased]: https://github.com/iiogurt/Rozvedka/compare/v0.9.2...HEAD
[0.9.2]: https://github.com/iiogurt/Rozvedka/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/iiogurt/Rozvedka/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/iiogurt/Rozvedka/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/iiogurt/Rozvedka/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/iiogurt/Rozvedka/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/iiogurt/Rozvedka/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/iiogurt/Rozvedka/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/iiogurt/Rozvedka/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/iiogurt/Rozvedka/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/iiogurt/Rozvedka/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/iiogurt/Rozvedka/releases/tag/v0.1.0
