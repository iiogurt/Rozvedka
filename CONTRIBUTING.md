# Contributing to Rozvedka

Thank you for helping. Rozvedka is a small, self-hosted project with one maintainer
([@iiogurt](https://github.com/iiogurt)); outside contributions are welcome, most of all **new or corrected sources**,
bug reports and fixes. This page says what fits the project and how a change gets in.

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems go through a private advisory,
never a public issue – see [SECURITY.md](SECURITY.md).

## What Rozvedka collects

Rozvedka gathers the public, regularly published reports – annual reports, threat assessments, risk analyses – of
**intelligence services, cyber-security centres, civil-protection authorities and police / counter-terrorism agencies**.

- **States and bodies in scope:** the EU27, EU bodies and NATO; the UK, Norway, Switzerland, Ukraine, the USA, Canada,
  Mexico, Brazil, Argentina, Chile, Colombia, Peru, Australia, New Zealand, Japan, South Korea and Taiwan; and a few
  international bodies (e.g. the IPCC). Widening the scope (a new state or kind of publisher) is the maintainer's decision
  – open an issue first.
- **Kinds of publisher**, always shown apart in the portal:
  - **official** – state agencies, government portals, intergovernmental bodies;
  - **independent** (◆) – pro-democratic and security think tanks and research institutes with regular reports;
  - **commercial** (■) – companies selling analysis, rated by who owns them.
- Every report comes from **its publisher's own domain**: no aggregators, mirrors or re-uploads.

### Proposing a source

Open a [source suggestion](https://github.com/iiogurt/Rozvedka/issues/new?template=source_suggestion.yml) or send a pull
request that edits [`sources/registry.yaml`](sources/registry.yaml) (the format is described at the top of that file):

- **Every language version** of the reports page gets its own `pages` entry with its `lang`, and **archive pages of
  older reports** are listed too (`kind: archive`), not only the latest edition.
- Each agency gets a profile: original and official English name, home page, a short description of what its reports
  cover, and its headquarters (`hq`) for the map.
- A registry change goes in **its own commit** (`sources: add Latvian SAB reports page`).
- `python3 tools/check_registry.py` checks that every registry URL still loads; `python -m rozvedka sync-registry` and
  `python -m rozvedka crawl --country XX --agency YY` show what the crawler finds.

### Proposing a think tank or commercial analyst

An independent or commercial publisher needs a **credibility profile** in [`sources/publishers.yaml`](sources/publishers.yaml)
before it is crawled – the method and the checks are explained in [`docs/PUBLISHER_PROFILES.md`](docs/PUBLISHER_PROFILES.md).
To be admitted, a think tank must

- publish regular reports on its own domain,
- disclose its funding at least in part (give the evidence URL and the date you checked it, and any donor governments),
- be on no sanctions list (EU, UK, UN, US).

Commercial analysts give their ownership instead of funding. The maintainer then runs `python -m rozvedka
fetch-publishers` to add the register, FARA and sanctions checks.

## Crawling ethics

- **Respect robots.txt** and crawl politely: one request per host every 2 seconds (built into `rozvedka/fetch.py`; do
  not lower it).
- A bot-protected site is marked `access: manual` – its reports are added by hand in the portal (*To collect*).
- **Never circumvent access controls**: no CAPTCHA solvers, no proxy rotation, no forged sessions. A pull request that
  does this will be closed.

## Principles every change follows

1. **Traceability.** Everything shown says where it comes from. Every number on a chart, card, matrix or map links to
   the exact list of documents or passages it counts; external facts (Wikidata, Wikipedia, MITRE ATT&CK, event dates)
   carry their source URL, revision and retrieval date; each view says how it was computed and what it left out.
2. **Dense, readable visualisations.** Labelled, comparable forms – cards with numbers, matrices, ranked lists with
   bars, small multiples. No force-directed "hairball" graphs; every label stays visible. Relations measure association
   or specificity, not raw frequency. Colours come from a colour-blind-safe palette in both themes; dark is the default.
3. **Honest matching.** Topics and actors are found by keywords and names, with transparent rules. Systematic errors are
   fixed with general rules first and hand exclusions (`sources/actors.yaml`) second; check precision on random samples
   of passages and say how you did.
4. **No LLMs or embeddings.** The project has decided against language models and vector embeddings, local or remote.
   Proposals to add them will be declined.

Every list in the portal uses the shared pager (`rozvedka/paging.py` + `templates/_pager.html`); never cap a list
silently.

## Setting up and running the tests

Python **3.13** is the reference (the Raspberry Pi target). CI runs the test suite on Ubuntu with Python 3.13 as the
required job, and measures – without requiring – Python 3.10–3.12, Linux ARM64, macOS and Windows
([`.github/workflows/tests.yml`](.github/workflows/tests.yml)).

```bash
git clone https://github.com/iiogurt/Rozvedka.git && cd Rozvedka
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The tests build their own temporary libraries (no `data/`, no network). New behaviour gets tests – see
`tests/test_trends.py`, `tests/test_actors.py` or `tests/test_graphs.py` for temporary database fixtures. For a change to
the portal, check the pages in a browser in **both themes**.

Stack: FastAPI + Jinja (server-rendered), SQLite with FTS5, vendored front-end libraries (Leaflet, ECharts) and no CDN at
runtime. Match the surrounding code's style and comment density.

## Pull requests

- Work on a branch named by the kind of change: `feat/…`, `fix/…`, `sources/…`, `docs/…` or `chore/…`.
- **One pull request per change.** Keep it focused; unrelated fixes go in their own PR.
- Describe **what changed**, **how you verified it** (tests, sample checks, screenshots) and the **test count** from
  `pytest -q`. The template asks for these.
- Note the change in [`CHANGELOG.md`](CHANGELOG.md) under `## [Unreleased]`, following
  [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), in plain words about what a user gets. **Do not bump the
  version**: the maintainer decides patch / minor / major, cuts the release and tags it.
- CI must be green; the maintainer merges with a merge commit.
- If a feature changes what the README describes, update it; screenshots in `docs/images/` are **dark theme, 1280 px
  wide, without agency logos** (logos are the agencies' marks and are not committed). `python3 tools/screenshots.py`
  takes them this way.

## Never commit

- `data/` – the database, downloaded PDFs, logos and gazetteer (`.gitignore` covers it);
- `.env*` files, keys, tokens or other credentials;
- personal names, e-mail addresses, home paths or host names – in files, screenshots or commit metadata. GitHub's
  `noreply` address works as your commit e-mail.

## YAML quirks

- The hand-written `sources/*.yaml` files are the source of truth. Fields marked as generated (e.g. event dates in
  `sources/events.yaml`) come from tools – re-run the tool, never type them from memory.
- **Quote the country code `"NO"`** (Norway): a bare `NO` is read as boolean false.
- Quote strings that contain `: `, `#` or start with a special character; keep the files' existing layout and comments.
