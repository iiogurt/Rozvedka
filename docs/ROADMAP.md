# Rozvedka – assessment and roadmap

Written 2026-10-06 at version 0.29.0 (the previous assessment was made at 0.16.0). Update this file when an item is done
or priorities change; it is the working plan referred to from [`CLAUDE.md`](../CLAUDE.md). Numbers below were measured
on the library that day.

## 1. Where the project stands

### Built (0.1 → 0.29, 39 merged PRs, 564 tests)

| Area | What exists |
|---|---|
| Library | 120 sources in 46 countries and bodies (94 fetched automatically, 26 collected by hand), 3,015 listed reports in 26 languages, 1987–2026; 2,932 downloaded (14.6 GB) |
| Collecting | registry → crawl → download (robots.txt, 2 s per host, curl / Chromium fallbacks); report series with missing editions; *To collect* for blocked sites with provenance; **Update page** with scope, progress, cancel and per-source status (0.29) |
| Text | full text of every PDF, OCR for scanned ones (135 recognised), years from text/address/folder (90 undated left) |
| Index | 64 topics (3,800 multilingual terms), 5,123 actors from Wikidata / Wikipedia / MITRE ATT&CK with connections, rule-based and transparent name matching, precision review in the portal (0.26) |
| Reading | home page with search console and dashboards, What's new by update + Atom feed, Watchlist, Compare agencies, Trends, Actors and pairs, Network, Maps, Topic mind map |
| Operations | datasets for backup and exchange with a GUI (export / check / import, progress, cancel); one job runner for long jobs; release check of every count against its list (`tools/check_links.py`) |

### Gaps, measured (2026-10-06)

| Gap | Size | Notes |
|---|---|---|
| **NATO and EU members without any source** | **6**: Albania, Iceland, Montenegro, North Macedonia, Turkey (NATO), Malta (EU) | in the declared scope (EU27 + NATO) but missing |
| Automatic sources that return nothing | 6: NCSC-NL, VIGINUM, NCSA (GR), SRE (LU), NCSC-IE, OEP (IE) | pages, patterns or JavaScript (old item A4) |
| Agency types not covered per country | civil protection / national risk assessment missing in 17 countries (AT, BE, BG, CY, EE, GR, HR, HU, LT, LV, NL, PT, RO, SI, SK, KR, TW …); cyber in 13 (AT, BG, HR, LU, LV, SE, US, JP, KR, TW, MX, PE, AR, BR …); military intelligence in most (few publish) | each needs a check whether the agency publishes at all |
| Blocked flagship reports | 26 manual sources, e.g. Säpo, PET, ASIO, CSIS, VSD/AOTD | collected by hand on *To collect* (needs the owner) |
| Open in a browser only | 74 (DIS Italy 38, E-tjenesten 20, StratCom CoE 12, Canada 4) | not downloadable automatically |
| Downloaded reports without any topic | 383 of 2,932 (13 %) | taxonomy gaps or non-report files (forms, leaflets) |
| Reports with too little text | 83 | mostly image-only pages OCR could not read |
| Undated reports | 90 | mostly undated leaflets and forms |
| Matching precision | 91.6 % measured on 1,802 passages of the 456 most frequent names (0.46.1; 75 % of the links), shown on the Actors page | names beyond the top 450 are not measured |
| Wrong years from titles | known cases (UK ISC press releases dated 2021) | date stamps in file names disagree with stored years |
| Per-file counting | translations and editions count as separate reports | item B2 |
| Portal start after a reboot | **not automatic** – runs from a shell, by the owner's choice | an optional systemd user service exists and is tested (0.48.0, `python -m rozvedka service install`); the owner keeps it off; starting at boot would need `loginctl enable-linger` (sudo) |
| Code size | `app.py` 28 lines; 13 route modules of 30–150 lines (0.47.2) | – |
| CI | none | tests run only on the Pi |

## 2. Strategy

