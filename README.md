<div align="center">

# Rozvedka

**A self-hosted library of the public reports of intelligence, security and civil-protection agencies –
collected, searchable, indexed by topic and actor, and traceable back to the page they came from.**

![version](https://img.shields.io/badge/version-0.41.0-1f4e79)
![python](https://img.shields.io/badge/python-3.13-3776ab?logo=python&logoColor=white)
![fastapi](https://img.shields.io/badge/FastAPI-server--rendered-009688?logo=fastapi&logoColor=white)
![sqlite](https://img.shields.io/badge/SQLite-FTS5-003b57?logo=sqlite&logoColor=white)
![platform](https://img.shields.io/badge/runs%20on-Raspberry%20Pi-c51a4a?logo=raspberrypi&logoColor=white)

[Features](#features) · [Quick start](#quick-start) · [Commands](#commands) · [Configuration](#configuration) ·
[How it works](#how-it-works) · [Database](#database) · [Development](#development) · [Sources & licences](#data-sources-and-licences)

<img src="docs/images/home.png" alt="Home page: ASCII radar and word mark, the search console, and dashboards of the newest reports" width="900">

</div>

## About

Intelligence services, cyber-security centres, civil-protection authorities and police agencies publish annual
reports, threat assessments and risk analyses. Rozvedka gathers them from the agencies' own websites into one
local library, so you can follow how state security, social resilience and disaster preparedness are developing
– and who reports on what.

| | |
|---|---|
| **Coverage** | 134 agencies and institutions in 50 countries and bodies: 26 EU member states, EU bodies and NATO, every NATO member except Montenegro (Iceland, Albania, North Macedonia, Türkiye, the UK, Norway, the USA, Canada), Switzerland, Ukraine, six Latin American countries, Australia, New Zealand, Japan, South Korea and Taiwan |
| **Library** | about 3,450 reports in 30 languages, with archives back to 2000, downloaded as PDF |
| **Index** | full text of every report, 66 topics from a 4,400-term multilingual keyword list, about 1,550 named actors and 189 countries |
| **Runs on** | a Raspberry Pi (or any Linux box) – Python, SQLite and the browser; no cloud service, no account |

> [!IMPORTANT]
> **Everything is traceable.** Every number on every chart opens the list of documents it counts; every actor
> mention links to the page of the PDF it was found on; every external fact (an event date, a Wikidata
> designation, a Wikipedia summary) carries its source, revision and retrieval date. Nothing is estimated or
> generated – counts are counts of documents.

## Features

### 🛰️ Home – search console and dashboards

The start page (`/`): an ASCII radar and word mark, one search box for the whole library, and what is new.

- **Search console** – type words, `"a phrase"`, or filters: `country:DE`, `coalition:NATO`, `agency:BIS`,
  `type:cyber`, `topic:ransomware`, `actor:"Fancy Bear"`, `year:2020..2025`, `lang:de`. The search opens the
  Documents list with those filters set. A misspelt or ambiguous filter is explained, with the choices as links
  (`agency:BIS` → BIS in Czechia or Slovakia).
- **Suggestions as you type** – actors (by any of their names, e.g. `APT28` → Fancy Bear), topics, agencies and
  countries, each with the number of reports it lists. <kbd>↑</kbd>/<kbd>↓</kbd> choose, <kbd>Enter</kbd> opens,
  <kbd>Tab</kbd> puts the suggestion into the query as a filter, <kbd>/</kbd> jumps to the box. Recent searches
  are remembered in your browser only.
- **Dashboards** – newest editions; reports added in the last 7 / 30 / 90 days; reports per publication year
  (every report in one row, undated ones included); rising topics; the actors most named in last year's reports;
  the library by agency type and download state, with the editions still to collect; and when the data was last
  crawled. Every number opens the list it counts.

<img src="docs/images/home-search.png" alt="Search suggestions: actors, topics with report counts" width="900">

### 🆕 What's new – update by update

`/new` shows what each update brought; an update is a day on which reports entered the library (updates run on
demand).

- **New reports** by agency, each with its main topics and the actors it names most.
- **Named for the first time** – actors named in the update's reports and in no report found earlier.
- **Topics that jumped** – each topic's share of the update's reports against its share of the reports found before.
- An **Atom feed** (`/feed.atom`) of the newest reports with their topics, actors and official URL, for any feed
  reader on your network.

Every number opens the list it counts.

<img src="docs/images/new.png" alt="What's new: updates by day, actors named for the first time, topics that jumped, new reports by agency" width="900">

### ☆ Watchlist

`/watch` follows searches **update by update** – one list for the whole portal (no accounts, no per-browser state),
kept in [`sources/watchlist.yaml`](sources/watchlist.yaml) (written by the portal, editable by hand). An item is any
search-console query: `actor:"Wagner Group"`, `topic:ransomware country:DE`, `"critical infrastructure"`. Add one with
the box on the page, **☆ Watch this search** on the Documents list or **☆ Watch** on an actor page.

- **Reports per update** – a table of the watched searches × the latest updates (with the earlier ones summed), each
  cell the number of the item's reports that entered the library that day.
- **By update** – newest update first, which watched searches it brought reports for.
- Per item: its newest reports, each with its passage on the search (densest mentions or terms) and page, and an
  **Atom feed** of the item (`/feed.atom?watch=…`).

Every number opens the Documents list of exactly those reports.

<img src="docs/images/watch.png" alt="Watchlist: watched searches by update, the updates in order, the newest reports with passages" width="900">

### ⚖️ Compare agencies

`/compare` puts what agencies say about **one actor or one topic** side by side: one card per agency, ranked by how
many of its reports in the chosen years name the actor (or are tagged with the topic), with the agency's two reports
that deal with it most and, from each, the **densest passage** – the 600 characters with the most mentions or topic
terms, passing over reference lists and endnotes – with its page in the PDF. Filter by years, country, coalition and
agency type; start from the menu, an actor page (*compare what agencies say*) or the Topics page (*compare*).

<img src="docs/images/compare.png" alt="Compare agencies on Wagner Group: one card per agency with its densest passages and page numbers" width="900">

### 📚 Documents

The library itself (`/documents`): every report with its agency, country, language, year and topics.

- Filter by country, coalition (EU, NATO, Five Eyes, G7, Schengen, AUKUS, JEF, NATO IP4), agency type, language,
  year or year range, download status, topic (several at once) and actor.
- **Full-text search inside the reports** – `"quoted phrases"`, `OR` for your own alternatives, results with
  highlighted snippets, sorted by relevance, year or date added.
- **Cross-language search** – a word that names one of ~100 security concepts (`sources/concepts.yaml`) also finds
  its names in the other languages of the library: *Drohne* finds 449 reports instead of 25 (drone, dron, дрон,
  bezpilotní letoun, mehitamata õhusõiduk …). The names are the labels and aliases of the concept's Wikidata item,
  shown above the results with the item, its revision and the retrieval date; *Search only the words as typed* turns
  it off. Trends term charts stay literal.

  <img src="docs/images/cross-language.png" alt="Searching Drohne: the names in 30 languages from Wikidata, and translated hits highlighted" width="900">
- Open a report's own page (its title), the downloaded PDF, or the agency's original; correct a title, language
  or year; hide irrelevant files; add a document by URL for sites that block automatic downloads.
- Page through the results with numbered pages, first/last, "go to page", and 25 / 50 / 100 / 200 / 500 per page –
  the same pager on every list in the portal (actors, names, passages).
- **Reports, not files** – the language versions, summaries and file variants of one report are grouped and counted
  once: the edition of a yearly series in any language, the same address with another language marker (`_en.pdf` /
  `_de.pdf`, `/en/` / `/fr/`), or the same title with a language or "summary" ending ("TE-SAT 2025 – Zusammenfassung").
  The file with most text represents the report (English unless another version has 30 % more); each row lists the
  other files ("also de fr …"), and the report page shows them all with the rule that grouped them. Asking for a
  language, a series or *all files* lists every file. Mistaken groups are split in `sources/works.yaml`.

  <img src="docs/images/doc-works.png" alt="Documents: a Swiss situation report listed once with its German version beside it" width="900">

- **Document types** – every file is typed by transparent rules on its title and file name (in the library's
  languages), its report series and its page count: annual or periodic report, threat / risk assessment, strategy,
  bulletin, guide, other report – or **not a report**: statement / press release, law or regulation, budget table, form. The type and
  the rule behind it are on each row and on the report page, where it can be corrected by hand
  (`sources/doc_types.yaml`). Statements, laws, budget tables and forms stay in the library but are left out of every
  count, chart and dashboard, as hidden files are; the Documents list says how many it leaves out and shows them with
  the type filter. Sampled precision: 48 of 50 types right.

  <img src="docs/images/doc-types.png" alt="Documents with every type shown: press notices marked as statements not counted, a risk register as an assessment" width="900">

- **Year conflicts** (`/years`, linked from the Documents summary): reports whose stored year is contradicted by strong
  evidence – a Japanese era year in the title, a date stamp in the file name, a report heading on the cover naming
  another year – with the evidence and one click to use the year found or keep the stored one. Nothing changes
  without a verdict; verdicts are kept in `sources/year_reviews.yaml` and travel with datasets.

  <img src="docs/images/years.png" alt="Year conflicts: stored and found year with the evidence, and buttons to use or keep" width="900">

### 📄 Report page

<img src="docs/images/report.png" alt="Report page: provenance, series edition with what changed, topics with the terms that matched" width="900">

Every report title in the portal opens its own page (`/report/<id>`); the PDF stays one click away:

- **where it comes from** – agency, the document type and the rule that set it, the official address, the page it was found on, how it got into the library
  (crawler, address pattern, by hand), when it was listed and downloaded, size, pages, SHA-256, and whether its text
  came from OCR; how its year was found;
- **series and editions** – which edition of which series it is, the previous and next edition, the same edition in
  other languages, and what changed against the previous edition (topics new or no longer among the main ones,
  actors named for the first time in the series);
- **topics** with their score and **the terms that matched**, so every topic tag can be checked;
- **actors named**, each with its first passage and page number, and the countries named.

### 🏛️ Sources

<img src="docs/images/sources-independent.png" alt="Sources: the separate section of independent think tanks, each card marked with a diamond badge" width="900">

**Official agencies and independent publishers are always told apart.** Besides the state agencies and
intergovernmental bodies, the library includes pro-democratic and security **think tanks** – CEPA, Freedom House,
ISD, ECFR, V-Dem, SIPRI, ICCT, Clingendael, HCSS, IFRI, ICDS, ASPI, Lowy Institute, IEP; CSIS, ISW and GLOBSEC
collected by hand. They are marked **◆ think tank** wherever a source or report appears (Documents, report page,
home, What's new, Watchlist, Compare, Series, actor pages), have their own section on Sources, a yellow diamond
instead of a dot on the map, and every count can leave them out with **“Official agencies only”**; the Trends notes
and the Documents summary say how many think-tank reports a count includes.

One card per agency: flag, logo, official name in the original language and in English, home page, a short
description of what its reports cover, coalition tags with the year each country joined, the report pages it is
crawled from (with language and current/archive), and a link to its headquarters on the map.

### ◆ Think tanks – credibility profiles

<img src="docs/images/think-tanks.png" alt="Think tanks: each with its credibility rating and the checks behind it" width="900">

No current, credible ranking of think tanks exists, so each think tank gets **checks with evidence instead of a score**
(*Sources → Think tanks*, `/publishers`): how openly it discloses who funds it (Transparify's scale: amounts, brackets,
names, categories, none – researched by hand with the evidence link and date, `sources/publishers.yaml`), whether a
donor government is an autocracy (V-Dem), its **EU Transparency Register** entry, **US foreign-agent (FARA)**
registrations, and the **sanctions lists of the US, UK, EU and UN** (fetched: `python -m rozvedka fetch-publishers`).
The result – *transparent funding*, *partly transparent*, *concerns*, *red flag* – colours the ◆ badge wherever the
think tank appears and its diamond on the map, with the reason in words. Each think tank has a **profile page**: the
checks and their evidence, former Transparify ratings, identity from Wikidata and Wikipedia, its state's democracy
ratings, and its reports here – per year, main subjects, actors named most, latest reports.

### 🗳️ Democracy ratings of the reporting states

<img src="docs/images/ratings.png" alt="Democracy ratings: regime type per year since 1990 with the Liberal Democracy Index, Freedom House and World Bank scores, regime changes" width="900">

A report reads differently if its state has since slid from democracy (*Sources → Democracy ratings*, `/ratings`):
each state's **regime type year by year since 1990** (V-Dem Regimes of the World, colour) with the **V-Dem Liberal
Democracy Index** as a line, plus the latest **Freedom House** score and the **World Bank Voice and Accountability**
indicator – three independent measurements, each value linked to its source, with licence and retrieval date. Sort by
the largest decline in ten years. Country headings on *Sources* carry the same strip, and every **report page shows the
ratings of the report's own year** – with a warning when the state's regime type has changed since (e.g. Hungary 2010
electoral democracy, 2018 electoral autocracy). Data: `python -m rozvedka fetch-ratings` (also part of `fetch-actors`).

### 📅 Report series

<img src="docs/images/series.png" alt="A report series: editions per year and language, topic and actor profiles over the years" width="900">

Recurring publications – the BIS annual report in Czech and English, KAPO's annual review, the Verfassungsschutzbericht – read
**edition by edition** (*Series* in the menu):

- the **catalogue** of all series with how complete each is, its latest edition and a compact grid of the last years;
- a **page per series**: which editions the library has per year and language (✓ in the library, ↓ listed but blocked,
  ✗ missing, … expected, – not published); **how the series changed** – its main topics and the actors it names, year by
  year (topics × years and actors × years, every cell opens the edition); and **edition by edition** what each one is
  mainly about, whom it names most, what became or stopped being a main topic, and which actors appear for the first time;
- documents carry a badge of their series (*Annual Report · 2023*), and the documents list filters by series.

The library proposes series from recurring titles; confirm, rename, merge or reject them on *Sources → Coverage*
(stored in [`sources/series.yaml`](sources/series.yaml)), which also lists every series' gaps for maintenance.

### 📥 To collect – hand import with provenance

<img src="docs/images/collect.png" alt="To collect: missing editions with candidates, upload form and not-published marker" width="900">

What the crawler cannot fetch, in four tabs: **missing editions** of confirmed series (with the source's documents of that
year and language to pick as the edition, an upload form, or "not published"), **blocked downloads** (sites that hand the PDF
only to a browser – open the original, save it, upload it to the same report), **sources to check by hand** (bot-protected
sites with their report pages and the date you last checked) and the **inbox** (PDFs copied to `data/inbox/`, imported with a
short form). Every report added by hand keeps its official URL, the date it was added and whether that URL is on the
agency's official domains (marked *added by hand* in the documents list, with a warning when it is not); it is indexed for
search, topics and actors right away. New reports from the agencies' sites are found on the **Update** page – there is
no periodic job.

### 🏷️ Topics and full-text index

<img src="docs/images/topics.png" alt="Topics page: categories and topics with document counts" width="900">

- 66 topics in 9 categories – extremism, state threats, geopolitics, cyber, crime, migration, hazards,
  resilience, governance – e.g. *right-wing extremism*, *Russia – intelligence, influence & hybrid activity*,
  *drones & emerging military technology*, *floods & extreme weather*, *civil defence*.
- Each topic is defined by keywords in 28 languages in [`sources/topics.yaml`](sources/topics.yaml); a report gets
  a topic only when it mentions it substantially, not in passing.

### 📈 Trends

<table>
<tr>
<td width="50%"><img src="docs/images/terms.png" alt="Term trends: share of reports containing each term"></td>
<td width="50%"><img src="docs/images/matrix.png" alt="Who reports on what: countries × topics heatmap"></td>
</tr>
<tr>
<td><b>Term trends</b> – any words over time, one line per term, with translations joined by <code>OR</code>.</td>
<td><b>Who reports on what</b> – countries or agencies × topics for a period.</td>
</tr>
</table>

- **Topics over time** – share of reports (or of reporting agencies) per year for up to 8 topics, with the number
  of reports per year beneath, plus the topics that rose and fell most in the last two years.
- **Reference events** (9/11, the annexation of Crimea, COVID-19, the invasion of Ukraine, …) marked on the time
  axis, dated from Wikidata.
- Every view has a permalink, a table view, a CSV export with a source link on every row and a *Where these
  numbers come from* section (method, filters, excluded documents, taxonomy version).

### 🕵️ Actors

<img src="docs/images/actor.png" alt="Actor page: profile with photo, key facts and Wikipedia lead, mentions per year, reporting agencies and sourced reference data" width="900">

- An index of state services, cyber threat groups, terrorist-designated and armed groups, organised crime,
  movements and key people, built from **Wikidata**, **Wikipedia** and **MITRE ATT&CK**, and found by name in the
  report texts – in all report languages and with the aliases of each group (APT28 = Fancy Bear = Sofacy =
  Forest Blizzard).
- **Profile** at the top of each actor page: a picture – a group's flag or logo, a person's photo, a country's
  flag – with its author and licence from Wikimedia Commons, key facts from Wikidata (born, positions held,
  citizenship; founded, founder, leader, ideology, headquarters, members) each linked to its statement, and the
  opening of the Wikipedia article. Fetched with `fetch-actor-profiles` (part of `fetch-actors`) for every actor
  the reports name; only freely licensed pictures are used, stored once as small thumbnails.
- Each actor page: reference data with its source and revision, the Wikipedia lead, mentions per year, which
  agencies report on it, the topics of those reports, actors named in the same passage, and **the passages
  themselves with a link to the cited page of the PDF**.
<img src="docs/images/connections.png" alt="Connections of an actor: leadership, founders, members with sources and reports naming both" width="900">

- **Connections** – the people and organisations around each actor: members, leaders, founders, key people,
  parent organisations, subsidiaries and wings, allies, employers, party memberships. They come from the
  infobox of the actor's English Wikipedia article and from Wikidata statements (in both directions), each with
  its source – article, infobox field and revision, or Wikidata statement and cited reference. The connected
  people are added to the index and found by their full names, so a report naming e.g. Alexander Nix shows his
  link to Cambridge Analytica.
- In the reports: every passage lists the actors named nearby and marks those with a known connection
  ("member of the party", "led by" …); pair pages show the documented connection above the passages, and the
  Network marks connected ties with ⛓.
- Beyond security services and armed groups the index covers political parties (AfD, FPÖ, Rassemblement
  National, United Russia, CCP …) and companies, think tanks and media (Cambridge Analytica, Heritage Foundation,
  RT, Huawei, Gazprom …); add more as seeds in `sources/actors.yaml`.
- **Search with suggestions** on the Actors page: type part of any name or alias, in any language and with any
  spelling – *prigozin*, *hezbolah*, *alkaida*, *Лукашенко*, *apt 28* – and up to 12 actors appear with picture, kind,
  report count and the alias that matched. With fewer than ten direct matches, the actors named most often in the
  same passages as the best match fill the list (e.g. Wagner Group and Putin for Prigozhin). ↑ ↓ Enter to open one.

<img src="docs/images/actor-search.png" alt="Actor search: a misspelt name finds Prigozhin, followed by the actors most often named with him" width="900">

- Name matching is rule-based and transparent: every name used (or not used, with the reason) is listed, and
  `/actors/names` shows the most frequent matches for review.
- **Precision review** (`/actors/review`): random passages of the names that put the most reports on their actor,
  each marked ✓ right or ✗ wrong; any passage on an actor page can also be marked *✗ not …*. A wrong verdict
  removes that report from the actor at once and on every rebuild; every verdict is kept with its passage as
  evidence in [`sources/actor_reviews.yaml`](sources/actor_reviews.yaml), gives each name a measured precision, and
  the actor page lists the reports left out this way.

<img src="docs/images/review.png" alt="Review actor matches: names by impact with sample passages to mark right or wrong" width="900">

### 🕸️ Network

<img src="docs/images/network.png" alt="Network: clusters of actors named together, with ties, main topics, timeline and reporting agencies" width="900">

Which actors the reports name **together more often than their frequency predicts** – not just most often:

- **Clusters** of strongly associated actors (e.g. *Wagner Group · Prigozhin · Internet Research Agency*,
  *Fancy Bear · Cozy Bear · Turla · Ghostwriter*, *LockBit · Conti · Akira*), each as a card with its members,
  strongest ties, the main topics of its reports, a timeline and the agencies that report on it.
- **Association matrix** of all actors, ordered by cluster: each cell is a pair named in the same passage, shaded
  by association strength (normalised pointwise mutual information); clusters appear as blocks.
- **Details panel**: an actor's most strongly associated and most frequent partners, or a pair's counts against
  what chance would predict.
- Filter by period, reporting coalition, agency type, topic and kind of actor. Every number opens the passages or
  reports it counts.

### 🗺️ Map

<table>
<tr>
<td width="50%"><img src="docs/images/map.png" alt="Dark world map with agency headquarters"></td>
<td width="50%"><img src="docs/images/mentions.png" alt="World map shaded by the share of each country's reports naming China"></td>
</tr>
<tr>
<td><b>Headquarters</b> – every agency on a dark world map, coloured by type, with a hover card.</td>
<td><b>Who reports on whom</b> – the share of each country's reports that name a country, or what one country or coalition reports on.</td>
</tr>
<tr>
<td width="50%"><img src="docs/images/democracy-map.png" alt="World map coloured by V-Dem regime type in 2025, with the library's states listed"></td>
<td width="50%"><img src="docs/images/democracy-change.png" alt="World map coloured by the ten-year change of the Liberal Democracy Index"></td>
</tr>
<tr>
<td><b>Democracy</b> – every country coloured by its regime type, Liberal Democracy Index, its ten-year change, Freedom House
or World Bank score, in any year since 1990 (slider, ▶ plays the years).</td>
<td>The panel counts states per regime in the world and in the library, and ranks the library's states with a trend
line, the change and the number of reports of that year – each count opens its documents.</td>
</tr>
</table>

Countries are recognised by their names and demonyms in the report languages (from Wikidata); a country's own
reports are left out, and selections with fewer than 10 reports are greyed out.

The Headquarters view can also shade countries by today's regime type, and each agency card shows its state's regime
type (V-Dem, latest year), so a report can be read with its state's record in mind. On the Democracy view the library's
sources are dots sized by their reports (think tanks dashed, in their credibility colour); hovering a country shows all
measures of that year with a trend line, and every colour and count names its source and retrieval date.

### 🧠 Topic mind map

<img src="docs/images/mindmap.png" alt="Topic mind map: categories, topics and their most characteristic actors" width="900">

Categories → topics → the actors most characteristic of each topic (counted in the reports that have the topic
among their three main topics), with a details panel and links to every count. Click a category or topic to unfold or
fold it, or use **Expand all**, **Topics** (the default) and **Collapse all**; each column is as wide as its longest
label and long names wrap, so labels never overlap. A filled dot has folded branches; dot size shows the reports.

### 💾 Data exchange – backup and sharing without crawling

*Sources → Data exchange* (`/data`) backs up the whole library or hands it to someone else, who then does not have
to crawl the agencies – and either side can crawl on from there.

<img src="docs/images/data-export.png" alt="Data exchange: an export running with its steps, progress bar, speed, time left and log" width="900">

- **Export** in three steps: *what* – everything, the catalogue only (the receiver downloads the report files from
  the agencies), or the catalogue plus the report files added since a day – each with its size; *where* – a folder
  picker over USB disks (`/media`, `/mnt`) and the home folder, with free space and *new folder*; *options* – the
  largest file (4 GB … 100 MB, 2 GB fits most transfer services) and a label. A meter shows whether it fits.
- The result is a **dataset**: one tar stream cut into files of at most that size plus a manifest – who made it,
  when, with which version, how fresh the data is per source, the SHA-256 of every file. Inside: a consistent copy of
  the database, the report files, logos, the actor gazetteer and the lists the portal keeps.
- **Import**: pick the folder with the dataset's files; datasets found there are listed with their date, origin,
  size and whether all files are present. **Check and compare** verifies every file and compares the dataset with
  the library – newer, older, mixed or complementing (same crawl state, but reports this library lacks), per source
  and per report – without changing anything; then **Import**, choosing whose hand edits win in a conflict.
  An **empty installation** is restored from the dataset; an **existing library** is merged – sources, pages and
  reports matched by key and address (ids differ between installations), missing reports, files, text and OCR
  added, empty years filled, the later crawl dates kept, conflicting hand edits listed. Reports whose file the
  dataset does not carry are marked for download; an older dataset adds nothing; importing twice changes nothing.
- **Progress** for every step (copying and compressing the database, writing, checking, merging, writing files,
  matching topics and actors), with a progress bar, size, speed and time left, the live **log** (kept in
  `data/logs/`), and **Cancel** – an export removes its partial files; an import can be stopped until it starts
  changing the library. Before any change the database is copied to `data/backups/` (the last three are kept).
- The same on the command line: `python -m rozvedka export DIR` / `import DIR [--check]` (see Commands).
- On this Raspberry Pi the full library (3,442 reports, 14.9 GB in 8 files) exports in about 18 minutes and restores
  into a new installation in about 27; checking alone takes about 6. The catalogue only takes about 2 minutes (280 MB).

<img src="docs/images/data-import.png" alt="Data exchange: the result of Check and compare, with the choice whose edits win and the Import button" width="900">

### 🌗 Dark and light theme

Dark by default; the sun/moon button in the header switches to light and back. The choice is remembered in the
browser, and charts redraw in the matching colours. The maps stay dark in both themes.

### ⟳ Update – check the agencies for new reports

Rozvedka looks for new reports only when you start it – there is no schedule. The **⟳ Update** button in the header
of every page shows how old the data is (every source checked since …; amber after a week) and, while an update
runs, its progress; it opens the **Update** page (`/update`):

<img src="docs/images/update.png" alt="Update page: what to do, which sources, the plan with its duration, and every source's last check" width="900">

- **What to do** – a *full update* (check the report pages, download the new reports, improve titles, extract text,
  OCR, dates, topics and actors), *check only* (list new reports without downloading them), or *download the
  waiting reports* (optionally retrying failed ones).
- **Which sources** – all, those not checked for N days, one country, or the ones ticked in the table; the page says
  how many report pages that is and about how long it takes (measured on earlier runs).
- **Progress** – the steps, a bar with the source being checked or the downloads done, time left, the live log (kept in
  `data/logs/`) and the result: new reports per source, with links to *What's new* and the reports added that day.
  **Cancel** stops between pages or downloads; what was found and downloaded so far is kept.
- **Sources** – every source with its report pages' last check, the outcome (fine, error, blocked by robots.txt,
  skipped, collected by hand – each page's status on a click), its reports, the new ones the last check found and those
  waiting for download; filter by outcome, country or name; *Check now* on one source.
- **History** of the checks and downloads, with how long each took.

Crawling is polite: robots.txt is respected and each host gets at most one request every 2 seconds. Long jobs run one
at a time (an update, an export or an import); the indexers run as separate processes.

## Quick start

```bash
git clone https://github.com/iiogurt/Rozvedka.git ~/Documents/Projects/Rozvedka
cd ~/Documents/Projects/Rozvedka
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo apt install poppler-utils chromium      # pdftotext (text extraction), Chromium (JavaScript-only sites)
sudo apt install ocrmypdf tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa …   # optional: OCR for scanned reports

.venv/bin/python -m rozvedka update          # crawl, download, extract and index (first run: hours)
.venv/bin/python -m rozvedka fetch-actors    # reference data for the actor index (a few minutes)
.venv/bin/python -m rozvedka index-actors
.venv/bin/python -m rozvedka serve           # → http://<host>:8080
```

> [!WARNING]
> The portal has no login. It listens on your LAN; do not expose it to the internet.

> [!NOTE]
> `data/` is not in git. It holds the database (`rozvedka.db`), the downloaded PDFs (`files/`, 14+ GB), logos and
> the actor gazetteer. Back it up as a dataset (*Sources → Data exchange*).

### Starting the portal

The portal runs when it is started – it is not set up to start by itself after a reboot, and nothing runs on a
schedule (both the owner's decisions; updates are started on the *Update* page):

```bash
cd ~/Documents/Projects/Rozvedka
nohup .venv/bin/python -m rozvedka serve > data/logs/portal.log 2>&1 &
```

`deploy/rozvedka-web.service` is a systemd user unit for whoever wants the portal managed by systemd
(`systemctl --user link "$PWD/deploy/rozvedka-web.service" && systemctl --user start rozvedka-web`); without
`loginctl enable-linger` it runs only while that user is logged in.

## Commands

`python -m rozvedka <command>` (from the project directory, with `.venv/bin/python`):

| Command | What it does |
|---|---|
| `update [--country CZ]` | crawl → download → improve titles → index topics → OCR → dates → actors (the *Update* page does the same with progress; runs only when started) |
| `sync-registry` | load `sources/registry.yaml` into the database |
| `crawl [--country CZ] [--agency BIS]` | find new documents on the report pages (no download) |
| `download [--country CZ] [--limit N] [--retry-failed]` | download discovered documents |
| `index-topics [--reextract]` | extract text for full-text search and tag topics; re-classifies after `topics.yaml` changes |
| `ocr [--limit N] [--workers 3]` | recognise the text of scanned reports (no text layer) with Tesseract via OCRmyPDF, in the report's language + English; stores the text with page breaks, marks it as OCR, leaves the PDF unchanged (part of `update` when installed) |
| `date-documents [--check]` | give undated reports a year from their first pages – a report heading, else a publication date – with the evidence; `--check` measures accuracy on reports whose year is known (part of `update`) |
| `fetch-actors [--refresh]` | download the actor gazetteer and connections from Wikidata, Wikipedia and MITRE ATT&CK (network; Wikipedia infoboxes are cached in `data/gazetteer/` – `--refresh` reads them again) |
| `fetch-actor-profiles [--refresh]` | pictures (flag, logo or photo, with author and licence), key facts and Wikipedia leads of every actor the reports name, from Wikipedia, Wikidata and Wikimedia Commons (network; part of `fetch-actors`; `--refresh` downloads the pictures again) |
| `index-actors [--rematch]` | find the actors in the report texts (offline) |
| `fetch-logos [--refresh]` | download agency logos from their home pages |
| `improve-titles` | replace poor document titles with the title stored in the PDF |
| `export DIR [--no-files] [--since DATE] [--part-size 2G] [--name LABEL]` | write the whole library as a dataset – parts of at most 2 GB plus a manifest – for backup or to hand to someone else |
| `import PATH [--check] [--prefer local\|dataset] [--no-index]` | verify a dataset, compare it with the library (newer / older / mixed / complementing), then restore it into an empty library or merge it into this one |
| `serve [--host] [--port]` | run the portal (default `0.0.0.0:8080`) |
| `stats` | documents found and downloaded per country |
| `--version` | release version and git build |

Tools in `tools/`: `check_registry.py` (does every registry URL still load), `build_sources_md.py` (regenerate
[`sources/sources.md`](sources/sources.md)), `geocode_hq.py`, `find_variants.py`, `build_events.py` (resolve event
markers against Wikidata), `bump_version.py` (cut a release).

## Configuration

Everything that defines *what* Rozvedka collects and recognises is a hand-editable YAML file in `sources/`:

| File | Contents |
|---|---|
| [`registry.yaml`](sources/registry.yaml) | the agencies: names, type, home page, description, headquarters, report pages (language, current/archive), how to fetch them |
| [`countries.yaml`](sources/countries.yaml) | country names, regions, coalition memberships with year joined |
| [`topics.yaml`](sources/topics.yaml) | topic taxonomy: categories → topics → keywords per language |
| [`actors.yaml`](sources/actors.yaml) | which Wikidata classes, hand-listed seeds and countries make up the actor index, and matching corrections |
| [`series.yaml`](sources/series.yaml) | confirmed report series per source (title stems per language, editions per year, editions confirmed as not published) – written by the portal, editable by hand |
| [`events.yaml`](sources/events.yaml) | reference events for the trend charts (Wikipedia titles; dates are resolved from Wikidata) |

<details>
<summary><b>How sources are fetched</b> (<code>access</code> in the registry)</summary>

| `access` | Behaviour |
|---|---|
| `auto` | plain HTTP fetch |
| `browser-ua` | same, with a curl fallback for servers that reject Python's TLS handshake |
| `tls-lenient` | skip certificate verification (server sends an incomplete chain) |
| `browser-js` | the page is rendered with headless Chromium |
| `manual` | bot-protected; add documents in the portal (Sources → *Add a document by URL*) |

Pages that turn out to be empty JavaScript shells are rendered with Chromium automatically. Report pages marked
`verified: false` are listed but not crawled.

</details>

<details>
<summary><b>Where the year of a report comes from</b></summary>

- From the title or the address of the file when they contain one (most reports).
- Otherwise (`date-documents`), in this order, each with its evidence stored with the report (hover the year):
  1. a Japanese era year in the title (平成29年版 = 2017), a year in a file name passed in the address
     (`…?file=…Spring-2026.pdf`), or a date stamp in the file name (`20260611_report.pdf`, a publication date);
  2. a **report heading** on the first pages – "Annual Report 2023", "Jahresbericht 2022", "za rok 2021",
     "2023年版" (the covered year; a range gives its end year; the cover page counts first);
  3. **the same folder**: at least three other dated reports in the same folder of the site, all from one year –
     unless the report's first page names another year;
  4. a **publication date** – "12 February 2022", "2024. gada 18. jūlijā", "Utgitt av DSB 2025", "© 2024", with
     month names in the library's languages – shown as *≈ 2024* on the Documents page;
  5. the **only year on a title page** (a first page of under 800 characters).

  A blind check on the ~2,400 reports whose year comes from their title (`date-documents --check`): headings 81 %
  exact / 89 % within one year, same folder 100 % / 100 %, publication dates 66 % / 83 %, lone cover year 82 % / 86 %.
  File-name date stamps disagree with those reference years more often, but where checked by hand the stamp was
  right and the reference year wrong (e.g. UK ISC press releases). PDF creation dates were tested and are not used.
- Years set by hand are marked as such and never changed; no year is ever overwritten.

</details>

<details>
<summary><b>How topics are assigned</b></summary>

- Keyword syntax: `word` (whole word), `stem*` (words starting with the stem), `two words` (a phrase; each token may
  end in `*`), Japanese/Chinese/Korean terms as substrings. Case and accents are ignored; every language's terms
  apply to every document.
- A topic is assigned when the title matches, or when at least 2 different keywords occur and the hits keep up with
  the length (≥ 3, and at least one per 15,000 words).
- Text is extracted from the first 150 pages (up to 400,000 characters). After editing `topics.yaml`, run
  `index-topics` again – documents are re-classified from the stored text.

</details>

<details>
<summary><b>How actors are recognised</b></summary>

- **Who is listed:** Wikidata items of the classes in `actors.yaml` (with an English Wikipedia article, not
  dissolved before 2000, no states or companies), items "designated as terrorist by" (P3461), MITRE ATT&CK
  groups (joined to Wikidata through P9025 or a unique shared name), and hand-listed seeds.
- **How mentions are found:** by name – Wikidata labels and aliases in the report languages, ATT&CK aliases,
  hand-added names; case-sensitive, accent-insensitive, headings in capitals included.
- **Rules against false matches** (each shown with its reason on the actor page): ignore lists and per-actor
  exclusions; lowercase, very short and generic one-word names; names shared by several actors; one-word names of
  people other than the surname; generic names and short abbreviations ("FSB", "National Security Council") count
  only together with another name of the actor; the longest of overlapping names wins; reports dated before an
  actor was founded and reports of sources excluded for an actor are not counted.
- **Countries** are actors too (kind *country*): sovereign states from Wikidata with their labels, aliases and
  demonyms ("Russian", "russe"), so the portal can count which countries' reports name which countries. Two-letter
  forms ("UK", "US") count only together with another name.
- **Connections:** Wikipedia infobox fields (leader, founder, key people, parent, subsidiaries, wings, allies,
  opponents, owner; for people: party, branch, unit, employer, organisation) and Wikidata properties (member of
  P463, party P102, employer P108, affiliation P1416, military branch P241, parent P749, part of P361, owned by
  P127, founded by P112, chair P488, director P1037, CEO P169, board P3320). Only links to people and
  organisations are kept; incoming Wikidata links are ranked by notability (Wikipedia language versions) and the
  25 most notable per relation are kept, with the total. Connected people are matched by full name only.
- **Named together:** two actors named within 600 characters in a report are stored as a pair; the network, the
  actor pages and the passage pages (`/actors/<a>/with/<b>`) all count these pairs per report.
- **Correcting it:** `/actors/names` lists the names with the most matches. Add a wrong one under
  `ignore_aliases`, `exclude_aliases`, `weak_aliases` or `exclude_sources` in `actors.yaml` and run
  `index-actors` again.

</details>

<details>
<summary><b>Map data</b></summary>

Headquarters are the publicly listed headquarters or contact addresses (`hq: {address, lat, lon, precision}` in the
registry), geocoded once with OpenStreetMap Nominatim; the portal makes no geocoding calls. Solid pins are exact
buildings, hollow pins street or city level. `/map#s-<id>` zooms to one agency, `/map?tiles=0` works offline.

</details>

## How it works

```mermaid
flowchart LR
    R[sources/*.yaml<br>registry · topics · actors · events] --> C[crawl]
    W[(agency websites)] --> C
    C --> D[download<br>PDF + SHA-256]
    D --> T[index-topics<br>text · pages · topics]
    K[(Wikidata · Wikipedia<br>MITRE ATT&CK)] --> F[fetch-actors<br>gazetteer]
    T --> A[index-actors]
    F --> A
    T & A --> DB[(SQLite + FTS5)]
    DB --> P[portal<br>FastAPI · Jinja · ECharts · Leaflet]
```

| Module | Role |
|---|---|
| `rozvedka/registry.py`, `crawler.py`, `fetch.py` | load the registry, find document links (robots.txt, per-host delay, curl and Chromium fallbacks) |
| `rozvedka/downloader.py` | download, check the PDF header, de-duplicate by SHA-256, improve titles |
| `rozvedka/topics.py` | text extraction with page offsets, FTS5 index, topic classification (all CPU cores) |
| `rozvedka/actor_sources.py`, `actors.py` | build the gazetteer from public reference data; match actors in the texts |
| `rozvedka/trends.py` | the statistics behind the Trends pages, each with the link that reproduces it |
| `rozvedka/graphs.py` | network associations and clusters, who-reports-on-whom and topic mind map data, with the same links |
| `rozvedka/updater.py` | the Update page: plan (pages, duration), the update steps, every source's last check, history |
| `rozvedka/jobs.py`, `progress.py`, `folders.py` | long jobs from the portal (update, export, import): progress, log, cancel, one at a time; the Data exchange folder picker |
| `rozvedka/dataset.py` | datasets: export in parts with a manifest, verify, compare (newer / older), restore or merge |
| `rozvedka/review.py` | precision review of actor matches: the queue, verdicts with evidence, measured precision |
| `rozvedka/watch.py`, `doclist.py` | the watchlist (queries counted update by update); the Documents list's filters as SQL, shared by every count |
| `rozvedka/compare.py` | Compare agencies: per-agency counts and densest passages on one actor or topic |
| `rozvedka/updates.py` | What's new by update and the Atom feed, each count with its link |
| `rozvedka/home.py` | the home page: search-console operators and suggestions, dashboard counts with their links |
| `rozvedka/report.py` | the report page: provenance, series edition and changes, topics with terms, actors with passages |
| `rozvedka/doctypes.py`, `works.py`, `dating.py` | document types; language versions and summaries grouped into one report; years from the text and year conflicts |
| `rozvedka/concepts.py` | cross-language search: concept names in every language from Wikidata |
| `rozvedka/ratings.py`, `publishers.py` | democracy ratings of states over time; think-tank credibility checks (EU register, FARA, sanctions lists) |
| `rozvedka/app.py`, `templates/`, `static/` | the server-rendered portal |

## Database

Everything the portal shows comes from one **SQLite** database, `data/rozvedka.db` (about 600 MB; write-ahead log,
full-text index FTS5). It is a **working copy, not the source of truth**: the hand-written lists in `sources/*.yaml`
(registry, topics, actors, series, think-tank profiles, reviews) and the downloaded files rebuild it – except the edits
made in the portal (a corrected title, language or year, a hidden file, an upload), which live only here and travel in
datasets. Reference data fetched from outside is kept beside it as JSON with its source and date
(`data/gazetteer/*.json` – actors, concepts, think-tank checks; `data/ratings/ratings.json` – democracy ratings).

<details>
<summary><b>How to look at the data</b> – read-only, also while the portal runs</summary>

Open the file **read-only** (the portal keeps writing to it; never change it by hand while the portal runs – use the
portal or the commands):

```bash
# the SQLite shell (sudo apt install sqlite3)
sqlite3 -readonly data/rozvedka.db
sqlite> .tables
sqlite> SELECT s.agency, COUNT(*) FROM documents d JOIN sources s ON s.id = d.source_id
   ...> WHERE d.hidden = 0 GROUP BY s.agency ORDER BY 2 DESC LIMIT 10;

# or Python, without installing anything
.venv/bin/python -c "import sqlite3; c = sqlite3.connect('file:data/rozvedka.db?mode=ro', uri=True); \
  print(c.execute('SELECT COUNT(*) FROM documents').fetchone())"
```

On a desktop, **DB Browser for SQLite** (open read-only) or **Datasette** (`datasette data/rozvedka.db`, a browsable web
view – keep it on your LAN like the portal) work well. To look at the data on another computer, export a *catalogue
only* dataset on *Data exchange* (about 250 MB) and take the database out of it:
`cat rozvedka-dataset-*.tar.* | tar x --occurrence=1 db/rozvedka.db.gz && gunzip db/rozvedka.db.gz` (a few seconds;
the database is the first member).

A few useful queries:

```sql
-- full text: reports whose text mentions "drone" or "Drohne" (FTS5; doc_text.rowid = documents.id)
SELECT d.year, s.agency, d.title FROM doc_text t JOIN documents d ON d.id = t.rowid JOIN sources s ON s.id = d.source_id
WHERE doc_text MATCH '"drone"* OR "drohne"*' ORDER BY d.year DESC LIMIT 20;

-- which agencies name an actor most (actors.key is the Wikidata id or MITRE ATT&CK id)
SELECT s.agency, COUNT(*) reports, SUM(da.hits) mentions FROM doc_actors da JOIN documents d ON d.id = da.doc_id
JOIN sources s ON s.id = d.source_id WHERE da.actor_key = (SELECT key FROM actors WHERE label = 'Wagner Group')
GROUP BY s.agency ORDER BY reports DESC;

-- a report's topics with the terms that matched
SELECT topic, score, terms FROM doc_topics WHERE doc_id = 2964 ORDER BY score DESC;
```

The portal's counts leave out hidden files, non-reports (statements, laws, budget tables, forms) and further language
versions of a report; to count as the portal does, add
`d.hidden = 0 AND d.status NOT IN ('missing','duplicate','skipped') AND (d.doc_type IS NULL OR d.doc_type NOT IN ('statement','legal','finance','form')) AND (d.work_id IS NULL OR d.work_id = d.id)`.
</details>

```mermaid
erDiagram
    sources ||--o{ pages : "report pages crawled"
    sources ||--o{ documents : publishes
    pages ||--o{ documents : "found on"
    documents ||--o| doc_text : "full text (FTS5)"
    documents ||--o| doc_index : "extraction, pages, OCR"
    documents ||--o{ doc_topics : "tagged with"
    documents ||--o{ doc_actors : "names"
    documents ||--o{ actor_pairs : "two actors in one passage"
    documents ||--o| uploads : "added by hand"
    documents ||--o| year_conflicts : "year contradicted"
    documents }o--o| documents : "work_id: same report"
    actors ||--o{ actor_names : "known as"
    actor_names ||--o{ actor_hits : "raw matches"
    actors ||--o{ doc_actors : "mentioned in"
    actors ||--o{ actor_links : "connected to"
    sources {
        int id PK
        text key "country/agency"
        text type "agency type or think-tank"
        text publisher "official or independent"
        real lat "headquarters"
    }
    documents {
        int id PK
        int source_id FK
        text url "official address"
        text title
        text lang
        int year
        text status "new, downloaded, failed"
        text sha256
        text doc_type "annual, assessment … form"
        int work_id "the file counted for its report"
    }
    doc_topics {
        int doc_id FK
        text topic "key in topics.yaml"
        real score
        text terms "terms that matched"
    }
    actors {
        text key PK "Wikidata or ATT&CK id"
        text kind
        text label
        int since_year "founded"
    }
    doc_actors {
        int doc_id FK
        text actor_key FK
        int hits
        text spans "text offsets"
    }
```

| Table | Rows (2026-10-07) | What it holds | Why |
|---|---:|---|---|
| `sources` | 151 | agencies and think tanks from `sources/registry.yaml`: names, type, publisher, home page, headquarters | who publishes; the Sources page, map, filters |
| `pages` | 302 | the report pages crawled per source, language, archive or current, last check and result | what the Update page checks |
| `documents` | 4,196 | every report file found: address, title, language, year (and where it came from), file, SHA-256, type, report it belongs to | the library itself |
| `doc_text` | 3,801 | full text and title of each downloaded report (FTS5 virtual table, `rowid` = document id) | full-text search and passages |
| `doc_index` | 3,801 | extraction details: characters, words, page offsets, OCR, index versions | page numbers, re-indexing only what changed |
| `doc_topics` | 27,714 | topics per report with score, hits and the terms that matched | Topics, Trends, filters |
| `actors` | 5,125 | actors from Wikidata, Wikipedia and MITRE ATT&CK (kind, label, founded, reference data) | the Actors pages |
| `actor_names` | 54,636 | every name and alias of an actor, its languages and whether it is used, with the reason | transparent name matching |
| `actor_hits`, `actor_lower` | 94,611 / 12,704 | raw matches of every name (and of one-word names written in lowercase) | the rules that decide which names count |
| `doc_actors` | 61,659 | actor mentions per report after those rules, with text offsets | actor counts and passages |
| `actor_pairs` | 582,116 | two actors named within one passage | Network, “named together” |
| `actor_links`, `link_entities`, `link_totals` | 7,234 / 4,718 / 945 | connections from Wikipedia infoboxes and Wikidata (leaders, founders, members) with their sources | the Connections section of actor pages |
| `year_conflicts` | 122 | stored years that strong evidence contradicts | the Year conflicts page |
| `uploads`, `collect_checks` | 0 / 0 | provenance of reports added by hand; “checked, nothing new” marks | To collect |
| `runs` | 91 | every crawl, download and update with its summary | the Update page's history and estimates |
| `actor_meta` | 2 | versions of the actor index | rebuilds only when needed |

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python tools/check_links.py      # before a release: home, What's new, Compare and Watchlist counts = their lists; no broken links
```

- **Working rules:** [`CLAUDE.md`](CLAUDE.md) holds the project conventions – scope and source rules, the
  traceability and visualisation principles, git/GitHub workflow, versioning, changelog, README and release
  steps. Claude Code reads it automatically in every session.
- **Roadmap:** [`docs/ROADMAP.md`](docs/ROADMAP.md) – where the project stands, measured gaps, and the
  prioritised next steps.
- **Workflow:** `main` always holds working code. Work on a branch (`feat/…`, `fix/…`, `sources/…`, `docs/…`) and
  merge through a pull request. Registry edits go in their own commits (`sources: add Latvian SAB reports page`).
- **Screenshots:** `python3 tools/screenshots.py [names]` retakes the README pictures from a second portal on port
  8091 (dark theme, 1280 px, agency logos removed); the data-exchange pictures need an export or a check in progress.
- **CI:** GitHub Actions (`.github/workflows/tests.yml`) runs the test suite on every pull request and push to
  `main`; a pull request is merged only when it is green.
- **Never commit** `data/`, `.env` or credentials – `.gitignore` covers them.
- **Versioning:** [Semantic Versioning](https://semver.org) by significance – *patch* for fixes, sources, keywords
  and visual changes; *minor* for new capabilities; *major* for incompatible changes (table in
  [`CHANGELOG.md`](CHANGELOG.md#versioning)). The portal footer, `/api/version` and `--version` show the git build
  between releases (`0.11.0+3.g1a2b3c4`).
- **Releasing:**
  ```bash
  python3 tools/bump_version.py minor      # patch | minor | major; --dry-run to preview
  # commit, open and merge the pull request, then tag the merge commit:
  git switch main && git pull
  git tag -a v<version> -m "Rozvedka <version>" && git push origin v<version>
  ```
  `bump_version.py` updates `rozvedka/__init__.py`, the changelog and the version badge above. GitHub releases
  carry the changelog section as notes; the portal shows the changelog at `/changelog`.

## Data sources and licences

| Component | Source | Licence / terms |
|---|---|---|
| Reports | the agencies' official websites, listed in [`sources/sources.md`](sources/sources.md) | the publishers' terms; downloaded for personal reference, not redistributed |
| Agency logos | the agencies' home pages (`data/logos/`, not committed) | the agencies' marks |
| Flags | [flag-icons](https://github.com/lipis/flag-icons) | MIT ([`LICENSE.flag-icons`](rozvedka/static/flags/LICENSE.flag-icons)); `nato.svg`, `other.svg` drawn for this project |
| Actor reference data | [Wikidata](https://www.wikidata.org) | CC0 |
| Actor summaries | [English Wikipedia](https://en.wikipedia.org) | CC BY-SA 4.0, attributed with article and revision on each page (also in the actor screenshot above) |
| Actor pictures | [Wikimedia Commons](https://commons.wikimedia.org) – the Wikipedia article image or the Wikidata flag / logo / image (`data/gazetteer/actor_images/`, not committed) | free licences only (CC BY, CC BY-SA, public domain …); author, licence and file page shown with each picture |
| Threat groups | [MITRE ATT&CK®](https://attack.mitre.org) | © The MITRE Corporation, reproduced with permission |
| Event dates | Wikidata via `tools/build_events.py` | CC0 |
| Charts | [Apache ECharts](https://echarts.apache.org) 6.1.0, vendored | Apache-2.0 |
| Map | [Leaflet](https://leafletjs.com) 1.9.4, Leaflet.markercluster 1.5.3, [Natural Earth](https://www.naturalearthdata.com) outlines | BSD-2, MIT, public domain |
| Home-page font | [DejaVu Sans Mono](https://dejavu-fonts.github.io), a subset vendored in `rozvedka/static/vendor/fonts/` | Bitstream Vera licence ([`LICENSE-DejaVu.txt`](rozvedka/static/vendor/fonts/LICENSE-DejaVu.txt)); DejaVu changes public domain |
| Street tiles | [OpenStreetMap](https://www.openstreetmap.org/copyright), loaded in the viewer's browser | ODbL, © OpenStreetMap contributors; OSM tile usage policy |

> [!CAUTION]
> **Reading the results.** Topics and actors are recognised by keywords and names, not by understanding: they show
> what reports *talk about*, not what they conclude. More mentions mean more attention, not necessarily a larger
> threat, and agencies publish different kinds of reports at different rhythms. Text of scanned reports comes from
> OCR and can contain misread words (marked *OCR*); years found in a report's text are marked with their evidence.
> Check any surprising number by following its link to the documents and passages.
