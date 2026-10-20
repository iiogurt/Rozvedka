# Country ratings beyond democracy: design (roadmap H3)

The owner asked on 2026-10-19 to extend the country democracy ratings to other ratings, such as security.

**Status:** H3a built in 0.70.0 (`/ratings?group=security|governance`, `/ratings/<country>`, the ratings map); H3b (UCDP conflict deaths per 100,000, EuRepoC cyber incidents, a Cyber group) built in 0.79.0; H3c (INFORM Risk Index via its API, WorldRiskIndex; ND-GAIN not used – bot-protected download) in 0.80.0; H3d (RSF World Press Freedom Index since its 2022 method, kept locally; ITU GCI 2024 tiers read from the report's annex; NCSI not used – its terms prohibit reproduction) in 0.81.0. The owner confirmed on 2026-10-19 that non-commercial and no-derivatives licences are fine for this personal library.

## 1. What exists

`rozvedka/ratings.py` reads four measures per country and year, each with its source, licence and retrieval date:
- V-Dem Liberal Democracy Index and Regimes of the World;
- the Freedom House score;
- WGI Voice and Accountability.

They come from [Our World in Data](https://ourworldindata.org/) chart files and the World Bank API. They are shown on
`/ratings`, on the democracy map, and as "the state it works in" on agency and publisher pages. Measures are listed in
one table (`MEASURES`), so a new measure from the same two services is a configuration entry plus tests.

## 2. Candidates (checked 2026-10-19)

| Group | Measure | Source | Years | Licence | Access | Verdict |
|---|---|---|---|---|---|---|
| **Security** | Political Stability and Absence of Violence/Terrorism | World Bank WGI (`GOV_WGI_PV.EST`) | 1996–2025 | CC BY 4.0 | the World Bank API already used | **Yes** – configuration only |
| | Intentional homicides per 100,000 | UNODC via OWID (`homicide-rate-unodc`) | 1990–2024 | as published by OWID | OWID, already used | **Yes** |
| | Deaths in organised violence | UCDP country-year 26.1 | 1989–2025 | CC BY 4.0 | direct CSV (the API needs a token, not needed) | **Yes** – shared with the timeline (H1) |
| | Military expenditure, % of GDP | SIPRI via OWID (`military-spending-as-a-share-of-gdp-sipri`) | 1949–2025 | as published by OWID | OWID | **Yes**. For NATO members, NATO's own "Defence expenditure of NATO countries (2014–2025)" is the official figure – later |
| | Terrorism threat level | the states' own announcements | as published | – | already in Rozvedka (`threat_levels.yaml`) | shown beside |
| | Global Peace Index, Global Terrorism Index | IEP | 2008– | CC BY-NC-SA 4.0 | only through a request form | **No** – the rule against forms |
| | Global Organized Crime Index | GI-TOC | 2019, 2021, 2023, 2025 | not stated | web and PDF | check the terms first |
| **Governance** | Rule of Law, Control of Corruption, Government Effectiveness, Regulatory Quality | World Bank WGI (`GOV_WGI_RL/CC/GE/RQ.EST`) | 1996–2025 | CC BY 4.0 | World Bank API | **Yes** – configuration only |
| | Corruption Perceptions Index | Transparency International (OWID copy for 2012–2024; 2025 from TI) | 2012–2025 | CC BY-ND 4.0 – shown unaltered | OWID / TI results file | **Yes** |
| **Media** | World Press Freedom Index | RSF | 2022–2026 (the method changed in 2022; earlier scores not comparable) | © RSF – the legal notice asks for written permission to reproduce | RSF yearly CSV files | **Yes, locally only** – shown in this private library with a link to RSF, not redistributed (the ratings file is not in datasets) |
| **Cyber** | National Cyber Security Index | e-Governance Academy (funded by the Estonian foreign ministry) | 2016– | the site's terms: "reproduction is prohibited other than in accordance with the copyright notice" | per-country web pages, no bulk download | **No** – the terms prohibit reproduction |
| | Global Cybersecurity Index 2024 (5 tiers, 194 states) | ITU | 2024 (earlier editions ranked by another method) | CC BY-NC-SA 3.0 IGO | only in the report PDF | **Yes** – `fetch-ratings` reads the annex "Tier performance: Global" (pp. 24–25); 194 states, all matched |
| | Cyber incidents with targets in the state | EuRepoC 1.3 | 2000–2024 | CC BY-NC 4.0 | Zenodo CSV | **Yes** – a count, shared with H1 |
| **Disaster risk** | INFORM Risk Index | EU JRC | yearly | not stated on the page (Commission reuse policy, normally CC BY 4.0) | JSON API | **Yes** after confirming the licence |
| | WorldRiskIndex | Bündnis Entwicklung Hilft / IFHV | yearly | CC BY (per HDX) | HDX / weltrisikobericht.de | **Yes** |
| | ND-GAIN (vulnerability and readiness) | University of Notre Dame | 1995– | CC BY per catalogues | CSV archive; the download page asks for a questionnaire | **Yes** if the questionnaire is optional |

Left out on purpose: Global Firepower (no published method) and the Global Health Security Index (last edition 2021).

## 3. Design

- **Groups on `/ratings`:** Democracy · Security · Governance · Media · Cyber · Disaster risk, each listing its
  measures with source, licence, years and direction ("higher = safer" is stated for every measure, and the colour
  scales follow it).
- **Country card:** small multiples, one sparkline per measure on its own scale, with the latest value, its year and
  the state's rank among the states in scope. Every value links to the source page for that country.
- **Map:** a measure switch on the democracy map, which becomes "country ratings".
- **No composite score.** Each measure keeps its own scale and source, as for publishers: a mixed index would be
  invented precision.
- **Joined to reports:** beside each security measure, the reports from and about that state on the matching topic
  (homicide ↔ organised crime, conflict deaths ↔ armed conflict). These are links, not a correlation.
- The data age is shown per measure, and a refresh (`fetch-actors --refresh` or `fetch-ratings`) runs on demand, as
  now.

## 4. Steps

1. **H3a – the easy half:** the five WGI dimensions, homicides, SIPRI military spending and CPI. These are configuration
   entries in `MEASURES`, the groups on `/ratings`, and the country card. · minor
2. **H3b – conflict and cyber counts:** UCDP deaths and EuRepoC incidents per state (they share the loader with H1a).
   · minor
3. **H3c – disaster risk:** INFORM, WorldRiskIndex and ND-GAIN, after the licence checks. · minor
4. ✅ **H3d – cyber indices and press freedom:** ITU GCI (extracted from the PDF) and RSF; NCSI not used. · minor