The library is broad; its weak spots are **completeness inside the declared scope** (6 member states, missing agency
types, silent and blocked sources) and **measured quality** (precision never measured, per-file counting). New reading
features matter less than closing those, so the order is: **A (complete the scope) → B (quality you can measure) →
E1 (the portal survives a reboot) → C/D as useful**, with each item one PR.

## 3. Roadmap

Each item: why · what · done when · version step.

### A. Complete the library within its scope (highest priority)

1. ✅ (0.29.1) **Fix the six silent automatic sources** (NCSC-NL, VIGINUM, NCSA, SRE, NCSC-IE, OEP) – check pages, link patterns,
   JavaScript rendering; mark as manual where nothing can be fetched. *Done when* each has reports or a documented reason. · patch (sources)
2. ✅ (0.29.1: Iceland, Albania, North Macedonia, Türkiye added; Montenegro and Malta publish no regular reports) **The six missing member states** – research the official publishers per slot (civil and military intelligence,
   cyber agency / national CERT, civil protection and national risk assessment, police / counter-terrorism) and add
   those that publish regularly. Starting points to verify (names from memory, not yet checked): Albania – state
   intelligence service, national cyber security authority; Iceland – national police commissioner's risk
   assessments, CERT-IS; Montenegro – national security agency, CIRT.ME; North Macedonia – national security agency,
   MKD-CIRT; Turkey – USOM (national CERT), AFAD (disasters); Malta – Civil Protection Department, CSIRTMalta. Only
   official domains; manual where blocked; record the slots where nothing is published. · patch (sources)
3. ◐ (0.44.1: no regular reports found for BG, CY, GR, RO, SK; AT BMI Sicherheitsbericht added; 0.29.1: NL, BE, PT, HU, HR, SI, IE added; AT, BG, CY, GR, RO, SK still open; 0.42.5: EE, LV added, LT by hand) **National risk assessments and civil protection gaps** – EU states must report a national risk assessment
   summary to the Union Civil Protection Mechanism every three years; most publish one (e.g. NL Rijksbrede
   Risicoanalyse, LT, LV, SK, AT). Fill the 17 countries without a civil-protection source. · patch (sources)
4. ◐ (0.29.1: AT, LV, SE, HR added; 0.42.5: JP; LU, BG and the other non-EU countries still open – CISA publishes its year in review as web pages only, KISA / TWCERT / CERT.br need a closer look) **Cyber gaps** – national CERT / cyber-agency annual reports where they exist; candidates to verify: CERT.at, CERT.LV,
   CERT-SE / NCSC-SE, CERT.hr, CIRCL (LU), NISC / JPCERT (JP), KISA (KR), TWCERT (TW), CISA (US), CERT.br. · patch (sources)
5. **Hand-collect the blocked flagships** (Säpo, PET, ASIO, CSIS, VSD/AOTD …) through *To collect*. *Done when* their
   latest three editions are in the library. · owner + data
6. ✅ (0.42.6: 80 → 24) **Browser-only reports** (80) – try per-site download links (DIS Italy's attachment API, E-tjenesten, StratCom CoE
   pdfjs viewer → the underlying PDF); otherwise keep them as links. 0.42.6: DIS Italy and StratCom CoE solved; the 20 of E-tjenesten (bot challenge) and 4 of Canada (publications.gc.ca archive notice, script-gated) stay links – not circumvented. · patch
7. ✅ (0.68.1, owner's idea) **Cognitive and narrative warfare sources from Small Wars Journal** – the article "Doors of
   Perception" and 118 SWJ posts on information, influence and cognitive warfare (2025-08 – 2026-10, robots.txt crawl delay
   10 s) cite 771 domains. Added: Swedish Psychological Defence Agency (MPF, 9 reports), IRSEM (67), USCC annual reports (61),
   UK DCDC strategic trends (8), RAND (10) and DFRLab (3) as think tanks with funding profiles; NATO STO and ACT by hand
   (bot protection). Already covered: EEAS, VIGINUM, StratCom CoE, Hybrid CoE, ASPI, ISD, CSIS, ISW, Freedom House.
   Candidates noted in the registry: NDU INSS (JavaScript list), CRS, Lund PDRI, Irregular Warfare Initiative, Graphika. · patch (sources)
