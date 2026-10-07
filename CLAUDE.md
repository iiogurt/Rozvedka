# Rozvedka – working rules

Project conventions agreed with the owner. Follow them in every session, on every machine. The README describes
*what* the app does; this file describes *how* work on it is done.

**Current plan:** [`docs/ROADMAP.md`](docs/ROADMAP.md) – the assessment of the project and the prioritised list of
next steps. Read it at the start of a session; update it (mark items done, re-prioritise) when work lands.

## Purpose and scope

- Rozvedka collects the public, regularly published reports (annual reports, threat assessments, risk analyses)
  of intelligence, cyber-security, civil-protection and police / counter-terrorism agencies, so the owner can
  follow state security, social resilience and disaster preparedness. It is self-hosted (Raspberry Pi), with a
  web portal that lists, downloads, indexes and visualises the reports.
- Scope: EU27 + EU bodies + NATO; other democracies (UK, Norway, Switzerland, Ukraine, USA, Canada, Mexico,
  Brazil, Argentina, Chile, Colombia, Peru, Australia, New Zealand, Japan, South Korea, Taiwan); a few
  international bodies (e.g. IPCC).
- Sources are either **official** (state agencies, government portals, intergovernmental bodies) or, since
  2026-10-07, **independent publishers** – pro-democratic and security think tanks and research institutes that
  publish regular reports (e.g. CEPA). Every report comes from its publisher's own domain; no aggregators or mirrors.
  The two are **always told apart visually** (badge, marker, filter) wherever a source, report, count or map point
  is shown, and every view says which kinds it counts.
- A new think tank gets a credibility profile in `sources/publishers.yaml` (funding disclosure with evidence URL and
  date, donor governments) before it is crawled; run `fetch-publishers` afterwards. Admission: regular reports on its
  own domain, funding at least partly disclosed, on no sanctions list (`docs/PUBLISHER_PROFILES.md`).
- **Whenever the scope widens** (new states, institutions or kinds of publisher), also refresh the actor gazetteer
  from Wikidata / Wikipedia / MITRE ATT&CK (`python -m rozvedka fetch-actors --refresh`, which also refreshes the
  cross-language search concepts, then `index-actors`) so
  subjects, groups and individuals named by the new sources are known.
- For every agency: list **every language version** (original, English, others), each as its own page entry with
  its language tagged, and **archive pages of older reports**, not only the latest edition. Each agency also gets a
  profile (original and official English name, home page, short description of what its reports cover), coalition
  memberships via its country, and its headquarters location for the map.
- Respect robots.txt and crawl politely (one request per host every 2 s). Bot-protected sites are `access: manual`;
  never circumvent access controls.

## Non-negotiable product principles

1. **Traceability.** Everything shown must say where it comes from. Every number on a chart, card, matrix or map
   links to the exact list of documents or passages it counts (verify this with a script that compares counts with
   the linked lists before releasing). External facts (Wikidata, Wikipedia, MITRE ATT&CK, event dates) carry their
   source URL, revision and retrieval date. Each view states how it was computed and what was left out.
2. **Information-dense, readable visualisations.** Prefer labelled, comparable forms – cards with numbers,
   matrices, ranked lists with bars, small multiples – over decorative graphs. No force-directed "hairball"
   graphs; every label stays visible. Measure association / specificity, not raw frequency, when showing relations.
   Follow a validated colour-blind-safe palette in both themes; dark theme is the default.
3. **Honest matching.** Topics and actors are found by keywords and names. Keep the rules transparent (show why a
   name is not used), check precision on random samples of passages, and fix systematic errors with general rules
   first and hand exclusions (`sources/actors.yaml`) second.
4. **No local LLM / embeddings.** The owner decided against it; do not propose it again.

## Git and GitHub

- Repository: https://github.com/iiogurt/Rozvedka (private). Commit identity:
  `iiogurt <188860570+iiogurt@users.noreply.github.com>` (set per repository; never use a personal e-mail).
