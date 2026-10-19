# Timeline of events: design (roadmap H1)

The owner asked on 2026-10-19 for a graphical timeline of important events that:
- works full screen on large high-resolution screens;
- shows chains of events (what caused or followed what);
- is joined to the reports and subjects already in the library.

This note covers what exists, the data that can support it, and how to build it. It is research for the
roadmap; nothing has been built yet.

## 1. What exists already

| Piece | What it holds | Where |
|---|---|---|
| Reference events | 19 hand-picked events (9/11 … Crocus City Hall), drawn as markers on the trend charts. The date comes from Wikidata (P585 / P580 / P571), with links | `sources/events.yaml`, `tools/build_events.py` |
| Dated facts of an actor | founded and dissolved (Wikidata), terrorist designations with a date, sanctions listings, official attributions, threat-level changes, first and last report naming the actor | `rozvedka/actor_events.py` |
| Actor timeline | when each agency first and last named an actor, reports per year by country, actors named beside it | `rozvedka/timeline.py`, `/actors/<key>/timeline` |
| Network | entities and ties with evidence, in layers (sanctions, Wikidata, publishers, reports …) | `rozvedka/ties.py` |
| Reports | year, and sometimes the date, of 4,575 documents, with the actors and topics of each passage | `documents`, `doc_actors`, `passages` |

Roadmap F7 ("annotated actor timeline") is the small version of this, for one actor. H1 replaces it.

## 2. The view

**Form: swimlanes on one time axis.** This is not a free-form graph.
- **Lanes:** one per country, actor or topic. The viewer picks the grouping and the lanes, for example
  "Russia · Ukraine · NATO" or "cyber · terrorism · hybrid".
- **Events:** a point (one day) or a bar (a span, such as a war or a campaign), each with its label.
- **Report strip:** under each lane, a thin band shows how many reports per month name the lane's subject. Each column
  opens that list of documents (traceability).
- **Every label stays visible.** Overlapping items stack in rows instead of overlapping. At a coarse zoom only the
  events above a threshold are drawn: those named by the most reports, or with the most deaths. The view always says
  what it hides ("214 smaller events hidden at this zoom – zoom in").
- **Chains of events:** only relations that a source states (section 3) are drawn, as typed arrows between events.
  Clicking an event highlights its chain (causes upstream, effects downstream, up to n steps) and dims everything else.
  A chain is followed on demand, never drawn as a hairball. A "part of" relation is drawn as a span that contains its
  events (the battles of a war, the attacks of a campaign), not as arrows.
- **Detail panel:** date and its source, participants (links to the actor pages), place, deaths where known, the
  reports that name the event, the chain as a list, and every source URL with its retrieval date.

**Full screen and large screens**
- The Fullscreen API (a button and the key `F`). The layout uses the whole viewport, with no fixed 1280 px width.
- Drawn as SVG, or canvas at `devicePixelRatio`, so lines and text stay sharp on 4K and 8K screens. A "wall" mode
  enlarges the type and line weights for viewing from a distance.
- The whole state (lanes, range, filters, selected event) lives in the URL, so a view can be opened directly on a TV
  or a second screen and kept running.
- Keyboard: arrows pan, `+`/`−` zoom, `Esc` leaves full screen. Dark theme by default, and the colour-blind-safe
  palette already in use.

## 3. Data that can support it (checked 2026-10-19)