8. ✅ (0.69.0, owner's decision 2026-10-16) **Commercial analysts** – a third kind of publisher (■), counted and marked apart
   from agencies and think tanks; rated by ownership, clients, authors and method; US federal contracts from USAspending.gov
   for every non-state publisher; owners, sponsors and founders as network links (layer "Publisher profiles"). Sources:
   Eurasia Group, ESET, Graphika, Microsoft MDDR; Allianz Risk Barometer and Munich Re by hand. Next: Swiss Re sigma and
   Recorded Future (pages built by script – try browser rendering), people and methods checks for the 19 think tanks,
   `ties` (boards, major donors) for the think tanks with named donors. · minor

### B. Quality you can measure

1. ✅ (0.42.7: top 40 names, 199 passages, 95.5 %; 0.43.0: names 41–200, 853 more passages, 92.7 % overall, shown on
   the Actors page; rules for the names that were mostly wrong; 0.46.1: names 201–456, 75 % of the links) **Measure matching precision**.
   Later: the remaining ~1,700 names (each under 8 reports) and a re-review of the corrected names. · owner + patch
2. ✅ (0.33.0) **Editions and translations** (old B7) – group the same report across languages and file variants, so counts and
   trends are per report, not per file; passages can switch language. · minor
3. ✅ (0.32.0) **Document types** (old B8) – annual report, threat assessment, risk assessment, strategy, guide/leaflet, form,
   statistics – from titles, series and size; filter and weight by type (a 200-page assessment is not a 2-page form). ·
   minor
4. ✅ (0.32.1: 4.8 %) **Reports without a topic** (383) – sample them: add missing terms to `topics.yaml` (general rule first), mark
   non-reports with their document type (B3). *Done when* below 5 % of real reports. · patch
5. ✅ (0.31.0) **Year conflicts** – list reports whose stored year contradicts strong evidence (file-name date stamp, folder,
   cover year) for review in the portal; never overwrite silently. · minor

### C. Reading workflow

1. ✅ (0.30.0) **Report page** – one page per report: metadata and provenance, series and editions, main topics, actors with
   passages, what changed against the previous edition, open/original links. Today a report is only a row and a PDF. · minor
2. **Research notes and citations** (old C13, adapted to *no user-based features*: one shared notebook) – mark
   passages into named notebooks, export as Markdown / PDF with formatted citations (agency, title, year, page,
   official URL). · minor
3. ✅ (0.46.0) **Actor timeline** (old C14) – first and last mention per agency, mentions per year by reporting country, how the
   connected actors changed. · minor
4. ✅ (0.35.0) **Cross-language search** – a word typed in one language also finds its translations where the topic taxonomy knows
   them (`Drohne` → `drone`, `dron`, …), shown as an explained expansion. · minor
5. ✅ (0.44.0) **Edition diff for a series** – what a new annual report says that the previous one did not (new actors, topics up
   or down, new passages naming watched actors). · minor

### D. Enrichment from other reliable, official information

1. ✅ (0.45.0) **Sanctions and designations** (old D15) – EU consolidated list, UK, UN Security Council consolidated list, US
   OFAC SDN (official XML/CSV): designations with legal reference and date on actor pages. · minor
2. ◐ (0.44.1: listed as a manual source – the reports are UN documents on other domains) **UN Security Council monitoring reports** – the Analytical Support and Sanctions Monitoring Team reports on ISIL
   and Al-Qaida (twice a year) and the panels of experts (DPRK, Libya, Yemen …): official, regular, high value for
   terrorism and sanctions evasion. · patch (sources: `OTHER`)
3. ◐ (0.44.1: UNODC, INTERPOL; FATF, IAEA, EUDA, CERT-EU, Eurojust, UNDRR by hand; OSCE, WHO not added) **Other international bodies with regular reports** – UNODC (World Drug Report), UNDRR (Global Assessment Report),
   FATF (typologies, mutual evaluations), OSCE, Interpol (global crime trend summaries), WHO (health emergencies),
   IAEA (nuclear security), EUDA/EMCDDA (European Drug Report), Eurojust, CERT-EU (threat landscape). · patch (sources)
4. ◐ (0.44.1: DK, NO, UK IPCO, CH, BE; NL CTIVD by hand; DE PKGr, AU IGIS, CA NSIRA not reachable or not reports) **Oversight bodies** – parliamentary and independent oversight reports on the services (NL CTIVD, BE Comité R,
   DE PKGr, NO EOS-utvalget, DK TET, UK IPCO): official, and they report what the services do not. · patch (sources)
5. ◐ (0.44.1: DE, NATO, US DoD; more countries to add) **National security strategies and white papers** – the governments' own strategy documents, linked to their
   agencies; a natural "document type" (B3). · patch (sources)
6e. ✅ (0.53.0) **ATT&CK techniques** – technique numbers named in reports tied to MITRE's catalog (Enterprise, Mobile, ICS), with groups that use them. Next: techniques as a column of the actor pages (needs a proximity rule). · minor
6d. ✅ (0.52.0) **Dated events per actor** – Wikidata dates, sanctions-list entries, attributions, country threat levels and first/last report year on the actor timeline. Next: CVE and incident dates once they are tied to actors beyond nearness. · minor
6c. ✅ (0.51.0) **Citations between reports and agencies** – addresses in the texts resolved against the library; `/citations`, report pages, Documents filter. Next: the names of cited documents (not only addresses), a graph by agency pair. · minor
6b. ✅ (0.50.0) **Terrorism threat levels** – dated official statements per state with passage (UK MI5 announcements; levels stated in NL, BE, ES, AT, SE, LV reports). Next: more states (FI, DK, FR, CH), the NCTV quarterly levels. · minor
6a. ✅ (0.49.0) **CVE numbers and the Known Exploited list** – CVEs named in reports linked to CISA's KEV catalog (CC0), on actor, report and CVE pages. · minor
6. ◐ (0.47.0: UK NCSC and US CISA, 21 statements; the Council of the EU, Germany and others block or are not yet listed) **Official attributions** – government statements attributing cyber attacks or sabotage to a state or group (EU
   Council, Five Eyes joint advisories), as dated events on actor pages. · minor
7. **Positions held** (old D16), **organisation charts** (old D17), **more seeds where reports point** (old D18). · minor / patch

8. ✅ (0.36.0) **Democracy ratings of states over time** – V-Dem, Freedom House, World Bank WGI per country and year; on
   report pages the ratings of the report's year. ✅ (0.38.0) Democracy map: shading by rating and year, regime shading
   and regime on the agency cards of the Headquarters map. Next: filter reports by the regime type of their state in
   their year.
9. ✅ (0.37.0) **Think-tank credibility profiles** – evidence checklist instead of a score, see
   [`PUBLISHER_PROFILES.md`](PUBLISHER_PROFILES.md); badge coloured by the rating, a profile page per think tank. Next:
   re-check the hand-researched funding evidence yearly; people & methods check.
10. ✅ (0.40.0) **Actor profiles** – picture (flag, logo or photo, free licences only, with author and licence), key
    Wikidata facts and the Wikipedia lead on every actor page (`fetch-actor-profiles`). ✅ (0.41.0) actor search with
    suggestions: aliases in every language, misspellings forgiven, related actors to fill the list. Next: a non-free
    logo is skipped (e.g. Wagner) – an official emblem from the group's own register entry could fill such gaps.

### F. Menu, design and visualisation (from the Opus 5.5 review of 0.53.0)

The owner chose the "Console" redesign (dark, dense, green/yellow accents) from three mockups on 2026-10-13. Its steps:
C1 ✅ (0.56.0) theme, fonts, side rail, command bar · C2 ✅ (0.57.0) overview as a panel grid with a key-number strip · C3 ✅ (0.58.0) actor page with the
combined timeline · C4 ✅ (0.58.1) the other pages in the panel style.


1. ✅ (0.54.0) **Menu in six groups, section tabs, phone menu, `/views`, header search** (`rozvedka/nav.py`, test that no page is missing). · minor
2. ◐ (0.54.0: map pages follow the theme, matrix legend, network mark, phone overflow) **Visual fixes** – aligned bars on `/actors` done in 0.58.1. · patch
3. ✅ (0.82.1) **Page header component** – every page has its `<h1>`; pages below a menu entry (a report, an actor, an edition, a
   book's statements) show a breadcrumb back to their list instead of hand-written "← back" links; the long method notes of 16 pages
   are folded under "How this is counted" (or "How to read it", "What a verdict does") with a one-line summary on top, while
   cautions ("a match is a name match, not an identification") stay visible. · patch
4. ✅ (0.56.0: spacing and type scale, chart palettes read through `rzTokens`, Lucide icon sprite; 0.82.1: the maps) **Design
   tokens** – agency-type, credibility, regime and rating-ramp colours, outlines and shading are CSS tokens for both themes; the three
   maps read them and redraw when the theme is switched, so pins match their legend and the light theme no longer shows dark-theme
   outlines and no-data fills. A test keeps hex colours out of the map scripts. · patch
5. **Overview dashboard** – sparkline tiles instead of the 30/90-day tiles, official/think-tank stacked years, dumbbell for rising topics. · minor
6. ✅ (0.59.0) **Topic matrix** – a reference column of all reports and an over-emphasis (lift) mode. · minor
7. → H1 **Annotated actor timeline** – dated events and the country grid on one year axis; covered by the timeline of events (H1). · minor
8. ✅ (0.60.0) **Threat-level small multiples** – one step chart per state on its own scale. · minor
9. ◐ (0.61.0: chord diagram between agency types) **Citations** – still open: an agency × agency matrix. · minor
10. **ATT&CK tactic grid and CVE lag plot.** · minor
11. **Coverage overview grid and a country × agency-type gap matrix.** · minor
12. ✅ (0.88.0) **Topic and country briefing pages** – `/topics/{key}` and `/countries/{code}`: reports by year (official apart),
    countries, agencies, emphasised actors and topics (lift × reports), who reports about a state, its ratings and events; every
    number opens its list (checked by `tools/check_links.py`). Found on the way: Czechia is not a country actor of the gazetteer,
    so "who reports about Czechia" is empty – to fix with the next `fetch-actors --refresh`. · minor

### G. Networks of groups and people (owner's decision 2026-10-14: everything, no mockups)

Measured at 0.61.0: 85 % of actor mentions are countries; the people the reports name are heads of state, not operatives;
co-mentions find the obvious pairs (Islamic State–Al-Qaeda, MI5–GCHQ). The links that are not obvious are in sources the
reports do not contain – starting with the sanctions lists already on disk (9,168 OFAC “Linked To” remarks, 5,472 UK
statements of reasons, shared addresses and identifiers). Approved sources include the non-official ones (company registries,
ICIJ Offshore Leaks), always marked as such and loaded only for names already in the network.

1. ✅ (0.62.0) **Connection graph** – `entities` + `ties` with layer and evidence: OFAC “Linked To”, UK/UN/EU listing
   narratives (sentence matching, 37/40 and 38/40 right in two hand-read samples, rules from the misses), Wikidata,
   Wikipedia, ATT&CK software and campaigns, co-mentions ≥ 2 reports; `/graph`, `/graph/ties`, `/entity/…`, a Network
   section on actor pages. Next: entries of different lists merged (G3). · minor
2. ✅ (0.63.0) **“How are X and Y connected?”** – `/graph/path`: up to five chains, hub-penalised (½ per doubling of an
   intermediate's links, +1.5 for common tools), alternatives on other routes, layers and countries selectable, evidence per
   step, co-mention-only steps flagged. Measured: 9,526 of 18,761 entities are in one connected part; sanctions-list clusters
   (e.g. 176 companies around one trader) stand apart until entries are merged across lists – G3 is next. · minor
3. ✅ (0.64.0) **Shared identifiers and one target across lists** – 11,155 entries → 4,393 targets (UN references, IMO /
   passport / ID / registration / tax numbers with a shared name word, same name + date of birth; one entry per list; 35 merges
   read by hand, none wrong); shared addresses, e-mails, websites, phones, wallets as entities (2,946 links); UK parents,
   subsidiaries, ship owners by name. Still open: Wikidata people merged with list entries (by date of birth), MMSI, directors
   from company registries (G9); the largest connected part grew only from 9,526 to 11,150 entities – most list clusters link
   to the actors only through people the reports never name. · minor
4. ✅ (0.65.0) **Vendor names and toolkit twins** – MISP galaxy: 176 groups tied, their distinctive names added to the
   matching (measured: 92 matches through names only MISP gives, 15 sampled all right; few new mentions overall – the
   reports mostly use the common names; one conflict found and ruled out:
   MISP's "APT38" under Lazarus), "similar/overlaps" as a layer; `/graph/twins` by IDF-weighted overlap of techniques and
   software (CVEs shown, not scored). · minor
5. ✅ (0.66.0) **Leads and brokers** – 613 leads (Adamic–Adar on the stated network; hubs over 200 links, shared software and
   shared rivals excluded after looking at the first results – shared tools and shared enemies inflated cyber and cartel pairs),
   review kept in `sources/lead_reviews.yaml`; brokers by the kinds of actor their links reach. Next: let confirmed leads feed
   back (a reviewed-confirmed lead as a link of its own, with the note as evidence). · minor
5b. ✅ (0.67.0, owner's idea) **Links from Wikipedia article text** – 12,735 sentence links from 843 articles; the subject is
   certain (a wiki link), the relation word only a hint (25/40 right in a hand-read sample, even after requiring the word to
   stand near the link – a keyword cannot read a sentence). The largest connected part grew from 11,150 to 12,559 entities;
   leads grew from 613 to 5,961 (the strongest now substantive: bin Laden – ISI, Hekmatyar – Al-Qaeda). Next: Wikidata family
   and position statements for people; articles of the connected people, not only of actors in the reports. · minor
6. ✅ (0.68.0) **Official sources on people: wanted notices** – 352 FBI and 24 Europe's Most Wanted notices about security
   (never victims or missing persons, no photos), merged with sanctions entries by name + full date of birth (109) and with
   gazetteer people (12); 571 links read with the narrative rules and the reports' actor matching; notices about several
   people as case nodes. Four hand-read samples of 40 drove the rules (no name across a comma, a name inside a longer group name
   not counted, "Saudi Hizballah" is not Hezbollah, relation words only near the name, "son" in lowercase only); the last: 40/40
   right subject, 24/27 hints right. Fixed on the way: "People's Liberation Army" (73 reports) was the Manipur group; "KGB",
   "ARC" now need context. Rewards for Justice excluded (robots.txt). Next: **6b** US Justice Department press releases (API
   searches titles only, 10 s per request – search the titles for the actors' names, read the sentences naming known people);
   a gazetteer actor for "Saudi Hizballah" (Hezbollah Al-Hejaz). · minor
7. ◐ (0.83.0: G7a – rings around one entity, `/graph/rings`: 40 direct links and 48 at two steps drawn, a sector per layer,
   every count opening the full list; 0.84.0: G7b – the neighbourhood matrix ordered by Louvain communities, "links that connect"
   by default) **Views** – still open: links on a time axis and the network as of a year. Only 9,300 of 42,500 links carry a
   date (UK, UN, EU, wanted notices, events, co-mentions, part of Wikidata; none from OFAC, Wikipedia or shared details), so such a
   view must show the undated links apart. BioFabric dropped: the matrix answers the same question for these sizes. The owner
   chose the case file first (2026-10-21); the year view waits until more sources carry dates. · minor
8. ✅ (0.85.0) **Case file** – one shared board (no per-user state): pin entities, chains between them found automatically, export
   with citations. Kept in `data/case_file.yaml` (personal: never committed, only in personal backups); connectors on several
   chains; Find a connection now uses links that connect by default. · minor
9. ◐ (0.86.0: G9a – GLEIF: 565 of 16,318 list companies matched by LEI, register number or distinctive name – samples 39/40 and
   40/40 – with 255 ownership links one step out) **Company registries and leaks** – 0.87.0: G9b – ICIJ Offshore Leaks, marked as
   leaked records: 57 companies by distinctive name and country, 35 people by rare name and country waiting for the owner's
   confirmation on /graph/offshore, 650 links one step out) still open: UK Companies House (persons with significant control –
   needs an API key the owner registers for). · minor

### H. Timeline, books and country ratings (owner's topics, 2026-10-19 – researched, not started)

1. ✅ (0.71.0: H1a – events from Wikidata, EuRepoC and UCDP, `/events`; 0.72.0: H1b – `/timeline`, full screen and wall mode; 0.73.0: H1c – chains; 0.74.0: H1d – reports naming an event, 96.7 % precision) **Timeline of events with chains** ([design](TIMELINE.md)) – swimlanes on one time axis, full screen and a wall mode
   for large screens, sharp at 4K; typed arrows only for stated relations (Wikidata cause / effect / follows / part of,
   hand-written chains with evidence), a clicked event highlights its chain. Data: Wikidata events (CC0), UCDP GED
   (CC BY 4.0), EuRepoC cyber incidents (CC BY-NC 4.0), the library's own dated records. Joined to reports by event names
   in the gazetteer (counted) and by actors within a time window (context, not counted); events become a network layer.
   Library: vis-timeline + timeline-arrows (vendored), ECharts as the fallback. Replaces F7. Steps H1a–H1d. · 4 × minor
2. ✅ (0.75.0: H2a – `import-books`, `/books`, metadata from books.yaml / Open Library / the file; 0.76.0: H2b – chapters, printed pages, the book's index; 0.77.0: H2c – terms, key sentences, dated statements, relations; 0.78.0: H2d – books on the timeline) **Local book library** ([what it would take](BOOKS.md)) – about 100 PDFs (EPUB cheaper) in `data/books/`, never committed:
   metadata by ISBN (Open Library, Wikidata), authors and publishers as subjects, chapters, printed page numbers, the
   book's own index; actors, topics and search as for reports, a fourth kind "book" marked apart. Meanings without a
   language model: distinctive terms, key sentences quoted with page, dated statements (→ timeline), stated relations
   with the sentence as evidence. About +20 % of the indexed words; OCR is the slow part if the books are scans.
   Steps H2a–H2d. · 4 × minor
3. ✅ (0.70.0: H3a – five WGI dimensions, homicides, military spending, CPI, a page per state, the ratings map; 0.79.0: H3b – UCDP conflict deaths, EuRepoC cyber incidents; 0.80.0: H3c – INFORM, WorldRiskIndex; 0.81.0: H3d – RSF since 2022, ITU GCI 2024 tiers; NCSI not used – its terms prohibit reproduction) **Country ratings beyond democracy** ([design](COUNTRY_RATINGS.md)) – groups Security (WGI political stability,
   UNODC homicides, UCDP conflict deaths, SIPRI military spending, threat levels), Governance (WGI rule of law,
   corruption, effectiveness, regulatory quality; TI CPI), Media (RSF), Cyber (ITU GCI, NCSI, EuRepoC incidents) and
   Disaster risk (INFORM, WorldRiskIndex, ND-GAIN); small multiples per country, a measure switch on the map, no
   composite score. Left out: IEP's Global Peace and Terrorism indices (request form only). Steps H3a–H3d; H3a needs
   only configuration. · minor

### E. Engineering and operations

1. ✅ (0.48.0: optional, tested, **not activated** – the owner does not want it) **The portal starts after a reboot** – install `deploy/rozvedka-web.service` as a user service with
   `loginctl enable-linger <user>` (needs sudo – owner's approval); **remove the weekly update timer from
   `deploy/`** (the owner declined periodic jobs). · patch
2. ✅ (0.31.1) **CI** – GitHub Actions running the tests on every PR. · patch
3. ✅ (0.47.2) **Split `app.py`** into route modules – `rozvedka/routes/` (13 areas) and `rozvedka/web.py` (shared); a migration helper is still open. · patch
4. **Performance** – cache actor and network results per index version (1–3 s pages); the home page takes ~0.7 s;
   (0.47.1: Actors page, actor pages and home page now 0.1–0.3 s on repeat visits) a cross-language search takes ~3 s on the Pi (highlighting ~40 alternatives) against ~1 s as typed. ✅ (0.39.0) the
   topic mind map's data: one query instead of one per topic, ~11 s → ~0.8 s. · patch
5. **Optional remote access** – stays LAN-only; if wanted, through a VPN (WireGuard / Tailscale), never exposed. · docs

### Done since 0.16.0

A2 hand import (0.18), A3 report series (0.17), B5 dates (0.20, 0.22.3: 465 → 90 undated), B6 OCR (0.21), B9
precision review (0.26), C10 What's new + Atom (0.22–0.23), C11 Watchlist (0.25), C12 Compare agencies (0.24), E19
backups and exchange (0.27–0.28), home page and search console (0.22), Update page (0.29).

## 4. Suggested next steps

Updated 2026-10-21, after H (all of it built by 0.81.0) and F3 + F4 (0.82.1):

1. **G7 → G8 → G9** – finish the network plan the owner approved: views (rings ✅ 0.83.0, matrix ✅ 0.84.0; the network as
   of a year waits for more dated links), the shared case file ✅ 0.85.0, then company registries and leaks (GLEIF, UK Companies House, ICIJ).
2. ✅ **F12** – topic and country briefing pages (0.88.0).
3. **F5, F9–F11** – overview sparklines, the agency × agency citation matrix, the ATT&CK tactic grid, the coverage gap matrix.
4. **A3–A5, D2–D7** – more sources (no new code); A5 needs the owner to collect the blocked flagships by hand.

Done from the earlier list: E1 (0.48.0, off by the owner's decision), A1 + A2 (0.29.1), B1 (0.46.1), B2 / B3 (0.32–0.33),
C1 (0.30.0).

## 5. Scope questions for the owner

- ✅ **Books (H2)** – answered 2026-10-19: English, a mix of PDF and EPUB; a trained parser (spaCy) may be used for
  who-did-what extraction (still no LLM, no embeddings).
- ✅ **Ratings (H3)** – answered 2026-10-19: non-commercial and no-derivatives licences are fine for personal use.
  Order agreed: H3a → H1 → H2.

- **Wider scope?** Candidates that fit "official and reliable": EU candidate and partner states (Moldova, Georgia,
  Serbia, Bosnia and Herzegovina, Kosovo), Israel, India, South Africa, Uruguay, Costa Rica, Singapore. Each adds
  languages and work; worth it only where agencies publish regular reports.
- **International organisations** (D2–D3) are outside "agencies" but inside "reliable official information" – include?
- ✅ (0.34.0) **Think tanks** – the owner admitted pro-democratic and security think tanks (2026-10-07), always marked
  apart from official agencies. Next candidates: RUSI, SWP, Chatham House, Carnegie (JavaScript lists, try browser
  rendering), deeper archives of the 13 crawled ones.
- **Oversight bodies** (D4) – include as their own agency type?
