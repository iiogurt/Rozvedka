# Rozvedka – assessment and roadmap

Written 2026-10-02 at version 0.16.0. Update this file when an item is done or priorities change; it is the
starting point for every new working session (see `CLAUDE.md` for the working rules).

## 1. Where the project stands

### Built (0.1 → 0.16, 20 merged PRs, 21 tagged releases, 477 tests)

| Area | What exists |
|---|---|
| **Sources** | Registry of 120 agencies in 46 countries/bodies (`sources/registry.yaml`): profiles, original + English names, every language version and archive page, HQ coordinates, coalition memberships; polite crawler (robots.txt, 2 s/host, curl and headless-Chromium fallbacks) |
| **Library** | 3,133 listed reports, 2,937 downloaded PDFs (14 GB), 26 languages; de-duplication by SHA-256; title repair from PDF metadata |
| **Index** | FTS5 full text with page offsets; 64 topics from a 3,800-term multilingual taxonomy; actor index of 5,123 entries (1,500 groups/services, 3,369 people, 189 countries) built from Wikidata, Wikipedia and MITRE ATT&CK, with 7,226 sourced connections |
| **Views** | Documents (search, filters, pager), Sources, Topics + mind map, Trends (topics over time, term trends, who reports on what), Actors (pages with sourced facts, passages with page links, connections, names review), Network (association clusters + matrix), Map (HQs; who reports on whom) |
| **Principles in code** | Every number links to the documents it counts (verified by script before each release); every external fact carries source, revision and retrieval date; matching rules are visible per name; dark/light theme; shared pager |
| **Process** | Branch → PR → merge → significance-based version → tag → GitHub release; `CLAUDE.md`, README in GitHub layout, Keep-a-Changelog |

### Gaps, measured (2026-10-02)

| Gap | Evidence | Why it matters |
|---|---|---|
| **Stale library** | Last crawl 2026-09-30; the weekly systemd timer is not installed (needs `loginctl enable-linger`) | New reports are not collected unless someone runs `update` |
| **Sources with no documents** | 32 of 120 sources have 0 reports – 26 are `manual` (bot-protected): Säpo, PET, LT VSD/AOTD (national threat assessment), ASIO, ASD ACSC, CSIS, NIS (KR), BMI, CCB, CCN-CERT, NBÚ, MV ČR, HZS ČR, DNSC, CNCS, FEMA, DIA, Ukrainian agencies, CENAPRED, SENAPRED, CSIRT Chile, JRC; 6 `auto` sources return nothing (VIGINUM, NCSA GR, NCSC-IE, OEP IE, SRE LU, NCSC-NL) | Several of the most important annual threat assessments are missing |
| **Downloads blocked** | 74 reports are `browser-only` (DIS Italy 38, E-tjenesten 20, StratCom CoE 12, …) | Listed but not readable, not indexed |
| **Undated reports** | 465 visible reports (15 %) have no year | They drop out of every trend, map and network count |
| **No text layer** | 257 reports have < 2,000 characters of text (scanned PDFs) | Invisible to search, topics and actors |
| **Unclassified** | 502 reports carry no topic | Either off-scope, too short, or a taxonomy gap |
| **Matching precision** | ≈ 85–90 % on random samples; fixed by rules + hand exclusions | Errors are visible but still need review |
| **No backup** | `data/` (500 MB database + 14 GB PDFs, gazetteer caches) exists only on the Pi's SD card | One card failure loses months of crawling and curation |
| **No CI** | Tests run only locally | Regressions caught late |

## 2. Strategy

The analysis layer is now richer than the data under it. The next stage should **make the library complete
and current first**, then **turn the analysis into a reading workflow** (what is new, what changed, what do
the agencies say about X), and only then add more enrichment. Every item keeps the non-negotiables from
`CLAUDE.md`: traceability, information-dense views, honest matching, no local LLM.

Order of work: **A → B → C**, with D and E in between when they unblock something.

## 3. Roadmap

Each item: why · what · done when · version step.

### A. Complete and current library (highest priority)

1. ~~Weekly update running~~ – **decided against by the owner (2026-10-02): no periodic job.** Updates run on demand
   (`python -m rozvedka update` or an *Update now* button); views show how old the data is instead.
2. ✅ (0.18.0) **Hand-import workflow for blocked sources** – a *To collect* page listing, per manual or browser-only source,
   the report pages to open and the editions expected but missing; upload of a PDF in the portal (or a
   `data/inbox/<source>/` folder picked up by `update`), with the official URL it came from recorded as its
   source. *Done when* Säpo, PET, VSD, ASIO and CSIS reports are in the library with their official URLs. · minor
