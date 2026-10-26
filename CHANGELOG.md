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

## [0.93.1] – 2026-10-26

### Fixed
- **An unreadable robots.txt is no longer taken as permission.** When a site's robots.txt timed out or answered with a
  server error, the fetcher treated it as empty and fetched anyway – a retry of two Natural Resources Canada reports
  went to a server whose robots.txt forbids it. Now only an answer of 200 (its rules) or 4xx (no rules) lets anything be
  fetched; robots.txt also gets the curl fallback the pages have, so sites that refuse Python's TLS keep working. The
  error says which of the two refused ("blocked by robots.txt" / "robots.txt could not be read (…) – not fetched").
- **Titles made of labels** ("true true", "Español", "EN FR ES AR" – the link text of a language switcher) are replaced
  by the file name when the PDF has no title of its own: 32 UNODC and INTERPOL files now say what they are.
- **Failed downloads re-checked** (61 → 54, 50 of them Türkiye's, blocked by robots.txt and waiting on *To collect*):
  the four IRSEM failures were stale links to briefs already in the library from IRSEM's new file store, NEMA's 2015
  capability assessment is in the library under its new address – those five, and three files that are not reports
  (IPCC Panel decisions and press slides, a UNGRD procurement study), are hidden.

### Added
- UNODC: the World Drug Report 2021 page moved (`wdr2021.html`); the 2017 and 2026 editions added – 31 reports.
- NEMA: 9 new reports found on a re-crawl; IRSEM: one new study.
- Türkiye (`sources/coverage_gaps.yaml`): AFAD keeps its documents under a path its robots.txt disallows; USOM
  publishes no reports; the national cyber security strategies are on a ministry server that refused connections from
  the EU and the US – noted for a retry.

## [0.93.0] – 2026-10-26

### Added
- **Languages checked against the text.** The crawler only knows the languages a source is listed with, so the 24
  language versions of a Europol summary were all tagged English, and the English editions of NÚKIB, RIA, ANSSI or SRI
  carried the agency's own language. A new pass (`rozvedka/languages.py`, run with `type-documents`, `date-documents` and
  every update) reads the text's script and its most frequent short words – no model – and corrects the stored language
  where
  - the address names another language (`…-bg.pdf`, `?filename=…_SL.pdf`) and the text reads as it, or
  - the text alone reads clearly as another language and hardly as the stored one (a bilingual report is left alone).

  An address code alone is never enough: `_uk` is often the United Kingdom, `_ar` an annual report. 446 files corrected;
  40 sampled text-only corrections all right. The report page shows why a language was corrected (new field
  `documents.lang_why`); a language edited by hand is never changed.
- **Undated language versions take their report's year** – files of one publisher in one folder with the same title
  once a language or "summary" word is removed, each in another language, all dated versions agreeing (blind check on
  dated reports: 40 of 40 exact).

### Fixed
- **Language versions grouped into their report.** With the right languages, 58 more files are counted as versions of
  a report rather than reports of their own (3,924 → 3,866 reports); undated reports 148 → 142.
- The title rule that groups versions cut letters off the last word ("opportunism" → "opportu"), which merged two
  different ECDC reports; "Digest", "Síntese", "Zhrnutie", "Συνοπτική" and "Inglés" are now known summary and language
  words.
- `sources/series.yaml`: the English titles of the RIA, ANSSI and SRI series and the Finnish ones of Supo are listed
  under their real language, so those editions stay in their series.

## [0.92.1] – 2026-10-26

### Changed
- **Roadmap re-measured at 0.92.0** (`docs/ROADMAP.md`): what is built, the gaps as they stand today and the next steps.
  Found on the way: none of the 47 hand-collected sources holds a report yet, and Türkiye's only source is blocked by
  robots.txt, so it has no report – roadmap A2 is reopened.

## [0.92.0] – 2026-10-23

### Added
- **Sparklines in the overview's key numbers.** The Reports, Think tanks ◆ and Commercial ■ tiles show their reports by
  publication year over the last 15 years, in the colour of their kind (the current year paler, as it is not over). Each bar
  opens that year's list – the same counts as the publication-year chart below, which `tools/check_links.py` already checks.
  This completes roadmap F5: the daily columns, the years split by publisher kind and the dumbbell of rising topics were
  built earlier.

## [0.91.0] – 2026-10-23

### Added
- **The ATT&CK matrix as the reports name it** (top of `/techniques`). A block per ATT&CK tactic in MITRE's order – the
  Enterprise kill chain, then what only ICS or Mobile has:
  - the reports naming any technique of the tactic (each counted once), opening them;
  - its techniques ranked by reports, with a bar against the most named one, each opening its reports;
  - how many of the tactic's techniques the reports name at all ("8 of 46 named"), with the rest behind "more".

  Now 16 tactics over 57 reports. New Documents filter `technique=tactic:<name>`.
- **How old the named vulnerabilities are** (top of `/cves`). For every report × CVE pair, the years between the year in the
  CVE number and the report's year (74% name a CVE of the same or the previous year), and for CVEs on CISA's Known Exploited
  list whether the report named it before, in or after the year CISA added it. Year precision only, as the page says; each
  bar opens the reports behind it (new filters `cve=age:N` and `cve=kev:before|same|after`).
- `tools/check_links.py` checks every number of both views against its list.

## [0.90.0] – 2026-10-22

### Added
- **Who cites whom, agency by agency** (`/citations#matrix`). A matrix sets the 30 most citing agencies against the 30 most
  cited:
  - each cell counts the reports of the row agency that link to the column agency – its site or one of its reports in the
    library – and opens exactly those reports;
  - the shade is the cell's share of the row's citing reports, so it shows what each agency relies on, not who publishes most;
  - row and column totals open their lists too; think tanks ◆ and commercial analysts ■ are marked; links to an agency's own
    site are left out, and the page says what falls outside the top 30 (now 210 of 493 pairs, 361 of 490 citing reports shown).

  *By country* folds the same links into country × country (486 of 490 reports shown); its diagonal counts agencies of one
  state citing each other. Two new Documents filters behind the cells: `cite=agency:ID` and `cite=ccountry:XX`, named in
  the filter chip. `tools/check_links.py` now checks every number of the chord table and both matrices against its list.

## [0.89.5] – 2026-10-22