| Source | What it adds | Size / coverage | Licence and access | Use? |
|---|---|---|---|---|
| **Wikidata** | Events with date (P585 point in time, P580/P582 start/end), country (P17), place (P276), participants (P710), perpetrator (P8031), deaths (P1120). Chains: has cause / has effect (P828/P1542), immediate cause (P1478/P1536), follows / followed by (P155/P156), part of (P361) | Dated since 2000: 1,733 terrorist attacks (88 with a cause, effect or sequence link), 797 natural disasters (72), 335 riots (41), 95 cyberattacks (4), 70 assassinations (11), 45 sabotage acts (4). The large events are well linked: the full-scale Russo-Ukrainian war has 11 causes and 15 effects | CC0, SPARQL – already used | **Yes** – the core |
| **UCDP** Georeferenced Event Dataset 26.1, Candidate Events 26.0.8 (monthly) | Organised-violence events with date, sides, deaths and coordinates – the war in Ukraine day by day | 1989–2025; candidate events up to the month before | CC BY 4.0; the [downloads](https://ucdp.uu.se/downloads/) are direct CSV files. The API needs a token requested by e-mail (since February 2026) – not needed | **Yes**, for the states in scope (Ukraine; Russia as a side) |
| **EuRepoC** Global Dataset of Cyber Incidents 1.3 | Cyber incidents with start date, initiator, attribution (who attributed, when), targets and target states – fills the gap Wikidata leaves (95 cyberattacks) | 3,416 incidents, 2000–2024 | CC BY-NC 4.0, [Zenodo](https://zenodo.org/records/14965395) (CSV, XLSX) | **Yes** – non-commercial use fits |
| The library's own records | Sanctions listings with their dates (EU, UK, UN), official attributions, threat-level changes, wanted notices, CISA KEV dates, the dates of reports | already on disk | as now | **Yes** – drawn as events of their kind |
| Wikipedia "Timeline of …" lists | Dated entries with links to the event articles (e.g. the timeline of the Russian invasion of Ukraine) | per article | CC BY-SA, through the existing wikitext reader | Later, only for linked entries |
| Hand-written chains | Relations that the sources above lack (for example "sanctions package 14 – response to – …"), each with its evidence URL | as needed | `sources/events.yaml` gets `relations: [{rel, to, evidence}]` | **Yes**, sparingly |
| ACLED, EM-DAT | conflict and disaster events | – | registration required | No (the rule against registration forms) |
| GDELT | events coded by machine from news | – | free | No – too noisy for "nothing inferred" |
| Global Terrorism Database | attacks | – | restricted licence | No |

Chains are sparse: only 4–9 % of dated events carry a stated link. The chain view will therefore be rich for the large
events (Ukraine, Crimea, 7 October, COVID-19) and thin elsewhere. It says so instead of filling the gaps by guessing.
Adding chains by hand, with evidence, is how gaps get filled.

## 4. Joining it to Rozvedka

- **Store:** an `events` table (key = Wikidata QID, or `ucdp:<id>` / `eurepoc:<id>`), plus `event_actors` (role:
  participant, perpetrator, target, attributed by), `event_countries` and `event_links` (rel, to, evidence). The command
  `python -m rozvedka fetch-events` reads the in-scope classes from Wikidata, UCDP and EuRepoC. Like
  `fetch-actors`, it runs on demand, not on a schedule.
- **Subjects:** participant and perpetrator QIDs are matched to the gazetteer actors, as the network does already.
  UCDP and EuRepoC actor names go through the same alias matching, with the reasons shown when a name is not used.
- **Reports, two ways, kept apart:**
  1. *Names the event:* its names and aliases in every language become gazetteer entries of kind "event". The
     existing `index-actors` then finds them in passages, and precision is measured on samples as for other names.
     These are counted as mentions.
  2. *Context:* reports that name the event's actors within ±N months of it. This is shown as "context", labelled as
     such, and never counted as a mention.
- **Network:** events become entities, with ties such as "participant in", "perpetrator of" and "caused" in a new layer
  "events". So "how are X and Y connected?" can pass through an event.
- **Elsewhere:** actor pages, the actor timeline, country pages and topic pages show their events. The trend charts
  keep their markers from `events.yaml`.

## 5. Library

| Option | For | Against |
|---|---|---|
| **vis-timeline 8.5.4** (Apache-2.0 or MIT, released 2026-08) + **timeline-arrows 4.8.0** (MIT) | Lanes (groups), stacking without overlapping labels, zoom and pan, ranges, item templates – most of section 2 ready-made; the plugin draws arrows between items | DOM-based: thousands of items need the zoom threshold (they would anyway); a new vendored library (~600 KB) |
| **ECharts 6.1.0** (already vendored) | No new library; canvas or SVG; dataZoom | Lanes, stacking and arrows written by hand with `custom` series |
| **D3 7.9** (ISC) | Complete freedom | Most code to write and maintain |

**Recommendation:** vis-timeline with timeline-arrows, vendored like Leaflet and ECharts (no CDN). If it is not smooth
with the full event set on a typical browser, fall back to an ECharts `custom` series, which is already in the project.
Decide by measuring with the real data in step H1b.

## 6. Steps

1. **H1a – events store.** `fetch-events` from Wikidata (in-scope classes and countries, since 2000), UCDP and
   EuRepoC, with sources and retrieval dates, and an "Events" list page using the shared pager. · minor
2. **H1b – timeline page.** `/timeline`: lanes, zoom threshold, report strips, detail panel, full screen and wall mode,
   state in the URL. Checked in headless Chromium at 1280 px and 3840 px, in both themes. · minor
3. **H1c – chains.** Typed arrows, chain highlight, "part of" spans, hand-written relations in `events.yaml`. · minor
4. **H1d – joined to reports and subjects.** Event names in the gazetteer with a precision sample, context reports, the
   "events" network layer, events on actor, country and topic pages. · minor
5. Later: dated statements from the book library (see [BOOKS.md](BOOKS.md)), drawn as "according to <book>, p. n".