3. ✅ (0.17.0) **Report series and missing editions** – model recurring publications (e.g. "BIS Annual Report", one per year,
   cs + en) per source; show gaps ("2019 English edition missing") on the source card and in *To collect*.
   *Done when* each annual-report source shows a complete or explicitly gapped series. · minor
4. **Fix the six silent `auto` sources** (VIGINUM, NCSA, NCSC-IE, OEP, SRE, NCSC-NL) – check pages, patterns,
   JavaScript rendering. · patch (sources)

### B. Data quality

5. ✅ (0.20.0: 463 → 181 undated; 0.22.3: 168 → 90, target met) **Dates for undated reports** – from PDF metadata, the first page ("Annual Report 2023", "Jahresbericht 2022",
   publication dates) and the series model; show where each date came from, keep manual corrections.
   *Done when* undated reports drop from 465 to < 100, with a sampled accuracy check. · minor
6. ✅ (0.21.0: 135 reports recognised) **OCR for scanned reports** – `ocrmypdf`/Tesseract (local, no model downloads beyond language packs) for the
   257 text-less PDFs; mark OCR text as such in the passages. · minor
7. **Editions and translations** – group the same report in several languages (title/year/size/page count),
   so counts are per report, not per file, and passages can switch language. · minor
8. **Document types** – annual report, threat assessment, risk register, strategy, brochure, statistics – from
   titles and series; filter and trend by type (an annual threat assessment weighs differently from a leaflet). · minor
9. **Precision review in the portal** – mark a wrong match on a passage ("not this actor"), stored as a hand
   exclusion with the passage as evidence; review queue sorted by impact. · minor

### C. Reading workflow – "what is new, what changed"

10. ◐ (0.22.0: the home page shows newest editions, reports added in the last 7/30/90 days, rising topics and the
    most named actors, with a search console; still open: per-crawl first-time mentions and the Atom feed)
    **What's new** – per crawl: new reports with their main topics and actors, first-time mentions of actors,
    topics whose share jumped; Atom feed from the portal (no external service). · minor
11. **Watchlist** – follow actors, topics or search terms; the start page shows new passages for them since the
    last visit; saved searches. · minor
12. **Compare agencies on one question** – pick a topic or actor and a year: one column per agency with its
    passages side by side (what BfV, AIVD, KAPO and NCTV say about the same thing). · minor
13. **Research notes and citations** – bookmark passages with a note; export a notebook as Markdown/PDF with
    formatted citations (agency, title, year, page, official URL). · minor
14. **Actor timeline** – first and last mention per agency, mentions per year by reporting country, connected
    actors over time. · minor (extends actor pages)

### D. Enrichment (sourced, public)

15. **Sanctions and designations** – EU consolidated sanctions list, UK sanctions list, UN consolidated list,
    US OFAC SDN (official XML/CSV): designations with legal reference and date on actor pages; designated
    persons and entities matched like connected people. · minor
16. **Positions held** (Wikidata P39 with dates): "Director of the FSB 2008–", head of party, minister – so a
    passage naming a person shows the office they held in that year. · minor
17. **Organisation charts** – parent/subsidiary/unit trees for services and groups (GRU units 26165, 74455 …),
    built from the connections already stored. · patch/minor
18. **More seeds where reports point** – actors frequently named but not in the index (review list of capitalised
    names near known actors); extend parties, companies, influence campaigns on evidence from the reports. · patch

### E. Engineering and operations (continuous)

19. **Backups** – nightly `sqlite3 .backup` + rsync of `data/` to an external disk or NAS; restore test. · patch
20. **CI** – GitHub Actions running the test suite on every PR (private repo minutes suffice). · patch
21. **Performance** – cache actor and network results per index version; the actor page for large actors and
    `/network` take 1–3 s on the Pi. · patch
22. **Code structure** – split `app.py` routes into modules (documents, actors, trends, maps); a small
    migration helper instead of ad-hoc `ALTER TABLE`s. · patch
23. **Optional remote access** – stays LAN-only by default; if wanted, access through a VPN (WireGuard/Tailscale)
    rather than exposing the portal. · docs

## 4. Suggested next three steps

1. **E19** – the data backed up (updates stay on demand – owner's decision).
2. ✅ **A2 + A3** – hand-import and report series (0.17.0, 0.18.0). Next: collect the blocked flagship reports by hand.
3. ✅ **B5 + B6** – dates and OCR (0.20.0, 0.21.0, 0.22.3): 90 reports left undated (from 465), 135 scanned reports recognised.

After that, C10–C12 turn the portal from an archive into a weekly reading tool.
The home page (0.22.0) is the start of C10 and the natural place for C11's watchlist.