### Changed
- **Dependencies updated** (Dependabot's first monthly update): FastAPI 0.148.0 (was 0.141.1, now on Starlette 1.7),
  Markdown 3.11.1 (was 3.9), pytest 9.1.1 (was 9.0.3, development only).
- **Python 3.11 or newer is needed** (was 3.10): Python 3.10 reached its end of life in October 2026, and Markdown 3.11 no
  longer installs on it. CI no longer measures 3.10; the Raspberry Pi target stays Python 3.13.
- The portal's start-up (database, collection queue, registry sync) runs in a FastAPI lifespan handler instead of the
  deprecated `on_event("startup")`, so it keeps working with later FastAPI versions.

## [0.89.4] – 2026-10-22

### Fixed
- **Eight countries were missing from the actors:** Argentina, Cambodia, Czechia, Greece, Moldova, North Korea, Peru and
  Slovenia. Wikidata cuts a reply larger than 12 MB short and only adds a warning; country records are large, so two batches
  of 50 came back incomplete and the missing countries went unnoticed. The gazetteer now asks again for whatever a reply left
  out, in smaller batches, so no Wikidata item is lost this way (all `fetch-…` commands that read Wikidata entities). After
  `fetch-actors --refresh` and `index-actors`, all 196 sovereign states are actors again – "who reports about Czechia" on its
  briefing page, the country matrices and the network now include them.

## [0.89.3] – 2026-10-22

### Security
- **pypdf 6.21.1** (was 6.19.0): fixes four advisories about PDFs that could make the indexer loop forever or use very
  large amounts of memory (crafted cross-reference tables, outline and tree items, streams with many filters), and one about
  unvalidated JPEG data. Rozvedka reads PDFs downloaded from agency sites, so a malformed report could have stalled indexing.
- **pytest 9.0.3** (was 8.4.2, development only): fixes its handling of temporary directories.

## [0.89.2] – 2026-10-22

### Changed
- **Dependency watch:** Dependabot now proposes security fixes for the pinned Python packages and the CI actions as soon as
  an advisory is published, and one grouped version update per month (`.github/dependabot.yml`). Every update still goes
  through a pull request and CI; nothing merges by itself.
- CI runs on `actions/checkout` and `actions/setup-python` v7 (were v4 and v5).

## [0.89.1] – 2026-10-22

### Added
- **An open-source licence:** Rozvedka's code is now under the MIT licence (`LICENSE`). Vendored libraries, fonts and
  icons keep their own licences, listed in the README; downloaded reports, logos and gazetteer data are not covered.
- **Guides for contributors:** `CONTRIBUTING.md` (what is in scope, how to propose an agency, think tank or commercial
  analyst, the crawling rules, tests and pull requests), the Contributor Covenant 2.1 as `CODE_OF_CONDUCT.md`, and
  `SECURITY.md` (only the latest release is supported; vulnerabilities go through GitHub's private reporting; an
  unauthenticated portal on an untrusted network is documented behaviour, not a vulnerability).
- **Issue and pull-request forms:** a bug report, a source suggestion (every language version and archive page, funding
  or ownership for think tanks), a link for private security reports, and a pull-request checklist.
- The README links these files from its header, Development, Security and licence sections, with a licence badge.

## [0.89.0] – 2026-10-22

### Added
- **Coverage grid** (`/sources/grid`, Maintain → Coverage grid). Every state in scope is set against the five national agency
  types, and each cell shows one of four things:
  - the reports the library has, with the newest year and the hand-collected sites;
  - **0** for a listed source with no report yet (mostly bot-protected sites waiting on *To collect*);
  - **∅** for a slot researched without finding regular public reports, with the date and what was found;
  - nothing, for a slot still open – the open slots are listed below the grid as a to-do.

  Think tanks and analysts get columns of their own. The checked gaps that were scattered over comments in the registry are
  now in `sources/coverage_gaps.yaml` (20 slots). Every count is checked against its list by `tools/check_links.py` (142 cells).

## [0.88.0] – 2026-10-22

### Added
- **Briefing pages – one topic or one country on one page.**
  - **A topic** (`/topics/{key}`, the topic names on Topics now open it) shows its reports year by year (official agencies
    apart from think tanks and commercial analysts), the countries writing most about it (with the share of each state's own
    reports), the agencies, the actors and related topics its reports emphasise (lift × reports, not raw frequency), and its
    newest reports with the words that tagged them.
  - **A country** (`/countries/{code}`, Sources → Countries) shows its agencies, its reports by year, the topics and actors
    its official reports emphasise compared with all official reports (its own agencies left out), which other states'
    reports name it, its regime type, ratings, events and threat levels.
  - Every number opens its Documents list, and the link checker now compares two sample briefings with their lists.

## [0.87.0] – 2026-10-21

### Added
- **Offshore leaks** (`fetch-icij`, `/graph/offshore`, a network layer marked as leaked records). ICIJ's Offshore Leaks Database
  holds the Panama, Paradise and Pandora Papers. It is kept only for the sanctions lists, and its records are **journalistic,
  not official**: shown with an orange, dashed mark everywhere and never counted as official.
  - **Companies:** 57 listed companies are matched by the same distinctive name in the same country.
  - **People:** 35 listed people match by a rarer name and the same country. They become links only after you confirm each
    one on the new page, which shows what the leak record is linked to; verdicts go in `sources/icij_reviews.yaml` and
    travel with datasets.
  - **Links:** their officers, shareholders, owned companies and intermediaries, one step out (650 links).

## [0.86.0] – 2026-10-21

### Added
- **Company ownership from GLEIF** (`fetch-gleif`, a network layer). The register of legal entity identifiers (CC0) is
  downloaded and kept only for the companies on the sanctions lists. A list company is matched to GLEIF by the LEI its entry
  states, by its register or tax number in the same country, or by a distinctive name that only one record in its country
  carries: 565 of 16,318 list companies, with 39 of 40 number matches and 40 of 40 name matches right in hand-read samples. Their
  direct and ultimate parents, branches and consolidated entities are linked one step out (255 links, e.g. LUKOIL's 24
  subsidiaries abroad), each with its GLEIF relationship record. Entity pages show the LEI record and why it is the same company,
  and the Markdown export of the case file cites it.
- OFAC's "Legal Entity Number" is now read with the entries' other identifiers.

## [0.85.0] – 2026-10-21

### Added
- **Case file** (`/case`, Actors & threats → Case file). One shared board where you pin up to 12 entities with notes, using
  **📌 Pin** on actor, entity, Rings and Find a connection pages. It shows a grid of how many steps separate every pair (each
  number opens the chains), the chain of each pair step by step, and the **connectors** that sit on the chains of several
  pairs. *Export as Markdown* writes it all with a citation for every step. The file is kept in `data/case_file.yaml`, never
  committed, and only personal backups carry it (merged on import).

### Changed
- **Find a connection uses links that connect by default.** Rivalries ("opposed to") and Wikipedia sentences without a relation
  word are left out of chains, as on Rings, Leads and Brokers. Before, "Hezbollah – Islamic State" was a one-step chain through
  their conflict. A choice next to the layers brings them back.

## [0.84.0] – 2026-10-21

### Added
- **Neighbourhood matrix** (`/graph/rings/matrix`, the *Matrix* switch on Rings). An entity's neighbours are shown as rows and
  columns, with a mark where a source states a link between two of them. The rows are ordered by communities (Louvain
  modularity), so groups such as Hezbollah's Quds Force / IRGC block, the Gaza war or a Latin American crime cluster stand out
  as blocks. Every mark opens its evidence, and the communities, every link and the neighbours linked to none of the others
  are listed below it.

### Changed
- **Rings use "links that connect" by default.** Rivalries and Wikipedia sentences without a relation word are left out, as on
  Leads and Brokers. The other choices bring them back.

## [0.83.0] – 2026-10-21

### Added
- **Rings around one entity** (`/graph/rings`, Actors & threats → Rings). An actor, a company or a person sits in the middle,
  with its stated links on the inner ring and the entities two steps away on the outer ring. There is one sector per source,
  official lists first, and every name is readable. Large neighbourhoods are cut to 40 + 48 names, chosen by how many sources
  state a link and how specific an entity is, and every sector says how many links it has and how many are not drawn. The
  tables below list every neighbour and everything two steps away, each with its evidence or chain. You can choose the sources
  (stated, official only, reference only, with co-mentions) and whether countries count. Actor and entity pages link to it.

## [0.82.1] – 2026-10-21

### Changed
- **A way back on every detail page.** A report, an actor, a series edition, a book's statements, a state's ratings and the other
  pages below a list show a breadcrumb under the menu (e.g. *Documents › BIS › series “Annual Report”*), in place of the separate
  "← back" links each page had.
- **Shorter page tops.** Sixteen pages (Sanctions, Ratings, Think tanks, Data exchange, Update, Year conflicts, Series, book
  relations and statements …) open with one line on what they show; the long explanation of how it is counted is folded under
  *▸ How this is counted* and opens with a click. Cautions such as "a match is a name match, not an identification" stay visible.

### Fixed
- **Maps in the light theme.** The headquarters, ratings and mentions maps used colours made for the dark theme: agency pins
  were brighter than their legend, no-data countries (Greenland) were almost black, the library's states had a near-white outline,
  hover cards stayed dark and the "fewer – more reports" scale lost its colour bar. All map colours now come from the stylesheet,
  one set per theme, and the maps redraw when the theme is switched.

## [0.82.0] – 2026-10-21

### Added
- **Personal backup** on *Data exchange* (and `export --personal`): a checkbox to include the data kept for personal
  use only. That is the book library (files, text, what the books say) and RSF's press-freedom scores; the page lists
  what this library holds of it. The file names of such a dataset end in `-personal`, the import list marks it, and
  the import report names what it holds. A personal backup merged into another library brings the books along with
  their records and what they say.
- Datasets now carry the **country ratings**. A dataset to share has them without RSF; on import, each measure is
  taken when the dataset's copy is more recent.

### Fixed
- The size estimate for an export no longer counts the book files, which a dataset to share does not carry.

## [0.81.0] – 2026-10-20

### Added
- **Press freedom and cybersecurity commitment** on `/ratings`, the state pages and the ratings map (roadmap H3d):
  - a new *Media* group with RSF's **World Press Freedom Index** (0–100, higher = freer) for the editions since 2022.
    RSF changed its method in 2022, so earlier scores are not comparable and are left out. The scores stay in this
    library: RSF's terms ask for permission to reproduce them;
  - in the *Cyber* group, the **ITU Global Cybersecurity Index 2024** tier of each state (T1 role-modelling …
    T5 building). The tiers are read from the annex of ITU's report PDF (CC BY-NC-SA 3.0 IGO): all 194 states
    are matched to their country codes, and the counts per tier agree with the report (46 in Tier 1, 29 in Tier 2).
    Taiwan has no tier, because ITU covers only UN members.
- Not used: the National Cyber Security Index, because its terms prohibit reproduction.

### Fixed
- A rating download that the server answers with an error (such as a missing file) is no longer retried as if the
  connection had dropped.
- The ratings map opens at the latest year of the chosen measure, and jumps there when you switch to a measure without
  values in the year shown. With RSF's 2026 edition, the map would otherwise have opened on an empty year.

## [0.80.0] – 2026-10-20

### Added
- **Disaster risk of the states** (roadmap H3c) – a new group on *Sources → Ratings*, each state's page and the
  ratings map:
  - the **INFORM Risk Index** of the EU's Joint Research Centre (0–10, higher = more risk) from its public API: one
    release, INFORM Risk 2026, with every year since 2015 recomputed by the same method, so the years compare;
  - the **WorldRiskIndex** (Bündnis Entwicklung Hilft / IFHV, CC BY, from the Humanitarian Data Exchange) since 2000.
  - Not used: ND-GAIN – its download is behind bot protection, which the library does not get around.

### Fixed
- The ratings download tries a dropped connection again (10 s, then 20 s) instead of failing the whole fetch.

## [0.79.0] – 2026-10-20

### Added
- **Conflict deaths and cyber incidents as ratings of the states** (roadmap H3b), computed from the event data that
  `fetch-events` already stores:
  - *Security:* UCDP deaths in organised violence per year and 100,000 inhabitants (population from the World Bank).
    Preliminary candidate months are left out, and a state with no recorded death has 0.
  - A new group *Cyber:* the EuRepoC cyber incidents with the state among their receivers, per year – context, not a
    grade, since it counts what was reported. Each count opens the incidents of that state and year on `/events`.
  - Both are on `/ratings`, each state's page and the ratings map. `fetch-ratings` computes them, and `fetch-events`
    refreshes them.

## [0.78.0] – 2026-10-20

### Added
- **What the books say, on the timeline** (roadmap H2d): a book's dated statements that name a lane's actor or state
  – dated to a day or a month – appear in that lane as "a book says" (in italics, grey). Clicking one shows the
  sentence, the book, its year and the printed page, with a link into the book; it is the book's statement as of its
  publication, not an event of the sources. A statement dated only to a year is not drawn (it would cover the year).

## [0.77.0] – 2026-10-20

### Added
- **What a book says** (roadmap H2c), read from its text and never written anew – on the book's page and two pages of
  their own:
  - **Distinctive terms** per chapter (or block of 25 pages): the words it uses far more than the library's other
    documents (tf–idf against the full-text index).
  - **Key sentences** per chapter: the three most central (TextRank on the words sentences share), quoted with their
    printed page and the distinctive terms they hold ("why").
  - **Dated statements** (`/books/<id>/statements`): every sentence that names an actor and a day, month or year,
    dated by the date it names first, filterable by actor. Source citations, tables, figure captions and contents
    pages are left out, and endnote numbers glued to a full stop no longer join two sentences. Measured on a 793-page
    report: 30 of 30 random statements are statements of the text with an actor and its date.
  - **Stated relations** (`/books/<id>/relations`), optional with spaCy (`requirements-books.txt`): two actors joined
    by a verb from a published list – the verb's own subject and its direct object (or the "by …" of a passive, the
    object of "against"). Demonyms and possessors do not stand for a country. A negated verb ("cannot attack") is
    kept and marked, and every relation shows its sentence. They are rare and strict by design: on the three test texts
    2 relations, both correct ("Russia invaded Ukraine").
  - `index-books` builds it all; `import-books` runs it too.

