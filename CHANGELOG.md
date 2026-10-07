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

## [0.36.0] – 2026-10-07

### Added
- **Democracy ratings of the reporting states** (`/ratings`, *Sources → Democracy ratings*): regime type per year since
  1990 (V-Dem Regimes of the World) with the V-Dem Liberal Democracy Index, the Freedom House Freedom in the World
  score and the World Bank WGI Voice and Accountability indicator for all 49 library states – each value linked to its
  source with licence and retrieval date; sort by the largest ten-year decline; regime changes listed. Country headings
  on Sources show the strip; **report pages show the ratings of the report's year** and warn when the regime type has
  changed since. New command `fetch-ratings` (also run by `fetch-actors`). The EIU Democracy Index is commercial and not
  used; V-Dem's own download needs a registration form, so V-Dem and Freedom House data come via Our World in Data.
- Design for think-tank credibility profiles (`docs/PUBLISHER_PROFILES.md`): existing rankings researched – none current
  and credible – and an evidence checklist proposed instead of a score.

## [0.35.0] – 2026-10-07

### Added
- **Cross-language search**: a search word naming one of 107 security concepts (drone, ransomware, espionage,
  disinformation, flood, civil protection …, `sources/concepts.yaml`) also finds the concept's names in every library
  language – the labels and aliases of its Wikidata item, fetched by the new `fetch-concepts` command (also run by
  `fetch-actors`) with the item's revision and the retrieval date. Documents shows what was added and where it comes
  from, with *Search only the words as typed*. Example: *Drohne* – 25 reports as typed, 449 in all languages.
- The Wikidata / Wikipedia fetch also covers Albanian, Macedonian, Turkish, Icelandic, Irish and Maltese names.

### Fixed
- Search results sorted by relevance computed the relevance with one full-text query per row (seconds per page);
  now once per search.

## [0.34.0] – 2026-10-07

