# Country ratings beyond democracy: design (roadmap H3)

The owner asked on 2026-10-19 to extend the country democracy ratings to other ratings, such as security.

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
| **Media** | World Press Freedom Index | RSF | 2002–2025 | not stated on RSF's site; the OWID copy ends in 2021 | RSF yearly files | check the terms first |
| **Cyber** | National Cyber Security Index | e-Governance Academy (funded by the Estonian foreign ministry) | 2016– | not stated; "all underlying data public", evidence-based | per-country web pages, no bulk download found | check the terms and robots.txt first |
| | Global Cybersecurity Index 2024 (5 tiers, 194 states) | ITU | 2015–2024 (5 editions) | ITU publication | only in the report PDF | **Yes**, extracted by a tool from the report's annex |
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
4. **H3d – cyber indices and press freedom:** ITU GCI (extracted from the PDF), NCSI and RSF, after the licence checks.
   · patch / minor