## [0.76.0] – 2026-10-20

### Added
- **The structure of a book** (roadmap H2b), on its page in the library:
  - **Chapters**, from the PDF's bookmarks, the EPUB's table of contents (EPUB 3 or 2), or else a printed table of
    contents ("Title …… 123"), each with the actors named most in it.
  - **Printed page numbers:** a PDF's page labels ("i", "ii", "1" …), so every passage of a book is cited by the page
    as printed ("p. 123"); an EPUB is cited by section.
  - **The book's own index**, read from its back: headwords with their pages – with or without a comma, page lists
    wrapped onto their own line, stopping where the book goes on – each linked to an actor when exactly one actor has
    that name (also turned round: "Putin, Vladimir").
  - `python -m rozvedka index-books` rebuilds it; `import-books` runs it too.

## [0.75.1] – 2026-10-20

### Fixed
- **Topics: false friends from other languages no longer count in English text.** Every language's keywords apply to
  every report, because reports mix languages. A few single words of one language read as different English words,
  and they gave English reports topics they do not have:
  - Latvian `ķīn*` ("China") matched "kingdom", "kind" and "king" (in 2,394 reports);
  - Czech `munic*` ("ammunition") matched "municipal" and "Munich";
  - Czech `búrk*` ("storm") matched "Burkina Faso";
  - Spanish `temporal*` ("storm") matched "temporal", French `crue*` ("flood") "cruel", German `personal` ("staff")
    "personal", Czech `čín*` ("China") "cinema".

  Now such a word counts only in a text that is not English. A text counts as English by its English function words,
  not by its language tag, which is sometimes wrong (Europol's Greek and Latvian TE-SAT summaries are tagged "en").
  Cognates that share their stem with the topic's English terms (`militar*` ~ military, `russ*` ~ Russia) and
  acronyms written in capitals (CTIVD, ＡＩ) still count everywhere.
  - Effect: 1,251 of 33,152 topic assignments (3.8 %) are removed, none added.
  - A random sample of 40 removals: about 27 were wrong (the floods topic in the Global Terrorism Index via
    "Burkina"), about 8 borderline, and the rest were mostly caused by acronyms, now exempt.
  - Every report is re-classified by the next `index-topics` (also part of `update`).

## [0.75.0] – 2026-10-20

### Added
- **The local book library** (roadmap H2a) – *Library → Books*, `/books`, and `python -m rozvedka import-books`.
  - Put PDFs and EPUBs into `data/books/` (never committed). Each is copied into the library and read whole: an EPUB
    section by section, a PDF page by page. Each book gets full-text search, topics and actors with their passages and
    pages, like a report.
  - **Metadata with its origin:** `data/books/books.yaml` written by hand first, then Open Library by ISBN (CC0, also
    linking authors to Wikidata), then the file's own EPUB or PDF metadata. The ISBN comes from the EPUB metadata or the
    copyright page, with its check digit verified. The book's page says where every field came from.
  - **Never counted as a report:** a book is of the new document type "Book" (choose it on Documents to search books),
    and its publishing house is a source of the kind "book", marked ▲ wherever it appears. No report count includes
    books – the home page's numbers are the same with and without them.
  - **Stays on this machine:** the dataset export leaves book files and text out. Encrypted (DRM) files are reported
    as unreadable.

## [0.74.0] – 2026-10-20

### Added
- **Reports that name an event** (roadmap H1d). Each Wikidata event's label and aliases in the library's languages are
  searched for in the reports' text, in the event's year or later.
  - Transparent rules decide which names are used: at least two words; a word of three letters or more (not a code
    such as "11-M"); not only a date ("October 7"); not a one-word code name ("Operation Domino"); something specific
    after the first word – a capitalised word, an acronym or a year ("Lucha contra el terrorismo" is a phrase, not a
    name); not an actor's name; not shared by two events; plus a short list excluded by hand with reasons
    (`ignore_names` in `sources/events.yaml`).
  - An occurrence next to an earlier year in the same sentence ("Russia's invasion of Ukraine in 2014") does not count.
  - Precision on 60 random matches: 58 correct (96.7 %), after two earlier samples led to the rules above.
  - 98 events are named in 1,403 reports. Every count opens `/documents?event=…`, the new filter of the Documents list.
    Each event lists its names and why one is not used. Rebuild with `python -m rozvedka index-events` (also part of
    `fetch-events`).
- **Events in the rest of the portal:**
  - the event list and the timeline panel show the reports naming an event;
  - the panel adds context links: reports naming its actors in its year and the next, which need not mention the event;
  - actor pages get an *Events* section, with the actor's heaviest events and links to all of them and to its
    timeline lane;
  - a new network layer *Events* ties each event to its participants, perpetrators, initiators and sides, and to the
    events it is stated to cause, follow or be part of, so "how are X and Y connected?" can pass through an event;
  - a link to `/timeline?sel=<event>` without lanes opens the event's own states and actors.

## [0.73.0] – 2026-10-19

### Added
- **Chains of events on the timeline** (roadmap H1c). Clicking an event draws the relations a source states, up to three
  steps back to its causes and forward to its effects, as arrows between the events on screen (also across lanes):
  Wikidata's *has cause / has effect*, *immediate cause* and *follows / followed by*. Everything else is dimmed, *part of*
  highlights the whole and its parts, and the panel lists the chain step by step. `Esc` or a click on empty space clears
  it. An event without a stated relation has no chain – nothing is inferred.
- **Relations written by hand** – `relations` in `sources/events.yaml` (from, rel, to, evidence URL): for chains no
  source states (e.g. "response to"), each drawn with its evidence. Uses timeline-arrows 4.8.0 (Apache-2.0 or MIT),
  vendored.

### Changed
- An event known only to its year is drawn as a dashed bar over the whole year, not as a point on 1 January (where it
  could stand before its own cause).

## [0.72.0] – 2026-10-19

### Added
- **Timeline** (roadmap H1b) – *Actors & threats → Timeline*, `/timeline`: states and actors as lanes on one time axis.
  - Each lane holds its events (Wikidata, EuRepoC cyber incidents, UCDP organised violence) and the library's dated
    records (sanctions listings, designations, official attributions, threat-level changes).
  - A state's lane is shaded by UCDP's deaths in organised violence per month, and a thin row under each lane counts the
    library's reports per year naming the subject (each year opens that list).
  - At every zoom a lane draws only its heaviest events that fit (compared within their own source) and says how many it
    hides; clicking an event shows its date, deaths, participants, sources and the relations its Wikidata item states.
  - Add a state or an actor as a lane, remove one with ×; the whole view – lanes, period, selected event, wall mode – is
    kept in the address.
  - Full screen (`F`) and a wall mode (`W`) with larger type for big screens; drawn sharp at 4K. Keys: `0` fit, `+` / `−`
    zoom, `←` / `→` move.
  - Uses [vis-timeline](https://visjs.github.io/vis-timeline/) 8.5.4 (Apache-2.0 or MIT), vendored like the other libraries.

## [0.71.0] – 2026-10-19

### Added
- **Events** (roadmap H1a, the data behind the coming timeline) – *Actors & threats → Events*, `/events`: dated events
  from three sources, each linked to its source and kept apart.
  - **Wikidata**: events of 14 classes (terrorist attacks, cyberattacks, data breaches, sabotage, assassinations,
    hostage takings, bombings, massacres, riots, coups, invasions, armed conflicts, natural disasters, pandemics) since
    2000 that took place in a state of the library or name an actor of the gazetteer. They come with country, place,
    deaths, participants and perpetrators, and the relations the items state: cause and effect, what followed, what
    was part of what. The classes are listed in `sources/events.yaml`.
  - **EuRepoC** cyber incidents (CC BY-NC 4.0), with receiving states, initiators matched to the gazetteer, and who
    attributed them.
  - **UCDP** organised violence (CC BY 4.0): deaths per country and month, and single events with at least 50 deaths
    in a state of the library; the monthly candidate events of the current year are marked as preliminary.
  - An actor is linked only when its Wikidata item or one of its names matches unambiguously, otherwise it is shown as
    written with the reason. Filters by source, kind, state, year, name and actor, with the shared pager. Refresh:
    `python -m rozvedka fetch-events`.

## [0.70.0] – 2026-10-19

### Added
- **Security and governance ratings of the states** (roadmap H3a), beside the democracy ratings on *Sources → Ratings*:
  political stability and absence of violence/terrorism, rule of law, control of corruption, government effectiveness
  and regulatory quality (World Bank WGI), intentional homicides (UNODC), military expenditure as a share of GDP
  (SIPRI) and the Corruption Perceptions Index (Transparency International). Each measure shows the state's course since
  1990 on its own scale, its latest value and its place among the library's states, and says which end is better
  (military spending is context, not a grade); nothing is combined into a score.
- **A page of all ratings per state** (`/ratings/<country>`): one small chart per measure, with the source, the place
  and the state's official reports on the matching topic (terrorism, organised crime, corruption, military threat).
- The **ratings map** (formerly the democracy map) colours countries by any of these measures; blue is always the better
  end, and a measure without one gets a single-hue scale.

## [0.69.1] – 2026-10-19

### Added
- **Roadmap H – research and designs** for three of the owner's topics, with the data checked on 2026-10-19:
  a full-screen timeline of events with chains of stated causes and effects, joined to reports and subjects
  ([docs/TIMELINE.md](docs/TIMELINE.md)); what a local library of about 100 books would take, and which "meanings" can be
  shown without a language model ([docs/BOOKS.md](docs/BOOKS.md)); country ratings beyond democracy – security,
  governance, media, cyber and disaster risk – with each candidate's licence and access
  ([docs/COUNTRY_RATINGS.md](docs/COUNTRY_RATINGS.md)).

## [0.69.0] – 2026-10-19

### Added
- **Commercial analysts – a third kind of publisher.** Companies that sell political-risk, security or threat analysis and
  publish part of it openly are marked ■ (a dashed badge, a square on the map, their own section on Sources and on the
  credibility page), kept apart from official agencies and ◆ think tanks; the home page, Documents, Trends and every year
  bar count their reports separately, and "Official agencies only" leaves them out. First sources: Eurasia Group (Top Risks
  2016–2023), ESET (half-yearly Threat Reports and APT Activity Reports), Graphika (influence-operations investigations,
  from its sitemap) and Microsoft's Digital Defense Report; the Allianz Risk Barometer and Munich Re's natural catastrophe
  figures are listed for collection by hand (their sites refuse automated requests).
- **A credibility rating for companies:** who owns them (listed, owners with or without stakes, undisclosed, a stake held by
  an autocracy's state), whether they name clients, and – for think tanks too – whether authors and a method are published.
- **US federal contracts and grants** for every think tank and company with a named recipient, by awarding agency since
  FY2008, from USAspending.gov (only the exact recipient names count – the API's search is loose).
- **Owners, sponsors and influence in the network:** each think tank and company is a subject of the network (layer
  "Publisher profiles") linked to its owners, founders, leaders, investors and partners, its donor governments, the US
  agencies that paid it and the current owner, funder and leaders on its Wikidata item (past chief executives are left
  out; a grant shows its year, amount, purpose and the reference Wikidata cites) – each link with its evidence – and its
  profile page lists the same ties.
- The crawler reads XML sitemaps as lists of publication pages, and a page can follow more than 25 of them (`follow_limit`).

### Fixed
- Link titles: entities left as text (`&hairsp;`), soft hyphens and typographic spaces become plain text, a hair space
  inside a label is closed up ("T1 2021", not "T 1 2021"), the `download` attribute names a file behind a bare
  "Download" link, and a PDF cited inside a sentence keeps its own name instead of the page's heading.

## [0.68.1] – 2026-10-16

### Added
- Sources on cognitive and narrative warfare, harvested from the links in Small Wars Journal posts: the Swedish
  Psychological Defence Agency (MPF, Swedish and English publications), the French military research institute IRSEM,
  the US–China Economic and Security Review Commission's annual reports, the UK Development, Concepts and Doctrine
  Centre's strategic-trends series, and – as think tanks, each with a funding profile – RAND (information operations and
  psychological warfare) and the Atlantic Council's DFRLab. NATO's Science and Technology Organization and Allied Command
  Transformation are listed for collection by hand (their sites block automated requests).

### Fixed
- A publication page that also links other publications ("Get publication <name>") now gives each PDF its own name,
  not the page's heading; screen-reader notes ("opens in a new window") and size notes without brackets
  ("PDF, 0.1 MB") no longer end up in titles.
- A folder that groups numbered reports (RAND's `RRA2000/RRA2032-1/…`) is no longer read as a publication year.

## [0.68.0] – 2026-10-16

### Added
- **Wanted notices as a network source** (`fetch-wanted`, `rozvedka/wanted.py`, layer “Wanted notices (FBI, Europe's Most
  Wanted)”): 352 FBI notices (its public API) and 24 of Europe's Most Wanted, only those about security – the FBI's cyber,
  counter-intelligence, China, Iran, terrorism, transnational repression and criminal-enterprise notices, the European ones
  for terrorism, criminal organisations, computer crime, trafficking and money laundering. Never victims or missing persons;
  no photographs or physical descriptions are kept. A notice is merged with the same person's sanctions entry when the name
  and the full date of birth agree (109 notices, e.g. the GRU officers of Units 26165 and 74455 on the OFAC and EU lists), and
  with an actor of the gazetteer by full name (12). Its text is read with the narrative name rules and the reports' actor
  matching: 571 links – a GRU officer to Unit 74455 (Sandworm), the indicted to each other, Mabna Institute contractors to
  the IRGC. A notice about several people (“APT 41 Group”, “GRU 29155 Cyber Actors”) is a case node linking them. The relation
  – member or officer, charged together, family, associate, support or funding, target, victim – is a hint from a word near
  the name; in a hand-read sample of 40 links all 40 named the right subject and 24 of 27 hints were right. The
  investigating agencies (FBI, DEA) are not linked; targets and victims do not count as connections for leads.
  Entity and actor pages show the notice, its charges and an “allegation, not a conviction” note.

### Fixed
- Actor matching: “People's Liberation Army” no longer counts as the Manipur group of that name (73 reports meant China's
  PLA), and “KGB” and “ARC” count for Belarus's KGB and the Caribbean Revolutionary Alliance only next to words of their
  field (found reading the wanted notices).
- Dates of birth written month first (“December 28, 1951”) are understood.

### Not added
- Rewards for Justice: its robots.txt allows only search engines. The US Justice Department's press releases follow
  separately (its API searches titles only, at one request per 10 seconds).

## [0.67.0] – 2026-10-15

### Added
- **Links from the text of Wikipedia articles** (`fetch-wikitext`, `rozvedka/wikitext.py`, network layer “Wikipedia article text”):
  sentences of the English articles of the 843 actors the reports name that link to another known actor or person – 12,735
  links, each with the sentence, its section and the article revision, reading “its article names …” / “named in the article of
  …”. The relation word near the link (member, founded, split, funded, led, allied, attacked …) is shown as a hint in brackets
  (25 of 40 hints read by hand were right); sentences without one are “named in the article”. Countries are not linked; See also
  and References are skipped. Find a connection weighs these links between the infobox and co-mentions; leads ignore article
  links about conflict or without a relation word.

## [0.66.0] – 2026-10-14

### Added
- **Leads** (`/graph/leads`, menu Actors & threats): hypotheses – pairs of actors never named together in a report and not linked by any
  source, but sharing neighbours in the stated network, ranked by Adamic–Adar (hubs, shared software and shared rivals not counted);
  613 today. A page per lead with the shared neighbours and the evidence on both sides, and a review (confirmed / rejected / unclear
  with a note) kept in `sources/lead_reviews.yaml`; the strongest leads on actor pages.
- **Brokers** (`/graph/brokers`): entities whose stated links reach actors of several kinds (state, cyber, terror, armed, crime),
  ranked by the kind they reach less; every number opens those links.
- The list of links can be filtered by the kind of the other end and to stated links only (`other_kind`, `group=stated`); the
  release check also compares the leads' and brokers' numbers with their lists.

## [0.65.0] – 2026-10-14

### Added
- **Security vendors' names of threat groups** (`fetch-misp`, `rozvedka/vendors.py`): the MISP threat-actor galaxy (CC0) ties 176
  groups to the gazetteer's actors and adds their vendors' names (Forest Blizzard, STRONTIUM, TA422 …) to the report matching –
  only names that cannot be ordinary words and are no other actor's own name; the Actor names page shows them with their origin.
  MISP's “similar” and “overlaps” statements are a new network layer.
- **Toolkit twins** (`/graph/twins`, menu Actors & threats): pairs of ATT&CK groups ranked by the overlap of their techniques and
  software, rare items weighted up; a page per pair with what they share (rarest first), what only one uses and CVEs named near
  both; the closest twins on actor pages. The release check compares each pair's numbers with its page.

## [0.64.0] – 2026-10-14

### Added
- **One target on several sanctions lists** (`rozvedka/identity.py`): 11,155 entries of the EU, UK, UN and US lists are recognised as
  4,393 people, companies and vessels – by a UN reference the UK or EU entry gives, by a shared IMO, passport, national ID,
  registration or tax number plus a shared name word, or by the same name and (for people) date of birth; at most one entry per
  list, never two different actors. Entity pages list the entries, the reason for every merge, dates of birth, numbers and addresses.
- **Shared details** (network layer “ids”): street addresses, e-mail addresses, websites (platform accounts), telephone numbers and
  crypto wallets given by two different targets become entities linked to both – 2,946 links. The UK list's parent companies,
  subsidiaries and ships' owners and operators are linked by name (legal forms ignored); owners that are not listed but shared by
  several entries become entities too.
- The sanctions lists' dates of birth, identity and registration numbers, addresses and contacts are read with each entry.

### Changed
- EU list entries are named by their original or English name (the list also holds translations into every EU language).

## [0.63.0] – 2026-10-14

### Added
- **Find a connection** (`/graph/path`, menu Actors & threats): how two groups, people, companies or tools are linked – up to five
  chains of stated links, the most specific first. A step costs least on an official sanctions list and most where two actors are
  only named together in reports; passing through an entity costs more the more links it has (and extra for common system tools),
  so chains through hubs come last. Alternative chains take other routes. Each step shows its relation as the source states it,
  its layers and its evidence; co-mention-only steps are flagged. Layers and countries can be chosen; with no chain, the page
  says whether the two are in separate parts of the network. Suggestions while typing (`/api/entities/suggest`); actor and entity
  pages link to it.

## [0.62.0] – 2026-10-14

### Added
- **Network of stated links** (`/graph`, menu Actors & threats → Network): 22,109 links between 18,761 groups, people, companies,
  vessels, malware and campaigns, each with its layer and evidence – OFAC's “Linked To” remarks, UK statements of reasons, UN and
  EU listing narratives naming another listing (with the sentence), Wikidata and Wikipedia connections, MITRE ATT&CK (groups and
  campaigns using malware and tools, campaigns attributed to groups) and actors named together in at least two reports. A
  sanctions entry matched with an actor is that actor, so the layers meet: actor pages get a **Network** section and a key number.
  Links can be searched by any name (`/graph/ties`); entities that are not actors have their own page (`/entity/…`).
- Command `build-graph` (no network), run by `update` after the indexes; `fetch-attack` now also keeps ATT&CK's software,
  campaigns and their relations.
- The release check (`tools/check_links.py`) also compares the Network page's numbers with their lists.

### Changed
- The co-mention page is now called **Named together** (`/network`) so it is not confused with the new Network.
- In the network, a sanctions entry matched with one actor by its own name and with others only by aliases is that actor
  (OFAC's HIZBALLAH is Hezbollah, not the groups named like its aliases).

## [0.61.0] – 2026-10-13

### Added
- **Citations between kinds of publisher** (`/citations`): a chord diagram of how agency types cite each other – reports of one type
  linking to agencies of another (their sites or their reports in the library), think tanks included – with a table beside it holding
  every number. Each ribbon and each number opens exactly those reports, through the new Documents filter `cite=stype:<type>`
  combined with the citing type.

## [0.60.0] – 2026-10-13

### Added
- **Threat levels as small multiples**: above the statements, one small chart per state and scale on a shared time axis, each on
  its own scale with the steps named. An announced change is a step line (the level holds until the next announcement); a level
  stated in a report is an open dot, never joined – a reading at that time, not a history. Every mark opens its statement.

## [0.59.0] – 2026-10-13

### Added
- **Topic matrix: a reference column and over-emphasis.** "Who reports on what" starts with a column for all reports of the period
  (also of countries or agencies too small to get their own column), each cell linking to its reports. A new *over-emphasis* switch
  colours every cell by the row's share against that reference – from ¼× (blue) through 1× (neutral) to 4× (yellow) – so a country's
  or agency's emphasis shows rather than its size; the tooltip gives both shares and the factor. The CSV and table views are unchanged.

## [0.58.1] – 2026-10-13

### Changed
- **Every page in the console style**: panel titles in small capitals with their counts in green mono, table headers in small
  capitals, numbers in IBM Plex Mono, rows lit on hover. In the dark theme the agency-type badges are outlined in the type's colour
  (the map's colours) instead of pale boxes.

### Fixed
- The bars of the actor list start at the same place in every row (the count has a fixed-width column).

## [0.58.0] – 2026-10-13

### Changed
- **Actor timeline in the console style**: one year axis carries the dated events (◆ sanctions list, ▲ attribution, ■ designation,
  ● founding – hover for the date), the reports naming the actor each year as bars, and the reporting countries as a heat grid.
  Below, in panels: the dated events with sources, the actors named beside it with small yearly bars, and each agency's first-to-latest
  span (dots open the first and the latest report).
- **Actor page**: a strip of key numbers (reports, agencies, first named, most named year, attributions, sanctions entries) with the
  timeline as its last card; the yearly chart takes the theme's accent.

## [0.57.0] – 2026-10-13

### Added
- **Threat watch** on the overview: the five CVE numbers and the five ATT&CK techniques the reports name most, each count opening its reports.

### Changed
- **Overview in the console style**: a compact banner (smaller word mark and radar), a strip of key numbers (reports, official agencies,
  ◆ think tanks, countries, languages, editions to collect – each a link), and the dashboards as one grid of panels joined by thin lines.
  The banner and prompt take the theme's green.

## [0.56.0] – 2026-10-13

### Changed
- **New look: the "console" design** chosen from the redesign mockups. A dark, dense theme with green and yellow accents (orange is kept
  for warnings such as old data or CISA's exploited list); official agencies are green, think tanks amber with ◆, so the two stay apart.
  The light theme uses the same greens on white.
- **Side rail** instead of the top menu: the six groups as icons with names on the left; hovering (or keyboard focus) opens a group's
  pages. The top bar is a command-line search (`rz>`) on every page but the home page, with the data age and the Update button.
  Phones keep the Menu button.
- **IBM Plex Sans and Mono** for text and numbers, stored with the portal (`static/vendor/plex`, SIL Open Font License) – nothing loads
  from the internet.
- Sequential colour scales (topic matrix, network, maps) run from dark green to yellow in the dark theme and from pale to deep green in the light one.

## [0.55.0] – 2026-10-13

### Changed
- **Overview dashboard**: the 30- and 90-day "recently added" tiles repeated the whole library for a young library; a span that adds
  nothing over the shorter one is dropped, and a column chart shows the additions of each of the last 30 days (each column opens
  that day's list). Each bar of "Reports by publication year" is split into official agencies and think tanks (two colours, each part
  a link). "Rising topics" is a dumbbell: the earlier and the recent share as two dots on one scale, each opening its reports. The
  bars of "Library" take the colour of the agency type.

## [0.54.2] – 2026-10-13

### Changed
- **One home for the colours**: spacing, type sizes, radii and the chart colours (categorical, sequential, "no data") are tokens in `style.css`
  for both themes; the Trends, Network and "Who reports on which country" charts read them (values unchanged, the actor-kind dots now use the
  same categorical set). Changing the palette is a one-place edit.
- Icons for refresh, download, upload and edit come from one sprite (`static/icons.svg`, Lucide, ISC licence) instead of text symbols
  that look different on every system.

### Fixed
- The "Who reports on which country" map now uses a light colour scale in the light theme (it was a dark-theme scale on a pale map) and redraws when you switch the theme.

## [0.54.1] – 2026-10-13

### Changed
- Every list page now has a title (Documents, Actors, Agencies, Report series, Topics, Connections, Coverage, To collect, the Trends views and
  the topic mind map); the browser tab of the Documents page says "Documents".
- The long method notes on the Threat levels, CVEs, ATT&CK techniques, Citations and Attributions pages are folded under "How this is counted",
  below a one-line summary of what the page shows; the text is unchanged.
- The "← Actors" back links on pages of the Actors & threats section are gone: the section tabs under the header show where you are.

## [0.54.0] – 2026-10-13

### Added
- **A menu in six groups** – Overview, Library, Topics & trends, Actors & threats, Sources and Maintain. Hover (or keyboard focus)
  on a group opens its pages with one line on what each answers; the group's name goes to its main page. Under the header, tabs
  show the pages of the section you are in, with the current one marked – on every page, also detail pages (an actor page lights
  up Actors, a report page Documents). A search box sits in the header on every page but the home page, which has its own.
  The menu is one table (`rozvedka/nav.py`); a test fails when a page is missing from it.
- **All views** (`/views`, linked in the menu and the footer): every page of the portal as a card, grouped like the menu, with the
  number it holds where there is one (reports, agencies, CVEs, techniques …).
- **Phone menu**: below 860 px the header shows a Menu button that opens all groups with their pages and a search box.

### Changed
- Watchlist and Compare are no longer top-level entries (Library › Watchlist, Topics & trends › Compare agencies); Update, Coverage,
  To collect, Year conflicts, Actor names, Precision review and Data exchange are under Maintain. The copied tab rows on the Sources,
  Topics, Trends and Map pages and the row of small links on the Actors page are replaced by the section tabs.

### Fixed
- The map pages now follow the light/dark choice (they stayed dark in light mode).
- The topic matrix legend no longer says "darker = larger" (in the dark theme larger values are lighter): it points along the colour ramp.
- The "known connection" mark on the Network page renders on every system (the chain symbol showed as an empty box).
- Phone width: no page is wider than the screen any more (wide tables scroll inside themselves; header and menu fit).

## [0.53.0] – 2026-10-13

### Added
- **ATT&CK technique numbers** (`/techniques`): the technique numbers the reports name (T1566, T1059.001 …), found by pattern
  (`index-techniques`) and tied to MITRE's catalog (`fetch-attack`: Enterprise, Mobile and ICS, with versions and the retrieval
  date; MITRE's terms of use linked). The list shows each technique's name, tactics, reports, agencies and years; a technique
  page shows the reports naming it with the passage and page, and the groups MITRE lists as using it (linked where the group is
  in the actor index). Report pages list their techniques; the Documents page filters by `technique=`. Numbers MITRE has retired
  stay (marked), since reports still cite them; numbers that are in no matrix are left out and counted on the page.

## [0.52.0] – 2026-10-12

### Added
- **Dated events on the actor timeline**: the page `/actors/<key>/timeline` opens with everything dated that the library's data says
  about the actor, oldest first, each with its source – founding and dissolution and designations as a terrorist group
  (Wikidata, with the designating state), entries of the EU, UK, UN and US sanctions lists, the official attributions,
  for a country the official changes of its terrorism threat level, and the first and last year a report names the actor.
  Only dated facts; nothing is estimated (undated Wikidata designations are left out).

## [0.51.0] – 2026-10-12

### Added
- **Who cites whom** (`/citations`): `index-citations` reads the web addresses in the report texts (41,858 links in 1,877
  reports) and resolves them: a report of the library (117 links, 92 distinct targets in the usual scope), the site of another
  agency (home-page host, or a path inside a shared portal like gov.uk; ambiguous hosts are not guessed at) or an outside
  source. The page ranks the agencies other agencies link to (e.g. ENISA, DHS, Europol, BSI, NCSC-UK), the reports most
  cited by reports, and the most linked outside hosts with a hand label for well-known ones (news, academic, law …). Report pages
  show what a report links to and which library reports link to it; the Documents page filters `cite=` (reports citing a report,
  cited by one, linking to an agency's site or to a host), so every count links to the reports it counts (checked for the top
  entries). Addresses broken across lines in a PDF are not recovered – every count is a minimum. `update` runs the indexing.

## [0.50.0] – 2026-10-12

### Added
- **Terrorism threat levels of states, with the passage behind each** (`/threat-levels`): 24 hand-curated statements for the
  UK, the Netherlands, Belgium, Spain, Austria, Sweden and Latvia, each with a verbatim quote and its check. Two kinds –
  the UK's official change announcements (MI5, 10 changes from 2014 to May 2026; `fetch-threat-levels` re-checks the page) and
  levels that agencies' reports in the library state (quote checked against the library's text every time, with the page,
  linked to the report). Each state is shown on its own scale (a "3" in Belgium's four steps is not a "3" in the Netherlands' five;
  levels are never ranked across states). A report shows the level at that time, not when it began.

## [0.49.0] – 2026-10-12

### Added
- **CVE numbers in the reports, tied to CISA's Known Exploited Vulnerabilities list**: `index-cves` finds every
  CVE-YYYY-NNNN in the report texts (351 reports, 1,203 different numbers) and `fetch-kev` downloads CISA's catalog
  (CC0; 1,739 entries) with its version and retrieval date. `/cves` lists the numbers with reports, agencies, years, and
  whether and since when CISA lists them (ransomware use shown); a CVE page gives CISA's entry, the reports naming it with
  passage and page, and the actors named in the same passage. Actor pages get "Vulnerabilities named near it", report
  pages the CVEs they name, and the Documents page filters `cve=` (also `cve=kev` and `cve_near=<actor>`), so every count
  links to exactly the reports it counts. The catalog says what is exploited, never by whom – the actor link is a nearness
  in the text and is labelled so. `update` runs `index-cves`.

## [0.48.0] – 2026-10-12

### Added
- **Optional systemd user service for the portal** (roadmap E1): `python -m rozvedka service install` writes the unit
  file and reloads systemd – it never enables or starts the service, and nothing in the project calls it; `show`,
  `status`, `verify` and `uninstall` complete the command. Tested on the Pi with a service of another name and port:
  `systemd-analyze` found nothing to complain about, the sandboxed portal started, served pages and wrote to the
  database, came back 5 s after being killed and stopped cleanly; the test service was then removed. Starting after a
  reboot without a login would need `loginctl enable-linger` (sudo), which is not part of the setup.

### Fixed
- The unit template put the system in read-only mode (`ProtectSystem=strict`) without allowing the project folder, so the
  portal could not have written its database; it now allows the project folder and the data folder. Its `After=network-online.target`
  (a system target a user service cannot wait for) is gone, and the `update` command's help no longer mentions a timer.

## [0.47.2] – 2026-10-12

### Changed
- **`rozvedka/app.py` is split into route modules** (roadmap E3): the 88 routes now live in `rozvedka/routes/` (one module
  per area: actors, documents, trends, maps, data, update, …), what they share in `rozvedka/web.py`; `app.py` keeps the
  app, its middleware and start-up. No change for users: the route list is identical (checked against the old one) and
  all tests pass unchanged.

## [0.47.1] – 2026-10-12

### Changed
- **Faster pages on the Pi**: the Actors page 5.3 s → 0.1 s, an actor page 4.0 s → 0.3 s, the home page 1.1 s → 0.2 s
  (measured on the Pi, repeat visits). The review file (1,800 verdicts) was parsed on every request, now only when it
  changes and with the C parser where libyaml is present; the Actors list, the review figures and the home dashboard are
  kept until the database, a `sources/*.yaml` file or the day changes (`db.cached`). The first visit after a change is as
  slow as before.

## [0.47.0] – 2026-10-09

### Added
- **Official attributions** (roadmap D6): `sources/attributions.yaml` lists 21 statements of the UK NCSC and US CISA that
  name a cyber threat group and, where the page says so, the state body behind it (GRU, SVR, FSB, China's MSS, Iran's
  MOIS and IRGC, North Korea's RGB) – each with a verbatim quote. `fetch-attributions` downloads the pages and checks that
  the quote is on them; actor pages get an "Official attributions" section (statement, quote, issuer, date, last check) and
  `/actors/attributions` lists all. The Council of the EU blocks automatic access, so its statements are not included.

## [0.46.1] – 2026-10-09

### Changed
- **Actor matching reviewed beyond the top 200 names** (roadmap B1): 890 more passages of 259 more names were read, so
  the review now covers 456 names, 1,802 passages and 75 % of the actor–report links (before: 197 names, 55 %).
  Measured precision of the whole sample is 91.6 %; 96.1 % on the 1,716 passages of the names still in use after the
  fixes below (the fixes come from the same samples, so this figure is optimistic until names are read again).
- **Names that meant something else are fixed** (`sources/actors.yaml`, each with its reason): "Box 500" (a PO box, not
  MI5), "Stephen Murphy", "Cobra", "Guardia Nacional", "Anonim" (Turkish "joint-stock"), "Syrian opposition",
  "Intelligence Academy", "JIC" and "Joint Intelligence Center", "President Bush", "Islamic Jihad" are not matched; "Leviathan",
  "Confucius", "Havex", "Reaper", "Quds", "Abu Bakr", "Foxtrot", "CSE", "Staatssicherheit" and "Intelligence Division"
  count only with a word of their field nearby; Säpo, the DEA and Iván Márquez skip the report series that use the name
  for a Peruvian river, a Scottish agency and a Colombian director.
- The review file is written once per batch of verdicts (`review.record_many`) instead of once per verdict.

## [0.46.0] – 2026-10-09

### Added
- **Actor timeline** (roadmap C3): `/actors/<key>/timeline`, linked from every actor page. It shows the first and last
  report of each agency that names the actor, a year × reporting-country grid of reports, and a year grid of the
  actors named in the same passage, with the ones that appeared (**new**) or vanished (**gone**) in the last three years
  marked. Every cell links to the exact reports it counts.

## [0.45.0] – 2026-10-09

### Added
- **Sanctions and designations** (roadmap D1): `fetch-sanctions` downloads the consolidated lists of the EU, the UK, the UN
  Security Council and the US (OFAC SDN) and matches their entries with the actors by name. Actor pages get a section
  with every entry – list, reference, matched name, date, programme and legal basis, source and retrieval date – and
  `/actors/sanctions` lists all designated actors, filtered by list, kind and match. Matching is deliberately strict
  and stated on the page; entries listed under the actor's own name (38 of 40 sampled right) are kept apart from
  alias-only matches (23 of 30). `match-sanctions` re-matches without downloading; `index-actors` and the update job do it too.

## [0.44.1] – 2026-10-08

### Added
- **Oversight bodies** (reports on what the services do, from the bodies that review them): Denmark TET, Norway
  EOS-utvalget, UK IPCO, Switzerland AB-ND, Belgium Comité R (activity and investigation reports), Netherlands CTIVD
  (manual: its list is script-built).
- **International and EU bodies:** UNODC (World Drug Report 2021–2025), INTERPOL (crime trend reports); by hand because
  the sites block or script their files: UN Security Council 1267 Monitoring Team, UNDRR (GAR), FATF, IAEA, EUDA,
  CERT-EU, Eurojust.
- **National security strategies:** Germany's National Security Strategy (all translations), NATO Strategic Concepts
  1949–2022, US Department of Defense strategy documents; Austria's BMI Security Report (several volumes a year).
- Not found, so not added: regular national risk assessment or civil-protection reports of Bulgaria, Cyprus, Greece,
  Romania and Slovakia (published only as one-off plans or on script-built pages); CIRCL (conference slides, no regular
  report), KISA, TWCERT/CC.

### Fixed
- Link text that is only markup residue or a row of language labels ("true true", "EN FR ES AR") is no longer used as
  a report title.

## [0.44.0] – 2026-10-08

### Added
- **What changed between two editions** of a report series (`/series/<id>/changes`, from the series page and from a
  report's "Against the previous edition" box): topics that are new, gone, or now / no longer main, with scores; actors
  named for the first time and no longer named, each with the passage and page; actors named clearly more or less often.
  One file per year in the series language, nothing hidden: counts say how many more actors exist beyond those shown.

## [0.43.0] – 2026-10-08

### Added

- **The Actors page shows the measured precision of the name matching**: 92.7 % – 912 passages of 197 names read,
  845 right and 67 wrong – with what it covers (the reviewed names give about 55 % of the actor–report links; the
  other names are not measured) and a link to the reviewed names. The review page lists every reviewed name, also those
  that no longer count, so its rows add up to the totals.

### Changed

- **Names 41–200 reviewed**: 853 more passages were read (787 right, 66 wrong; `reviewer: Claude` in
  `sources/actor_reviews.yaml`). Names that were mostly wrong now have rules; the index has 267 fewer actor–report links
  (63,862 → 63,595), after the shared names that now count added about 40 correct ones:
  - an article and an ordinary word counts like the word: "The Home" (Home Office → Die Heimat), "la Fédération"
    (de Russie → Sinaloa Cartel), "The Foundation" (→ al-Qaeda), "La Empresa" are dropped because the word is mostly
    written in lowercase;
  - "administration" and "federation" are generic words, so "Security Administration" (US agencies → a Yugoslav
    service) needs another name of its actor in the same report;
  - a shared name of several words belongs to the group it is the label of: "Feuerkrieg Division" and "Sonnenkrieg
    Division" are now those groups rather than Atomwaffen Division, and the Romanian "Serviciul de Informații
    Externe" is Romania's foreign intelligence service, not Russia's SVR;
  - words of their field are needed next to "Snake" (Turla, not Snake Island or the Snake keylogger), "Antifa" (the
    German movement), "Potok" (the PMC, not Slovenian place names) and "National Security Council"/"NSC" (India's,
    not other countries' councils);
  - hand exclusions for ordinary words: "Ansar" (Ansar al-Sharia, Ansar Allah …), "Renaissance", 復興, 再生 and 复兴
    (Revival), "Patria" and other translations of "homeland" (Die Heimat); NATO's own reports no longer count for EU
    INTCEN through NATO HQ's "SITCEN". Exclusions now also apply to names in Chinese or Japanese script.

## [0.42.7] – 2026-10-08

### Added

- **First measured precision of the actor matching.** 199 passages for the 40 names that put the most reports on actors
  were read and judged (*Actors → Review*): 190 right, 9 wrong – **95.5 %**. The verdicts are in
  `sources/actor_reviews.yaml` with the passage as evidence and `reviewer: Claude`; the owner can overrule any of them on
  the review page. (Names not in the top 40 are not measured yet.)
- `context_aliases` in `sources/actors.yaml`: a name that is also a common surname counts only when a word of its field
  stands within six words of it.

### Fixed

- Errors found by the review, fixed by general rules where there was one:
  - "Wagner" matched authors in reference lists (8 of 20 further passages): it now needs a word like *military*, *group*,
    *mercenaries* nearby – Wagner Group 110 → 73 reports, all 14 passages checked afterwards are the group. The same for
    "Lazarus" (87 → 79 reports).
  - "Donald Trump Jr." (and any person's name followed by Jr., Sr., Junior) is no longer the father.
  - A name at the end of a line before a soft hyphen is a word's beginning ("Conti-nuidad" is not the Conti group).
  - "Putina", the district in Peru, no longer counts as Vladimir Putin in the civil-defence reports of INDECI (52 reports).

## [0.42.6] – 2026-10-08

### Added

- 19 Italian intelligence annual reports (DIS *Relazione annuale*, 2007–2025) that were listed as "open in a browser only"
  are now in the library: the site hands the files to scripts again, so a retry succeeded.

### Changed

- **Download again** (`download --retry-failed`, and the option on the Update page) now also retries reports that were
  listed as open-in-a-browser-only, since sites change.
- The Norwegian intelligence service's site (E-tjenesten) is bot-protected with a JavaScript client challenge; it is now
  a manual source (*To collect*) instead of an automatic one.

### Fixed

- Links to an in-page PDF viewer (`/pdfjs/?file=…pdf`, as on the NATO StratCom CoE site) are read as the PDF itself;
  twelve such "Read online" entries were duplicates of reports already in the library and are gone.

## [0.42.5] – 2026-10-08

### Added

- Civil-protection reports for two more countries: the **Estonian Rescue Board** yearbooks (Päästeamet, 2014–2025) and the
  **Latvian State Fire and Rescue Service** public reports (VUGD, 2008–2025).
- Cyber: **JPCERT/CC** (Japan) quarterly incident-handling reports in English and Japanese, 2008–2025.
- The **Lithuanian Fire and Rescue Department** (PAGD) is listed on *To collect*: its site refuses automatic requests, so
  its activity reports are added by hand.

### Fixed

- Detached PGP signature files (`….pdf.asc`) next to a report were listed as documents; the crawler no longer takes them.
- `tools/check_links.py` works again: since 0.42.0 the portal's host check refused its test client.

## [0.42.4] – 2026-10-07

### Changed

- The ROZVEDKA lettering on the home page carries a háček over the E (Ě), as in the Czech *rozvědka*.

## [0.42.3] – 2026-10-07

### Fixed
- Maps: moving the pointer quickly over states or headquarters left the previous hover cards on screen for a moment,
  so several overlapped. A closing card now disappears at once – only the card under the pointer shows (all three
  maps).

## [0.42.2] – 2026-10-07

### Fixed
- Map: zoomed-in street tiles showed "Access blocked" from OpenStreetMap. Since 0.42.0 the portal sends no referrer to
  other sites, and OpenStreetMap's tile policy requires one; the map tiles now send the page's origin (only the
  address and port, never the page path).

## [0.42.1] – 2026-10-07

### Changed
- The repository is public. The README's version badge now shows the latest GitHub release by itself (a release no
  longer edits it), with a badge of the test run on `main` and the supported Python versions (3.10–3.13).

## [0.42.0] – 2026-10-07

### Security
- **Importing a dataset can no longer write outside `data/files/`.** A crafted dataset could give a report file a path
  such as `../../.bashrc` and so place files anywhere the portal's user may write; such files are now skipped and
  counted. Part files must sit beside the manifest, and the values a manifest shows on the Data exchange page must be
  numbers (no markup from someone else's file reaches the page).
- **Requests from other websites are refused** when they would change something (updates, imports, exports, edits –
  cross-site request forgery), and the portal answers only to IP addresses, `localhost`, local names and names in
  `ROZVEDKA_ALLOWED_HOSTS` (DNS rebinding). Every response forbids framing by other sites, MIME sniffing and sending
  the address to other sites.

### Changed
- **`serve` now listens on this computer only (127.0.0.1) by default.** For the home network start it with
  `--host 0.0.0.0` or set `ROZVEDKA_HOST=0.0.0.0`; the systemd unit does so.
- The systemd unit in `deploy/` is a template that works from any folder (install commands at its top) and runs with
  a read-only system.
- Report file and inbox paths are stored with `/` on every system (Windows stored `\`).
- The folder picker also offers `/Volumes` (macOS disks).
- Documentation: Security and Compatibility sections, the environment variables, an install that works from any
  folder; CI measures Linux x86-64 and ARM64 with Python 3.10–3.13, macOS and Windows.

## [0.41.0] – 2026-10-07

### Added
- **Actor search with suggestions** (Actors page): as you type, up to 12 actors whose names or aliases match – in any
  language, accents ignored, misspellings forgiven (letter-triple similarity, or one letter off for short words) –
  with picture, kind, number of reports and the alias that matched. With fewer than ten direct matches, the actors
  most often named in the same passages as the best match fill the list, with the number of reports naming both.
  Keyboard: ↑ ↓ to choose, Enter to open, Esc to close; Enter without a choice still filters the list.

## [0.40.0] – 2026-10-07

### Added
- **Actor profiles**: each actor page opens with a picture – the flag or logo of a group, the photo of a person, the
  flag of a country – with author, licence and Commons file page; key facts from Wikidata (born, died, citizenship,
  occupation, positions held with years; founded, founder, leader, ideology, headquarters, members, website), each
  linked to its Wikidata statement in the reference table; and the opening of the English Wikipedia article (now
  also for people, who had none before).
- New command `python -m rozvedka fetch-actor-profiles` (also run by `fetch-actors`): fetches the profiles of every
  actor the reports name into `data/gazetteer/actor_profiles.json` and stores each freely licensed picture once as a
  small thumbnail; the portal makes no outside calls.

## [0.39.0] – 2026-10-07

### Added
- Topic mind map: **Expand all**, **Topics** and **Collapse all** buttons, keyboard support (Tab, Enter), and a count
  of the topics and actors shown.

### Changed
- The topic mind map loads in under a second instead of ~11 s: its data comes from one database query instead of one
  per topic (same counts – a test compares them with the Documents filter's rule).
- The mind map is drawn as a tidy tree: each column is as wide as its longest label, long names wrap to two lines and
  the page grows as branches unfold, so labels no longer overlap when a topic is expanded. It follows the light and
  dark theme. Scroll-to-zoom and dragging are gone – the page scrolls instead.

## [0.38.1] – 2026-10-07

### Fixed
- Map hover cards no longer squeeze into a narrow column with one word per line (near the right edge of the map, and
  on the Democracy map almost always); they are sized by their content and fully opaque, and their pointer matches the
  side they open on.
- A cluster's agency list near the top of the map opens below the cluster instead of being cut off.

### Changed
- Democracy map hover card: each measure with its source, the measure the map shows in bold, and a larger
  Liberal Democracy Index trend line 1990–2025. Source dots: country, agency type or think-tank credibility, years
  covered and what a click opens. Countries without agencies say so instead of "0 agencies · 0 documents".

## [0.38.0] – 2026-10-07

### Added
- **Democracy map** (`/map/democracy`): every country coloured by V-Dem regime type, Liberal Democracy Index, its
  change in ten years, Freedom House or World Bank Voice and Accountability, for any year 1990–2025 with a slider and a
  ▶ play button. The panel counts states per regime type (world and library), lists the library's states with a trend
  line, change arrow and the number of their official reports that year (each opens the documents); hover cards show
  every measure of the year. The library's sources appear as dots sized by their reports, think tanks in their
  credibility colour. Settings are kept in the address.
- Headquarters map: **"Shade countries by"** now offers the regime type (V-Dem, latest year) besides the number of
  reports, and agency cards and country tooltips show the state's regime type.

### Changed
- The map panel is wider (360 px) so the three map views' tabs fit.

## [0.37.1] – 2026-10-07

### Added
- README: a **Database** section – where the data lives and what is rebuilt from what, how to open it read-only (SQLite
  shell, Python, DB Browser, Datasette, or the database taken out of a catalogue dataset), example queries, the
  condition the portal counts with, an entity-relationship diagram and a table of every table with its rows and purpose.
- `tools/screenshots.py` retakes every README screenshot from a running portal; all screenshots refreshed for 0.37.

### Fixed
- Search suggestions on the home page took about 6.5 s per keystroke (the actor query joined every name with every
  report before filtering); now about 0.15 s.
- Home page: the think-tank badge overlapped the report titles in the *Newest editions* and *Recently added* lists –
  now a compact coloured ◆ with the rating in its tooltip.
- The Update page's source table and the *To collect* list now mark think tanks too.

## [0.37.0] – 2026-10-07

### Added
- **Think-tank credibility profiles** (`/publishers`, *Sources → Think tanks*): checks with evidence instead of a score –
  funding transparency on Transparify's scale (researched by hand for all 17 think tanks, with evidence links and
  dates, `sources/publishers.yaml`), donor governments rated autocracies by V-Dem, EU Transparency Register entry (with
  declared EU grants), US FARA registration, and the sanctions lists of the US (OFAC), UK, EU and UN (new command
  `fetch-publishers`, also run by `fetch-actors`). Result today: transparent funding – SIPRI, Clingendael, HCSS, ASPI;
  concerns – CSIS (United Arab Emirates among its donors), ISW and IEP (donors not disclosed); the others partly
  transparent; no sanctions or FARA hits.
- **The ◆ badge is coloured by that rating** (and labelled: "think tank · concerns"), opens the profile, and the map's
  diamonds take the same colours; report pages of think tanks state the reason.
- **A profile page per think tank** (`/publisher/<id>`): the checks with evidence, former ratings, identity from
  Wikidata and Wikipedia (founded, headquarters, founders, leaders, revision), its state's democracy ratings, and its
  reports in the library – per year, main subjects, actors named most, latest reports, report pages.

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

[Unreleased]: https://github.com/iiogurt/Rozvedka/compare/v0.93.1...HEAD
[0.93.1]: https://github.com/iiogurt/Rozvedka/compare/v0.93.0...v0.93.1
[0.93.0]: https://github.com/iiogurt/Rozvedka/compare/v0.92.1...v0.93.0
[0.92.1]: https://github.com/iiogurt/Rozvedka/compare/v0.92.0...v0.92.1
[0.92.0]: https://github.com/iiogurt/Rozvedka/compare/v0.91.0...v0.92.0
[0.91.0]: https://github.com/iiogurt/Rozvedka/compare/v0.90.0...v0.91.0
[0.90.0]: https://github.com/iiogurt/Rozvedka/compare/v0.89.5...v0.90.0
[0.89.5]: https://github.com/iiogurt/Rozvedka/compare/v0.89.4...v0.89.5
[0.89.4]: https://github.com/iiogurt/Rozvedka/compare/v0.89.3...v0.89.4
[0.89.3]: https://github.com/iiogurt/Rozvedka/compare/v0.89.2...v0.89.3
[0.89.2]: https://github.com/iiogurt/Rozvedka/compare/v0.89.1...v0.89.2
[0.89.1]: https://github.com/iiogurt/Rozvedka/compare/v0.89.0...v0.89.1
[0.89.0]: https://github.com/iiogurt/Rozvedka/compare/v0.88.0...v0.89.0
[0.88.0]: https://github.com/iiogurt/Rozvedka/compare/v0.87.0...v0.88.0
[0.87.0]: https://github.com/iiogurt/Rozvedka/compare/v0.86.0...v0.87.0
[0.86.0]: https://github.com/iiogurt/Rozvedka/compare/v0.85.0...v0.86.0
[0.85.0]: https://github.com/iiogurt/Rozvedka/compare/v0.84.0...v0.85.0
[0.84.0]: https://github.com/iiogurt/Rozvedka/compare/v0.83.0...v0.84.0
[0.83.0]: https://github.com/iiogurt/Rozvedka/compare/v0.82.1...v0.83.0
[0.82.1]: https://github.com/iiogurt/Rozvedka/compare/v0.82.0...v0.82.1
[0.82.0]: https://github.com/iiogurt/Rozvedka/compare/v0.81.0...v0.82.0
[0.81.0]: https://github.com/iiogurt/Rozvedka/compare/v0.80.0...v0.81.0
[0.80.0]: https://github.com/iiogurt/Rozvedka/compare/v0.79.0...v0.80.0
[0.79.0]: https://github.com/iiogurt/Rozvedka/compare/v0.78.0...v0.79.0
[0.78.0]: https://github.com/iiogurt/Rozvedka/compare/v0.77.0...v0.78.0
[0.77.0]: https://github.com/iiogurt/Rozvedka/compare/v0.76.0...v0.77.0
[0.76.0]: https://github.com/iiogurt/Rozvedka/compare/v0.75.1...v0.76.0
[0.75.1]: https://github.com/iiogurt/Rozvedka/compare/v0.75.0...v0.75.1
[0.75.0]: https://github.com/iiogurt/Rozvedka/compare/v0.74.0...v0.75.0
[0.74.0]: https://github.com/iiogurt/Rozvedka/compare/v0.73.0...v0.74.0
[0.73.0]: https://github.com/iiogurt/Rozvedka/compare/v0.72.0...v0.73.0
[0.72.0]: https://github.com/iiogurt/Rozvedka/compare/v0.71.0...v0.72.0
[0.71.0]: https://github.com/iiogurt/Rozvedka/compare/v0.70.0...v0.71.0
[0.70.0]: https://github.com/iiogurt/Rozvedka/compare/v0.69.1...v0.70.0
[0.69.1]: https://github.com/iiogurt/Rozvedka/compare/v0.69.0...v0.69.1
[0.69.0]: https://github.com/iiogurt/Rozvedka/compare/v0.68.1...v0.69.0
[0.68.1]: https://github.com/iiogurt/Rozvedka/compare/v0.68.0...v0.68.1
[0.68.0]: https://github.com/iiogurt/Rozvedka/compare/v0.67.0...v0.68.0
[0.67.0]: https://github.com/iiogurt/Rozvedka/compare/v0.66.0...v0.67.0
[0.66.0]: https://github.com/iiogurt/Rozvedka/compare/v0.65.0...v0.66.0
[0.65.0]: https://github.com/iiogurt/Rozvedka/compare/v0.64.0...v0.65.0
[0.64.0]: https://github.com/iiogurt/Rozvedka/compare/v0.63.0...v0.64.0
[0.63.0]: https://github.com/iiogurt/Rozvedka/compare/v0.62.0...v0.63.0
[0.62.0]: https://github.com/iiogurt/Rozvedka/compare/v0.61.0...v0.62.0
[0.61.0]: https://github.com/iiogurt/Rozvedka/compare/v0.60.0...v0.61.0
[0.60.0]: https://github.com/iiogurt/Rozvedka/compare/v0.59.0...v0.60.0
[0.59.0]: https://github.com/iiogurt/Rozvedka/compare/v0.58.1...v0.59.0
[0.58.1]: https://github.com/iiogurt/Rozvedka/compare/v0.58.0...v0.58.1
[0.58.0]: https://github.com/iiogurt/Rozvedka/compare/v0.57.0...v0.58.0
[0.57.0]: https://github.com/iiogurt/Rozvedka/compare/v0.56.0...v0.57.0
[0.56.0]: https://github.com/iiogurt/Rozvedka/compare/v0.55.0...v0.56.0
[0.55.0]: https://github.com/iiogurt/Rozvedka/compare/v0.54.2...v0.55.0
[0.54.2]: https://github.com/iiogurt/Rozvedka/compare/v0.54.1...v0.54.2
[0.54.1]: https://github.com/iiogurt/Rozvedka/compare/v0.54.0...v0.54.1
[0.54.0]: https://github.com/iiogurt/Rozvedka/compare/v0.53.0...v0.54.0
[0.53.0]: https://github.com/iiogurt/Rozvedka/compare/v0.52.0...v0.53.0
[0.52.0]: https://github.com/iiogurt/Rozvedka/compare/v0.51.0...v0.52.0
[0.51.0]: https://github.com/iiogurt/Rozvedka/compare/v0.50.0...v0.51.0
[0.50.0]: https://github.com/iiogurt/Rozvedka/compare/v0.49.0...v0.50.0
[0.49.0]: https://github.com/iiogurt/Rozvedka/compare/v0.48.0...v0.49.0
[0.48.0]: https://github.com/iiogurt/Rozvedka/compare/v0.47.2...v0.48.0
[0.47.2]: https://github.com/iiogurt/Rozvedka/compare/v0.47.1...v0.47.2
[0.47.1]: https://github.com/iiogurt/Rozvedka/compare/v0.47.0...v0.47.1
[0.47.0]: https://github.com/iiogurt/Rozvedka/compare/v0.46.1...v0.47.0
[0.46.1]: https://github.com/iiogurt/Rozvedka/compare/v0.46.0...v0.46.1
[0.46.0]: https://github.com/iiogurt/Rozvedka/compare/v0.45.0...v0.46.0
[0.45.0]: https://github.com/iiogurt/Rozvedka/compare/v0.44.1...v0.45.0
[0.44.1]: https://github.com/iiogurt/Rozvedka/compare/v0.44.0...v0.44.1
[0.44.0]: https://github.com/iiogurt/Rozvedka/compare/v0.43.0...v0.44.0
[0.43.0]: https://github.com/iiogurt/Rozvedka/compare/v0.42.7...v0.43.0
[0.42.7]: https://github.com/iiogurt/Rozvedka/compare/v0.42.6...v0.42.7
[0.42.6]: https://github.com/iiogurt/Rozvedka/compare/v0.42.5...v0.42.6
[0.42.5]: https://github.com/iiogurt/Rozvedka/compare/v0.42.4...v0.42.5
[0.42.4]: https://github.com/iiogurt/Rozvedka/compare/v0.42.3...v0.42.4
[0.42.3]: https://github.com/iiogurt/Rozvedka/compare/v0.42.2...v0.42.3
[0.42.2]: https://github.com/iiogurt/Rozvedka/compare/v0.42.1...v0.42.2
[0.42.1]: https://github.com/iiogurt/Rozvedka/compare/v0.42.0...v0.42.1
[0.42.0]: https://github.com/iiogurt/Rozvedka/compare/v0.41.0...v0.42.0
[0.41.0]: https://github.com/iiogurt/Rozvedka/compare/v0.40.0...v0.41.0
[0.40.0]: https://github.com/iiogurt/Rozvedka/compare/v0.39.0...v0.40.0
[0.39.0]: https://github.com/iiogurt/Rozvedka/compare/v0.38.1...v0.39.0
[0.38.1]: https://github.com/iiogurt/Rozvedka/compare/v0.38.0...v0.38.1
[0.38.0]: https://github.com/iiogurt/Rozvedka/compare/v0.37.1...v0.38.0
[0.37.1]: https://github.com/iiogurt/Rozvedka/compare/v0.37.0...v0.37.1
[0.37.0]: https://github.com/iiogurt/Rozvedka/compare/v0.36.0...v0.37.0
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
