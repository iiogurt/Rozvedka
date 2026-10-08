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
| Matching precision | not measured yet – 0 reviews | the review page exists (0.26); the 85–90 % figure is still an estimate |
| Wrong years from titles | known cases (UK ISC press releases dated 2021) | date stamps in file names disagree with stored years |
| Per-file counting | translations and editions count as separate reports | item B2 |
| Portal start after a reboot | **not automatic** – runs from a shell | `deploy/rozvedka-web.service` needs `loginctl enable-linger` (sudo, owner's approval); `deploy/` still ships a weekly update timer the owner declined |
| Code size | `app.py` 1,102 lines, 9,700 lines in total | routes not yet split by area |
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
3. ◐ (0.29.1: NL, BE, PT, HU, HR, SI, IE added; AT, BG, CY, GR, RO, SK still open; 0.42.5: EE, LV added, LT by hand) **National risk assessments and civil protection gaps** – EU states must report a national risk assessment
   summary to the Union Civil Protection Mechanism every three years; most publish one (e.g. NL Rijksbrede
   Risicoanalyse, LT, LV, SK, AT). Fill the 17 countries without a civil-protection source. · patch (sources)
4. ◐ (0.29.1: AT, LV, SE, HR added; 0.42.5: JP; LU, BG and the other non-EU countries still open – CISA publishes its year in review as web pages only, KISA / TWCERT / CERT.br need a closer look) **Cyber gaps** – national CERT / cyber-agency annual reports where they exist; candidates to verify: CERT.at, CERT.LV,
   CERT-SE / NCSC-SE, CERT.hr, CIRCL (LU), NISC / JPCERT (JP), KISA (KR), TWCERT (TW), CISA (US), CERT.br. · patch (sources)
5. **Hand-collect the blocked flagships** (Säpo, PET, ASIO, CSIS, VSD/AOTD …) through *To collect*. *Done when* their
   latest three editions are in the library. · owner + data
6. ✅ (0.42.6: 80 → 24) **Browser-only reports** (80) – try per-site download links (DIS Italy's attachment API, E-tjenesten, StratCom CoE
   pdfjs viewer → the underlying PDF); otherwise keep them as links. 0.42.6: DIS Italy and StratCom CoE solved; the 20 of E-tjenesten (bot challenge) and 4 of Canada (publications.gc.ca archive notice, script-gated) stay links – not circumvented. · patch

### B. Quality you can measure

1. **Measure matching precision** – review the top names on *Actors → Review* (5 passages × the 40 most frequent names);
   publish the measured precision on the Actors page; turn names that are mostly wrong into exclusions. · owner + patch
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
3. **Actor timeline** (old C14) – first and last mention per agency, mentions per year by reporting country, how the
   connected actors changed. · minor
4. ✅ (0.35.0) **Cross-language search** – a word typed in one language also finds its translations where the topic taxonomy knows
   them (`Drohne` → `drone`, `dron`, …), shown as an explained expansion. · minor
5. **Edition diff for a series** – what a new annual report says that the previous one did not (new actors, topics up
   or down, new passages naming watched actors). · minor

### D. Enrichment from other reliable, official information

1. **Sanctions and designations** (old D15) – EU consolidated list, UK, UN Security Council consolidated list, US
   OFAC SDN (official XML/CSV): designations with legal reference and date on actor pages. · minor
2. **UN Security Council monitoring reports** – the Analytical Support and Sanctions Monitoring Team reports on ISIL
   and Al-Qaida (twice a year) and the panels of experts (DPRK, Libya, Yemen …): official, regular, high value for
   terrorism and sanctions evasion. · patch (sources: `OTHER`)
3. **Other international bodies with regular reports** – UNODC (World Drug Report), UNDRR (Global Assessment Report),
   FATF (typologies, mutual evaluations), OSCE, Interpol (global crime trend summaries), WHO (health emergencies),
   IAEA (nuclear security), EUDA/EMCDDA (European Drug Report), Eurojust, CERT-EU (threat landscape). · patch (sources)
4. **Oversight bodies** – parliamentary and independent oversight reports on the services (NL CTIVD, BE Comité R,
   DE PKGr, NO EOS-utvalget, DK TET, UK IPCO): official, and they report what the services do not. · patch (sources)
5. **National security strategies and white papers** – the governments' own strategy documents, linked to their
   agencies; a natural "document type" (B3). · patch (sources)
6. **Official attributions** – government statements attributing cyber attacks or sabotage to a state or group (EU
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

### E. Engineering and operations

1. **The portal starts after a reboot** – install `deploy/rozvedka-web.service` as a user service with
   `loginctl enable-linger <user>` (needs sudo – owner's approval); **remove the weekly update timer from
   `deploy/`** (the owner declined periodic jobs). · patch
2. ✅ (0.31.1) **CI** – GitHub Actions running the tests on every PR. · patch
3. **Split `app.py`** into route modules (documents, actors, trends, maps, data, update) and a small migration helper. · patch
4. **Performance** – cache actor and network results per index version (1–3 s pages); the home page takes ~0.7 s;
   a cross-language search takes ~3 s on the Pi (highlighting ~40 alternatives) against ~1 s as typed. ✅ (0.39.0) the
   topic mind map's data: one query instead of one per topic, ~11 s → ~0.8 s. · patch
5. **Optional remote access** – stays LAN-only; if wanted, through a VPN (WireGuard / Tailscale), never exposed. · docs

### Done since 0.16.0

A2 hand import (0.18), A3 report series (0.17), B5 dates (0.20, 0.22.3: 465 → 90 undated), B6 OCR (0.21), B9
precision review (0.26), C10 What's new + Atom (0.22–0.23), C11 Watchlist (0.25), C12 Compare agencies (0.24), E19
backups and exchange (0.27–0.28), home page and search console (0.22), Update page (0.29).

## 4. Suggested next steps

1. **E1** – the portal survives a reboot (needs the owner's yes for `sudo loginctl enable-linger`).
2. **A1 + A2** – the six silent sources and the six missing member states (sources work, no new code).
3. **A3 + A4** – civil-protection (national risk assessments) and cyber gaps.
4. **B1** – an hour of precision review, so the quality of every actor count is measured, not estimated.
5. Then **B2 / B3** (count per report, by document type) and **C1** (a page per report).

## 5. Scope questions for the owner

- **Wider scope?** Candidates that fit "official and reliable": EU candidate and partner states (Moldova, Georgia,
  Serbia, Bosnia and Herzegovina, Kosovo), Israel, India, South Africa, Uruguay, Costa Rica, Singapore. Each adds
  languages and work; worth it only where agencies publish regular reports.
- **International organisations** (D2–D3) are outside "agencies" but inside "reliable official information" – include?
- ✅ (0.34.0) **Think tanks** – the owner admitted pro-democratic and security think tanks (2026-10-07), always marked
  apart from official agencies. Next candidates: RUSI, SWP, Chatham House, Carnegie (JavaScript lists, try browser
  rendering), deeper archives of the 13 crawled ones.
- **Oversight bodies** (D4) – include as their own agency type?