### Added
- **Independent publishers – think tanks** (owner's decision of 2026-10-07): 17 pro-democratic and security think
  tanks, kept apart from the official agencies – 13 crawled (Freedom House, ISD, ECFR, V-Dem, SIPRI, ICCT,
  Clingendael, HCSS, IFRI, ICDS, ASPI, Lowy Institute, IEP; 150 reports to start with) and 4 behind bot protection
  collected by hand (CEPA, CSIS, ISW, GLOBSEC). Researched and left out for now: RUSI, SWP, Chatham House, Carnegie
  (lists built by JavaScript), EU DisinfoLab (no PDFs), state-run institutes (OSW, PISM, NUPI).
- **Always told apart**: registry field `publisher: official | independent` and source type *Think tank*; a ◆ *think
  tank* badge next to the publisher in every list, a banner on their report pages, their own section on Sources, a
  diamond marker on the map; "Official agencies only" in every scope selector (Documents, Trends, Network, Map
  mentions, Compare); the home page counts official agencies and think tanks separately; the Documents summary and the
  Trends notes say how many think-tank reports a count includes.
- Crawler: `follow` – a pattern of publication pages to open from a list page (think-tank lists link to one page per
  publication); titles from the publication page's own heading, without "Read more", dates or the site name; language
  names count only in short link texts and at the end of file names ("…_Spanish_lowres.pdf"), not in titles about a
  country ("Russian information warfare").

### Changed
- Actor gazetteer refreshed from Wikidata, Wikipedia and MITRE ATT&CK after widening the sources (now a standing rule:
  every widening of scope refreshes it).

## [0.33.0] – 2026-10-07

### Added
- **Reports, not files**: language versions, summaries and file variants of one report are grouped and counted once –
  by series edition, by address without its language marker, or by title without a language / "summary" ending. One
  file represents the report (the one with most text, English unless another version has 30 % more); Documents lists
  each report once with its other files beside it ("also de fr …") and a "+ N other language versions and summaries"
  link; the report page lists every file of the report with the rule that grouped it. Filtering by language or series,
  or *all files*, lists every file. Corrections in `sources/works.yaml` (`separate`). The library now counts **2,917
  reports in 3,246 listed files**: 211 reports have several files, 329 files are no longer counted twice (Europol's
  TE-SAT and SOCTA summaries in 20 languages each were counted 20 times).

### Changed
- Every count, chart and dashboard counts reports, not files; the Trends notes say how many other language versions and
  summaries were counted once.
- English "situation reports" (e.g. Switzerland's Security) are threat assessments like their originals, not bulletins.

## [0.32.1] – 2026-10-06

### Changed
- **Fewer reports without a topic: 14.5 % → 4.8 %** of the counted reports with text (463 → 151). The keyword list
  gained the languages it lacked for the hazard, resilience, cyber and crime topics – Croatian, Slovenian, Russian,
  Greek, Hungarian, Portuguese, and Albanian, Macedonian, Turkish and Icelandic for the new sources – plus the Peruvian
  disaster vocabulary (huaicos, damnificados, simulacros, El Niño), "SOCTA" and malware-analysis terms. Two new topics:
  **Crime statistics** (police crime statistics such as the German PKS) and **Cyber security practice & standards**
  (ISMS, certification, encryption, monitoring, awareness, cyber exercises). 66 topics, 4,400 terms.
- Terms that turned into common words of another language once accents are folded were left out or written as exact
  words (Turkish *taşkın* → "tasking", Latvian *šiem* → "siem", Croatian *suše* → "SUSE"); tests guard these cases.
- New document type **Law / regulation** (gazette numbers such as "82/15", *Zakon*, *Uredba*, *Gesetz*, *Act on the*,
  *rozporządzenie* …): 84 files, mostly Croatian civil-protection legislation, not counted as reports. EU project
  funding sheets (POSEUR / POCI codes) are budget tables.

## [0.32.0] – 2026-10-06

### Added
- **Document types**: every file gets a type from rules on its title and file name (many languages), its report
  series and its page count – annual or periodic report, threat / risk assessment, strategy / white paper, bulletin /
  warning, guide / factsheet, other report, and three kinds that are not reports: statement / press release, budget /
  accounts table, form. The type and its rule show on Documents and on the report page, where it can be corrected
  (kept in `sources/doc_types.yaml`, merged on dataset import). New command `type-documents`, run after every update
  and import. Documents has a type filter with counts.

### Changed
- Counts, charts and dashboards leave out statements, budget tables and forms (133 files today, mostly UK ISC press
  notices and Slovak budget tables), as they leave out hidden files; the Documents list leaves them out by default and
  links them ("+ 133 … not counted"), and the Trends notes list them under *Left out*.

## [0.31.1] – 2026-10-06

### Added
- The tests run on GitHub Actions for every pull request and every push to `main`.

## [0.31.0] – 2026-10-06

### Added
- **Year conflicts** (`/years`): reports whose stored year is contradicted by strong evidence (a Japanese era year in
  the title, a date stamp in the file name that is neither the stored year nor the next, a report heading on the cover
  naming another year), with the evidence, filters by kind and agency, and *Use the year found* / *Keep* per report
  or for the ticked ones. 122 conflicts found in the library, e.g. UK ISC press releases stored as 2021 that are dated
  2009–2020 and Peruvian civil-defence yearbook chapters from 2002–2006 stored as 2019. Verdicts are written to
  `sources/year_reviews.yaml`, re-applied whenever reports are dated (so they hold after a dataset import) and merged
  on import. The Documents summary links the number of open conflicts; a report page shows its conflict.

## [0.30.0] – 2026-10-06

### Added
- **Report page** (`/report/<id>`): one page per report with where it comes from (official address, the page it was
  found on, how and when it was listed and downloaded, size, pages, SHA-256, OCR, how its year was found), its series
  edition with the previous / next edition and the other languages, what changed against the previous edition, its
  topics with the terms that matched, and the actors it names with a passage and page number each. Report titles on
  Documents, Home, What's new, Watchlist, Compare, Series and actor pages open it; a separate *PDF* link opens the file.

### Fixed
- Series pages no longer count an actor in editions dated before the actor was founded (the rule the actor pages
  already used), so "first time in this series" agrees with the actor pages.

## [0.29.1] – 2026-10-06

### Added
- **Sources for the NATO members outside the EU**: Iceland (National Security Council – security assessments and
  reports on the national security strategy), Albania (AKSK, national cyber-security authority – annual reports),
  North Macedonia (ANB – national threat assessment in Macedonian, Albanian and English), Türkiye (police
  counter-narcotics – the yearly Türkiye Drug Report since 2006; collected by hand, as robots.txt disallows its files).
  Montenegro, Albania's SHISH and Malta publish no regular reports (recorded in the registry).
- **National risk assessments** (civil protection): Netherlands (Rijksbrede Risicoanalyse Nationale Veiligheid),
  Belgium (Belgian National Risk Assessment 2023–2026), Portugal (ANEPC), Hungary (BM OKF), Croatia (civil protection
  directorate), Slovenia (URSZR – national and sector assessments); Ireland's national risk assessments 2017, 2020, 2023.
- **National CERTs' annual reports**: Austria (CERT.at), Latvia (CERT.LV), Sweden (NCSC), Croatia (CERT.hr); Ireland's
  national cyber risk assessments 2022 and 2025.
- Countries Iceland, Albania, Montenegro, North Macedonia and Türkiye with their NATO accession years (nato.int) and flags.

### Fixed
- Six sources that found nothing: VIGINUM (publications list), SRE Luxembourg (activity reports 2021–2024, rendered
  in a browser), NCSC Ireland and the Office of Emergency Planning (on gov.ie); NCSC-NL and NCSA Greece are now
  collected by hand, with the reason. The Cybersecuritybeeld Nederland 2023–2025 is found under NCTV.
- Crawler: archive pages with one page per yearly report are followed even when the page also links a few navigation
  PDFs (the link text must name a report and a year); a page that redirects to another domain of the agency keeps
  its documents; Icelandic, Turkish and Macedonian report words; document links of Episerver media libraries.
- Not taken as reports: a CERT's RFC 2350 self-description, eIDAS trust lists, forms, EUR-Lex links and vulnerability
  bulletins naming CVE numbers (hidden where already stored).

## [0.29.0] – 2026-10-06

### Added
- **Update page** (`/update`) and an **⟳ Update** button in the header of every page with the age of the data (every
  source checked since …, amber after a week) or the running job's progress. The page: what to do (full update,
  check only, download waiting reports with optional retry of failed ones), which sources (all, not checked for N days,
  one country, ticked ones) with the number of pages and the expected duration (measured on earlier runs); a progress
  panel with the steps, the source being checked, downloads done, time left, live log and the result with links to
  What's new; cancelling between pages or downloads; every source's last check, outcome per report page, reports,
  new ones and waiting ones, with filters and *Check now*; the history of checks and downloads.
- `ROZVEDKA_DB` chooses another database file.

### Changed
- The old crawl, download and *Update now* buttons (Sources, To collect, Documents) start the same jobs and open the
  Update page; their one-line status banner is gone.
- All long jobs from the portal – updates, dataset export and import, indexing after a hand upload – run through one
  runner (`rozvedka/jobs.py`): one at a time, with progress, log and cancel. Indexers run as separate processes, as
  they start worker processes of their own (the old *Update now* forked them from the portal's threads).
- Crawls and downloads record when they started, so the page can show how long they took.

### Fixed
- Background indexing jobs could reach the default library instead of the one in use (`ROZVEDKA_DATA`/`ROZVEDKA_DB`
  are now passed exactly); tests never start indexer processes.

## [0.28.1] – 2026-10-06

### Added
- Browser tab icon: a small radar scope like the home page's banner (SVG, with a 16/32 px `favicon.ico` and a 180 px
  icon for phones and Safari).

## [0.28.0] – 2026-10-05

### Added
- **Export and import in the portal** (*Sources → Data exchange*): export in three steps (what – everything,
  catalogue only, or catalogue + report files since a day, each with its size; where – a folder picker over USB disks
  and the home folder with free space and *new folder*; options – largest file and label) with a space check;
  import by picking the folder with a dataset (listed with date, origin, size, files present), **Check and compare**,
  then **Import** with the choice whose hand edits win. A progress panel shows the steps, a progress bar with size,
  speed and time left, the live log (also saved in `data/logs/`) and the result; **Cancel** removes a partial export
  and stops an import until it starts changing the library. One job at a time; not while a crawl or download runs.
- The folder picker only lists `/media`, `/mnt`, `/run/media`, the home folder and `ROZVEDKA_EXCHANGE_DIRS` – the
  portal has no login, so it never shows the rest of the file system (symbolic links cannot lead out).

### Changed
- After an import from the portal, topics, dates and actors are matched in separate processes (their worker
  processes must not be forked from the portal's threads).

## [0.27.0] – 2026-10-05

### Added
- **Datasets for backup and exchange** – `python -m rozvedka export DIR` writes the whole library (database copy,
  report files, logos, actor gazetteer, the portal's lists) as parts of at most 2 GB plus a manifest with the
  exporter, date, version, freshness per source and a SHA-256 per part; `--no-files` (catalogue only), `--since DATE`
  (only newer report files), `--part-size`, `--name`. `python -m rozvedka import PATH` verifies the parts, compares
  the dataset with the library (newer / older / mixed / complementing, per source, and what it would add or change; `--check` stops
  there), then restores an empty library or merges into an existing one by source key and report address – adding
  reports, files, text and OCR, filling years, keeping the later crawl dates, listing conflicting hand edits (local
  wins unless `--prefer dataset`), merging watchlist, reviews and series, and marking reports without a file for
  download. A copy of the database is kept in `data/backups/` before every import; the report in `data/imports/`.
- **Data exchange** page (`/data`, under Sources): this installation's identity and freshness, the commands, and
  the history of exports and imports.
- Each installation has an identity (`data/installation.json`); imported reports record the dataset they came from.

## [0.26.0] – 2026-10-05

### Added
- **Precision review of actor matches** (`/actors/review`, linked from Actors): random, stable sample passages of the
  names that put the most reports on their actor (after all matching rules), to mark ✓ right or ✗ wrong; every
  passage on an actor page has a *✗ not …* button too. Verdicts are kept with the passage as evidence in
  `sources/actor_reviews.yaml`; a wrong one removes that report from the actor at once and on every rebuild, and
  the actor page lists the reports left out this way. The page shows the measured precision overall and per name.

### Fixed
- One-word names whose symbol is part of the name are no longer matched as the bare word: "Heimat!" put the party
  Die Heimat on 45 reports through the ordinary German word *Heimat*; "III %" (Three Percenters) matched the
  numeral III, "LAPSUS$" the word Lapsus. A rule tested and rejected on the way: a capitalised word next to a
  one-word organisation name (1,848 of 14,113 mentions) is no sign of a person's name – in a sample nearly all were
  right (German nouns, lists of groups) – so such cases go to the review instead.

## [0.25.0] – 2026-10-05

### Added
- **Watchlist** (`/watch`, in the menu): searches followed update by update – one shared list in
  `sources/watchlist.yaml`, no per-user state. Any search-console query can be watched (`actor:"Wagner Group"`,
  `topic:ransomware country:DE`, `"critical infrastructure"`); add it on the page, with **☆ Watch this search** on the
  Documents list or **☆ Watch** on an actor page. The page shows a table of watched searches × updates, the updates in
  order with the searches each brought reports for, and per item its newest reports with their passage and page.
- Atom feed per watched search: `/feed.atom?watch=<query>`.

### Changed
- The Documents list's filters are built in one place (`rozvedka/doclist.py`), so the watchlist's counts are the
  Documents list's by construction.

## [0.24.0] – 2026-10-05

### Added
- **Compare agencies** (`/compare`, in the menu): what agencies say about one actor or one topic, side by side. One
  card per agency, ranked by its number of reports in the chosen years that name the actor or carry the topic (with
  all its reports in the period for scale); in each card its two reports that deal with it most, each with the
  densest passage – the 600 characters with the most mentions of the actor or terms of the topic, skipping reference
  lists and endnotes, and not counting an agency's own name in its own reports – and the PDF page it is on. Filters:
  years (default the last three), country, coalition, agency type. Links from actor pages and the Topics page.

## [0.23.0] – 2026-10-05

### Added
- **What's new** (`/new`, in the menu): update by update – an update is a day on which reports entered the library.
  For each: the new reports by agency with their main topics and the actors they name most; the actors **named for the
  first time** (in no report found earlier); and the **topics that jumped** (share of the update's reports against
  the reports found before). Every number opens its list.
- **Atom feed** (`/feed.atom`, also announced in every page's header for feed readers): the 50 newest reports with
  agency, year, language, main topics, named actors and the official URL. Entry ids do not depend on the address
  the portal is opened with.
- Documents list: `added_to=` filter (with `added_from=`, the reports of one update).

## [0.22.3] – 2026-10-05

### Changed
- More reports have a year: undated reports went from 168 to 90 (roadmap B5's target was under 100). New evidence,
  each stored with the report and shown when you hover the year:
  - Japanese era years in titles (平成29年版 → 2017; 21 disaster-management white papers);
  - a year in a file name passed in the address (`…?file=…Spring-2026.pdf`, `?filename=Political Guidelines 2024-2029.pdf`)
    and date stamps in file names (`20260611_SGDSN_….pdf`);
  - the year shared by at least three other dated reports in the same folder of the site (100 % exact in the blind
    check), unless the report's own first page names another year;
  - publication dates with month names in all the library's languages (Estonian, Latvian, Lithuanian, Hungarian,
    Finnish, Croatian, Romanian, Portuguese, Greek, Bulgarian, Irish, Maltese …), year-first dates
    ("2024. gada 18. jūlijā") and imprint lines ("Utgitt av DSB 2025", "Traficomin julkaisuja 11/2025");
  - the only year on a title page (82 % exact).
- `date-documents --check` reports accuracy per rule.

## [0.22.2] – 2026-10-05

### Fixed
- After an update, Chrome could keep showing pages with the old stylesheet (the new home page appeared unstyled).
  Stylesheets and scripts are now linked with a content stamp (`style.css?v=1a2b3c4d`), so a changed file always
  has a new address, and unstamped static files are revalidated on every visit (`Cache-Control: no-cache`).

## [0.22.1] – 2026-10-05

### Fixed
- Home page: the ASCII radar and word mark could fall apart in Chrome on Windows or macOS, where the system
  monospace font (Consolas, Menlo) lacks some of the glyphs and others are drawn at a different width. The banner,
  search console and readout now use a bundled 21 KB subset of DejaVu Sans Mono (`static/vendor/fonts`, Bitstream
  Vera licence), so they look the same in every browser.

## [0.22.0] – 2026-10-05

### Added
- Home page (`/`): an ASCII radar and word mark, a search console and dashboards. The search understands filters –
  `country:`, `coalition:`, `agency:`, `type:`, `topic:`, `actor:` (any name or alias), `year:` (one year or
  `2020..2025`) and `lang:` – next to words and `"phrases"`, and opens the Documents list with them set. Unknown or
  ambiguous filters are explained with the choices as links. Suggestions as you type (actors, topics, agencies,
  countries, with report counts); <kbd>Tab</kbd> completes a filter; recent searches stay in your browser.
- Dashboards on the home page: newest editions, reports added in the last 7 / 30 / 90 days, reports per
  publication year (with the undated ones), rising topics, the actors most named in last year's reports, the
  library by agency type and download state, editions to collect and the date of the last crawl. Every number
  links to the list it counts.
- Documents list: sort by date added; filters for reports without a year (`undated=1`) and for reports added since
  a day (`added_from=`).
- `tools/check_links.py`: before a release, compares every home-page count with its list and follows the internal
  links of the main pages.

### Changed
- The Documents list moved from `/` to `/documents` (menu: Documents; the Rozvedka name opens the home page).
  Old links and bookmarks such as `/?country=CZ` are redirected, so nothing breaks.

## [0.21.0] – 2026-10-02

### Added
- OCR for scanned reports (`rozvedka/ocr.py`, command `ocr`, part of `update` when installed): reports without a
  usable text layer (< 2,000 characters, or < 120 per page) are recognised with Tesseract 5.5 via OCRmyPDF in the
  report's language plus English (17 languages installed). Only the text is stored, with page breaks – the PDF is not
  changed – and it goes through topics, dates and actors. 135 of 187 candidates recognised (4.6 million characters,
  e.g. a full Bulgarian DANS annual report); 47 gained nothing (maps, image pages); 5 were XFA forms.
- Recognised text is marked: *OCR* in the documents list (engine, languages, date on hover) and *OCR text* on actor
  and pair passages.

### Changed
- `index-topics --reextract` keeps recognised text instead of bringing back the empty text layer.
- Questionnaires and forms (`questionnaire`, `formulier`) count as low relevance; five AIVD screening forms hidden.

## [0.20.0] – 2026-10-02

### Added
- Years for undated reports (`rozvedka/dating.py`, command `date-documents`, part of `update` and of the indexing
  after a hand upload): from a report heading on the first pages, else from a publication date, each with the
  evidence stored in `documents.year_source`. 282 of 463 undated reports dated (51 from a heading, 231 from a date).
- `date-documents --check`: blind accuracy check on reports with a known year (headings 82 % exact, 89 % within one
  year; publication dates 68 % / 83 %).
- Documents page: the year shows where it came from on hover; years from a publication date are marked ≈.
- Trends: the provenance section states how many years were found in the reports' text.

### Changed
- Editing a report's year marks it "set by hand"; such years are never changed by the dating.

## [0.19.0] – 2026-10-02

### Added
- *Series* in the menu: a catalogue of all confirmed report series (completeness, latest edition, compact grid of
  the last years; filter by country, search) and a page per series:
  - the editions in the library per year and language;
  - how the series changed over the years: topics × years (main topic / present) and actors × years (mentions,
    first edition naming the actor), each cell opening the edition; the publishing agency itself is left out;
  - edition by edition: files in every language with page counts, main topics, actors named most, topics that became
    or stopped being main topics, actors named for the first time in the series.
- Documents carry a badge of their series and edition year; the documents list filters by series (`series=`).
- The Coverage page explains that it is for maintaining series and links every series to its page.

## [0.18.0] – 2026-10-02

### Added
- *Sources → To collect* (`rozvedka/collect.py`), four tabs with the shared pager:
  - **Missing editions** of confirmed series and the next expected edition, with the source's documents of that year
    and language to pick as the edition ("this is the edition" – stored as a URL of the series), an upload form and
    "not published";
  - **Blocked downloads** (browser-only, failed): open the original, upload the PDF to the same report;
  - **Sources to check by hand** (bot-protected, blocked pages, no report found): report pages, "checked, nothing new"
    with date and note;
  - **Inbox**: PDFs copied to `data/inbox/` (a folder named after the source preselects it), imported with source,
    official URL, title, year and language.
- Reports added by hand keep the official URL, the date, how they came in (upload or inbox) and whether the URL is on
  the agency's official domains; the documents list marks them *added by hand* (and *unofficial URL* when it is not).
  They are indexed for search, topics and actors right after the upload.
- *Update now* button and the age of the data on the To collect page (no periodic job).

### Changed
- The downloader and the hand import share one step that checks, de-duplicates (SHA-256) and files a PDF.

## [0.17.0] – 2026-10-02

### Added
- Report series (`rozvedka/series.py`): recurring publications of a source, recognised by their title without the
  year, with languages joined when their editions cover the same years. *Sources → Coverage* shows every confirmed
  series as a years × languages grid – in the library, listed but not downloaded, missing, expected, confirmed as
  not published – and the proposed series to confirm, rename, merge into an existing series or reject.
- Source cards show their series as a compact grid of the last 12 years.
- `sources/series.yaml` stores confirmed series, editions marked as not published and rejected proposals; 23
  flagship series (national annual reports and threat assessments) are confirmed to start with.

### Changed
- Roadmap: no periodic update job (owner's decision); updates run on demand.

## [0.16.1] – 2026-10-02

### Added
- `docs/ROADMAP.md`: assessment of the project at 0.16.0 with measured gaps (stale library, 32 sources without
  reports, 74 blocked downloads, 465 undated and 257 text-less reports, no backup, no CI) and a prioritised
  roadmap – complete and current library, data quality, a reading workflow, sourced enrichment, engineering.
  Linked from `CLAUDE.md` and the README.

## [0.16.0] – 2026-10-01

### Added
- Connections of every actor – members, leaders, founders, key people, parent organisations, subsidiaries and
  wings, allies and opponents, employers and party memberships – from the infobox of its English Wikipedia
  article and from Wikidata statements in both directions, each with its source (article, infobox field and
  revision; or Wikidata statement and cited reference). Shown on the actor pages, grouped by relation, with the
  reports naming both in one passage.
- Connected people are added to the actor index and found by their full names.
- Passages list the actors named nearby and mark those with a known connection; pair pages show the documented
  connection; the Network marks known connections with ⛓.
- New kinds: political parties and companies, think tanks & media. New seeds include AfD, Die Heimat, Der III.
  Weg, FPÖ, Rassemblement National, Golden Dawn, Revival, Shor Party, United Russia, the CCP, the Workers' Party
  of Korea, Cambridge Analytica, SCL Group, Heritage Foundation, Concord, Social Design Agency, RT, Russkiy Mir,
  Rossotrudnichestvo, Confucius Institute, Huawei, ZTE, ByteDance, Kaspersky, NSO Group, Gazprom, Rosatom,
  Rosneft, Solntsevskaya Bratva, Tambov Gang, thieves in law and the Night Wolves.

### Changed
- Mixed-case three-letter abbreviations ("AfD") count as names on their own.
- A person's name inside the name of something else is not counted ("Alan Turing Institute", "USS Theodore
  Roosevelt", "… Airport", "… Prize").
- `fetch-actors` caches its slow stages (Wikipedia infoboxes, incoming Wikidata links, item kinds) in
  `data/gazetteer/`, so an interrupted run continues; `fetch-actors --refresh` reads them again.
- Redirects to the same Wikipedia article are resolved for every spelling.

## [0.15.0] – 2026-10-01

### Added
- One pager for every list (`rozvedka/paging.py`, `templates/_pager.html`): numbered pages with first/last and
  gaps (« ‹ 1 … 5 6 7 8 9 … 61 › »), a "go to page" box, the position ("301–350 of 3,017 documents") and the
  number per page (25, 50, 100, 200, 500). Filters and page size are kept in every link; out-of-range pages
  show the last page.
- Paging on the Documents page (above and below the table), the Actors list, the actor-names review, and the
  passages on actor and pair pages – which previously stopped at the 40 newest reports.

## [0.14.1] – 2026-10-01

### Added
- `CLAUDE.md`: the project's working rules in one place – scope and source requirements, traceability and
  visualisation principles, git/GitHub workflow, versioning and release steps, README and changelog conventions,
  and notes for operating the Raspberry Pi installation. Linked from the README.

## [0.14.0] – 2026-10-01

### Added
- Light and dark theme with a toggle in the header. Dark is the default; the choice is remembered in the browser
  (localStorage) and applied before the page is drawn. Charts (Trends, Network, actor pages, mind map) redraw in
  the matching palette. The map pages stay dark.

### Changed
- The theme no longer follows the operating system's light/dark setting.
- README screenshots in the dark theme.

## [0.13.0] – 2026-10-01

### Changed
- Network (`/network`) redesigned. Instead of a force graph of raw co-occurrence counts, it measures association –
  how much more often two actors are named in the same passage than their frequency predicts (normalised pointwise
  mutual information) – and shows:
  - clusters of strongly associated actors as cards: members, strongest ties, main topics of their reports,
    timeline, reporting agencies, links to every count;
  - an actors × actors association matrix ordered by cluster, with all names visible;
  - a details panel for an actor (strongest and most frequent partners) or a pair (counts vs. chance).
- Filters for kind of actor, cluster strictness and the minimum number of reports per tie.

### Added
- Documents page: `cluster=` (reports naming two of the listed actors in one passage).

## [0.12.0] – 2026-10-01

### Added
- Network (`/network`): actors linked when named in the same passage, sized by reports, coloured by kind,
  filtered by period, reporting coalition, agency type and topic; table view.
- Passages of two actors named together (`/actors/<a>/with/<b>`), linked from every network link and from the
  actor pages ("Named in the same passage", now with countries listed apart).
- Who reports on whom (`/map/mentions`, a tab of the map): the share of each country's reports naming a chosen
  country, or the countries named by one country or coalition; CSV export; thin selections (< 10 reports) greyed.
- Topic mind map (`/topics/map`): categories → topics → the actors most characteristic of each topic, with a
  details panel and links.
- Countries as actors (189, from Wikidata with demonyms), shown under Actors → Countries.
- Documents page: `main=1` (topic among each report's three main topics).

### Changed
- Name matching: "States", company words and ordinal numbers are generic; words in capitals match only from
  6 letters; hand exclusions for "America", "Korea", "Valencia". Drug cartels and private military companies are
  no longer dropped by the company filter (it applies only to "designated as terrorist").

## [0.11.1] – 2026-10-01

### Changed
- README rewritten in the usual GitHub layout: overview with badges and screenshots (`docs/images/`), the
  portal's features page by page, quick start, command and configuration reference, a pipeline diagram,
  development and release notes, and a table of data sources and licences.
- `tools/bump_version.py` also updates the version badge in the README.

## [0.11.0] – 2026-10-01

### Added
- Actor index (`/actors`): about 1,500 actors from Wikidata, MITRE ATT&CK and a hand-kept list
  (`sources/actors.yaml`), found by name in the report texts. New commands `fetch-actors` and `index-actors`;
  the weekly `update` re-indexes actors.
- Actor pages with sourced reference data (Wikidata revision, Wikipedia lead with revision and licence, ATT&CK
  description), mentions per year, reporting agencies, topics, actors named in the same passage, the passages with
  page links, and every name used for matching with the reason any name is not used.
- Matching rules against false matches, each shown with its reason on the actor pages: ignore lists and per-actor
  exclusions, generic names and short abbreviations only together with another name, longest match wins, surnames
  only for people, no counts from reports dated before an actor was founded. Review of the most frequent names at
  `/actors/names`. Checked on samples: 50 of 50 cited pages contain the passage.
- Documents page: `actor=` filter.
- Text extraction records where each PDF page starts, so passages cite page numbers (re-extracted automatically).

## [0.10.0] – 2026-10-01

### Added
- Trends pages (`/trends`): topics over time (share of reports or of agencies, per year), rising and falling
  topics, term trends for any words with `OR` translations, and a countries/agencies × topics matrix for a period.
- Every point, bar and cell links to exactly the documents it counts; table views, CSV export with a source link on
  every row, and a "Where these numbers come from" section on each view.
- Reference event markers from `sources/events.yaml`, dated from Wikidata by `tools/build_events.py`, each with its
  Wikipedia and Wikidata link and retrieval date.
- Documents page: `year_from`/`year_to` range, `indexed=1` (classified text only) and `OR` in searches.
- Apache ECharts 6.1.0, vendored.

## [0.9.3] – 2026-10-01

### Fixed
- Logos drawn in white for dark site headers (SRI, MUST, ABW, Frontex, ISC, NCSC-UK, DHS, DIA, CENAPRED) were
  invisible on the white logo tiles. The browser now samples each logo and gives white-on-transparent ones a dark
  tile on the Sources page, in the documents table and on the map.

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

[Unreleased]: https://github.com/iiogurt/Rozvedka/compare/v0.36.0...HEAD
[0.36.0]: https://github.com/iiogurt/Rozvedka/compare/v0.35.0...v0.36.0
[0.35.0]: https://github.com/iiogurt/Rozvedka/compare/v0.34.0...v0.35.0
[0.34.0]: https://github.com/iiogurt/Rozvedka/compare/v0.33.0...v0.34.0
[0.33.0]: https://github.com/iiogurt/Rozvedka/compare/v0.32.1...v0.33.0
[0.32.1]: https://github.com/iiogurt/Rozvedka/compare/v0.32.0...v0.32.1
[0.32.0]: https://github.com/iiogurt/Rozvedka/compare/v0.31.1...v0.32.0
[0.31.1]: https://github.com/iiogurt/Rozvedka/compare/v0.31.0...v0.31.1
[0.31.0]: https://github.com/iiogurt/Rozvedka/compare/v0.30.0...v0.31.0
[0.30.0]: https://github.com/iiogurt/Rozvedka/compare/v0.29.1...v0.30.0
[0.29.1]: https://github.com/iiogurt/Rozvedka/compare/v0.29.0...v0.29.1
[0.29.0]: https://github.com/iiogurt/Rozvedka/compare/v0.28.1...v0.29.0
[0.28.1]: https://github.com/iiogurt/Rozvedka/compare/v0.28.0...v0.28.1
[0.28.0]: https://github.com/iiogurt/Rozvedka/compare/v0.27.0...v0.28.0
[0.27.0]: https://github.com/iiogurt/Rozvedka/compare/v0.26.0...v0.27.0
[0.26.0]: https://github.com/iiogurt/Rozvedka/compare/v0.25.0...v0.26.0
[0.25.0]: https://github.com/iiogurt/Rozvedka/compare/v0.24.0...v0.25.0
[0.24.0]: https://github.com/iiogurt/Rozvedka/compare/v0.23.0...v0.24.0
[0.23.0]: https://github.com/iiogurt/Rozvedka/compare/v0.22.3...v0.23.0
[0.22.3]: https://github.com/iiogurt/Rozvedka/compare/v0.22.2...v0.22.3
[0.22.2]: https://github.com/iiogurt/Rozvedka/compare/v0.22.1...v0.22.2
[0.22.1]: https://github.com/iiogurt/Rozvedka/compare/v0.22.0...v0.22.1
[0.22.0]: https://github.com/iiogurt/Rozvedka/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/iiogurt/Rozvedka/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/iiogurt/Rozvedka/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/iiogurt/Rozvedka/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/iiogurt/Rozvedka/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/iiogurt/Rozvedka/compare/v0.16.1...v0.17.0
[0.16.1]: https://github.com/iiogurt/Rozvedka/compare/v0.16.0...v0.16.1
[0.16.0]: https://github.com/iiogurt/Rozvedka/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/iiogurt/Rozvedka/compare/v0.14.1...v0.15.0
[0.14.1]: https://github.com/iiogurt/Rozvedka/compare/v0.14.0...v0.14.1
[0.14.0]: https://github.com/iiogurt/Rozvedka/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/iiogurt/Rozvedka/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/iiogurt/Rozvedka/compare/v0.11.1...v0.12.0
[0.11.1]: https://github.com/iiogurt/Rozvedka/compare/v0.11.0...v0.11.1
[0.11.0]: https://github.com/iiogurt/Rozvedka/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/iiogurt/Rozvedka/compare/v0.9.3...v0.10.0
[0.9.3]: https://github.com/iiogurt/Rozvedka/compare/v0.9.2...v0.9.3
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
