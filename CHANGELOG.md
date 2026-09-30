# Changelog

All notable changes to Rozvedka are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Before 1.0.0, a minor version can change the data model or the
registry format.

Each release is tagged `v<version>` on `main` (e.g. `v0.6.0`). The version shown in the portal footer comes from
`rozvedka/__init__.py`.

## [Unreleased]

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

[Unreleased]: https://github.com/iiogurt/Rozvedka/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/iiogurt/Rozvedka/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/iiogurt/Rozvedka/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/iiogurt/Rozvedka/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/iiogurt/Rozvedka/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/iiogurt/Rozvedka/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/iiogurt/Rozvedka/releases/tag/v0.1.0
