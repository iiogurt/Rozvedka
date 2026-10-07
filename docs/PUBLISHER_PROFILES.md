# Think tanks: how to show whether a publisher can be trusted

Design accepted by the owner and implemented in 0.37.0 (2026-10-07): `rozvedka/publishers.py`, `sources/publishers.yaml`,
`/publishers` and `/publisher/<id>`. Not yet built: the "people and methods" check. Context: the library includes independent think tanks (0.34.0). Some "think tanks"
are created to influence politics and public opinion for a state or an interest group, so every independent publisher
needs a visible, checkable profile.

## 1. What exists already (research, 2026-10-07)

| Ranking | What it measures | Status | Usable? |
|---|---|---|---|
| [Global Go To Think Tank Index](https://en.wikipedia.org/wiki/Think_Tanks_and_Civil_Societies_Program) (University of Pennsylvania) | Reputation survey among experts and think tanks themselves | Last edition 2020; programme dissolved 2021; methodology widely criticised (duplicates, no data behind the ranks) | No – stale, and popularity is not trustworthiness |
| [Transparify](https://en.wikipedia.org/wiki/Transparify) | Funding transparency, 0–5 stars: are donors, amounts and funded projects published? | Ratings 2014–2018; site no longer online | Its **method** yes ([criteria](https://onthinktanks.org/initiative/transparify/transparify-methodology/)); its old stars only as dated history |
| [Who Funds You?](https://taxjustice.net/2018/07/16/who-funds-you-transparency-and-think-tanks-we-score-the-maximum-again/) (openDemocracy) | Same idea, UK only, A–E | Irregular | Only for UK think tanks, with its date |
| [EU Transparency Register](https://transparency-register.europa.eu/) | Official: registered think tanks must declare funding sources and lobbying costs | Current, official, searchable | **Yes** – official evidence |
| US [FARA](https://efile.fara.gov/) filings | Official: registration as agent of a foreign principal | Current, official | **Yes** – a registration is a strong signal |
| Sanctions lists (EU, UK, UN, US OFAC) | Official designations – e.g. Russian intelligence-run "think tanks" sanctioned in 2021 | Current, official (roadmap D1) | **Yes** – a red flag that ends admission |

Conclusion: **no current, credible ranking exists**, and a single reputation score would be invented precision. Credibility
research (On Think Tanks, [“The art of deception”](https://onthinktanks.org/articles/the-art-of-deception-how-pseudo-think-tanks-and-researchers-influence-policy/))
points to the same few checkable signals: funding transparency, independence from governments and donors, identifiable
people and methods, and official records.

## 2. Design: a publisher profile – evidence, not a score

Every independent publisher gets a profile in `sources/publishers.yaml` (hand-written, each item with its evidence URL
and the date it was checked) plus facts fetched automatically. The portal shows it as a checklist on the publisher's
card, its report pages and the Sources section:

| Check | ✓ / ◐ / ✗ / ? | Evidence (shown as a link) | How it is found |
|---|---|---|---|
| **Funding transparency** (Transparify method) | ✓ donors with amounts · ◐ donors without amounts · ✗ not published | the publisher's own funding page | by hand, re-checked yearly |
| **Government funding** | which governments, and the share where published | funding page / annual report | by hand |
| **Funding from non-democracies** | ✗ if a donor government is rated an autocracy (V-Dem, in the year of funding) | funding page + `/ratings` | by hand + ratings data |
| **Official registers** | EU Transparency Register entry (ID, declared budget); US FARA registration | register entry | tool (register search) |
| **Sanctions / designations** | ✗ red flag – a listed publisher is removed from the library | list entry | tool (roadmap D1) |
| **Identity** | founded, legal form, headquarters, leadership | Wikidata / Wikipedia (revision, date) | tool |
| **People and methods** | named authors; methodology and corrections policy published | publisher's site | by hand |
| **Former ratings** | Transparify stars (year), Who Funds You? grade (year) | archived rating | by hand, dated |

Display: a compact row of symbols (e.g. `funding ✓ · registers ✓ · sanctions – · people ✓`) next to the ◆ badge, each
opening its evidence; no total score. A red flag shows in red on every report of that publisher.

## 3. Admission rule for new think tanks (proposed)

A think tank is added only if: it publishes regular reports on its own domain; its funding is at least partly
disclosed (◐); it is on no sanctions list; it names its authors. Publishers that fail later are kept, but their
profile shows why – nothing disappears silently.

## 4. Steps once approved

1. `sources/publishers.yaml` + checks for the 17 current think tanks (one evening of research, with links and dates).
2. Profile display on Sources, report pages and the ◆ badge tooltip.
3. Fetched checks: Wikidata identity facts; EU Transparency Register lookup; after D1, sanctions matching.