- `main` always holds working code. Every change goes on a branch (`feat/…`, `fix/…`, `sources/…`, `docs/…`,
  `chore/…`) and is merged through a pull request **with a merge commit**.
- Claude opens the PR, **merges it and cuts the release itself** – the owner does not want to do this manually.
  One PR per change; merge it before starting the next (no stacked PRs).
- PR descriptions: what changed, how it was verified (tests, sample checks, screenshots), and the test count.
- Registry edits go in their own commits (`sources: add Latvian SAB reports page`).
- Never commit `data/` (database, downloaded PDFs, logos, gazetteer), `.env*`, keys or credentials;
  `.gitignore` covers them.
- `gh pr edit` fails on the installed gh (Projects-classic GraphQL error); use `gh api` REST calls instead.

## Versions, changelog, releases

- Semantic Versioning **by significance** (table in `CHANGELOG.md` → "Versioning"):
  - **patch** – fixes, new or corrected sources, keyword changes, visual tweaks, documentation;
  - **minor** – a new capability (page, view, filter, command, registry or database field);
  - **major** – an incompatible change needing manual migration.
- `CHANGELOG.md` follows Keep a Changelog. Note changes under **Unreleased** while working; plain, specific
  language about what the user gets.
- Release steps, every time:
  1. `python3 tools/bump_version.py patch|minor|major` – updates `rozvedka/__init__.py`, the changelog and the
     README version badge (the repo is private, so the badge is static).
  2. Run the tests; commit; open and merge the PR.
  3. Tag the merge commit `v<version>` (annotated: `git tag -a v<version> -m "Rozvedka <version>"`) and push it.
  4. Create a GitHub release from that changelog section (mark it latest).
  5. Restart the portal so the footer / `/api/version` show the new version.

## README

- Keep `README.md` in the GitHub layout: centred header with badges and a hero screenshot, About table, Features
  page by page with screenshots, Quick start, Commands table, Configuration table (+ collapsible details), How it
  works (Mermaid diagram + module table), Development, Data sources and licences, caution note.
- Update it with every feature: describe what the user can do, and retake affected screenshots in
  `docs/images/` – **dark theme**, 1280 px wide. Do not show agency logos in screenshots (the Sources and
  Documents pages), since logos are the agencies' marks and are not committed.

## Code and tests

- Python 3.13, FastAPI + Jinja (server-rendered), SQLite with FTS5, vendored front-end libraries (Leaflet,
  ECharts) – no CDN at runtime. Match the surrounding code's style and comment density.
- Every list in the portal uses the shared pager (`rozvedka/paging.py` + `templates/_pager.html`): numbered pages,
  first/last, "go to page", page-size choice, filters kept in every link. Never cap a list silently.
- Every change keeps `python -m pytest -q` green; new behaviour gets tests (temporary database fixtures as in
  `tests/test_trends.py`, `tests/test_actors.py`, `tests/test_graphs.py`).
- Check UI changes in headless Chromium (screenshots, and the DevTools protocol for interactions) in both themes.
- Hand-written data files (`sources/*.yaml`) are the source of truth; generated fields (e.g. event dates) come
  from tools, never typed from memory. Quote the country code `"NO"` in YAML.

## Operating the Raspberry Pi installation

- Project path `/home/prisonmaster/Documents/Projects/Rozvedka`; run project commands as the `prisonmaster`
  user (`sudo -u prisonmaster .venv/bin/python -m rozvedka …`) and `chown -R prisonmaster:prisonmaster .` after
  writing files as root.
- Portal: `python -m rozvedka serve` on port 8080 (LAN only, no login – never expose it to the internet).
- Stop processes with `kill $(pgrep -f '^.venv/bin/python -m rozvedka serve')`. Never run `pkill -f`/`pgrep -f`
  with a pattern that also appears in the same shell command line – it matches and kills that shell.
- Ask before anything needing `sudo` beyond running as `prisonmaster` (e.g. `loginctl enable-linger` for the
  systemd user services in `deploy/`).
