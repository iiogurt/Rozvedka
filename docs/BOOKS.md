# A local library of books: what it would take (roadmap H2)

**Status:** H2a (import, metadata with its origin, search, topics and actors, the book kind) built in 0.75.0; H2b–H2d open.

The owner asked on 2026-10-19: how hard would it be to add a local library of about 100 e-books (PDF) of journalism and
history, linked into the database? It should extract not only keywords but also basic meanings.

**Short answer:** it is feasible on the Raspberry Pi, and most of the pipeline already exists, because reports go
through it. Two things decide the effort:
1. **Scanned books** need OCR, which is slow on a Pi 4.
2. **"Meaning" without a language model** is limited to what can be shown with evidence: what a chapter is about, its
   distinctive terms, its key sentences quoted as written, dated statements, and stated relations between subjects.
   A summary in new words would need a language model, which the owner has ruled out.

## 1. Sizes, measured against the library (2026-10-19)

| | Now | With 100 books (estimate) |
|---|---|---|
| Words indexed | 50.8 M in 4,575 documents | +10 M (100 × ~350 pages × ~300 words), about +20 % |
| Database | 0.82 GB | about +0.2 GB |
| Files | 18 GB, 41 GB free | +0.5–2 GB |
| Text extraction (pypdf, already used) | – | one to two hours for books with a text layer |
| OCR (`python -m rozvedka ocr`, tesseract, 3 workers) | – | only for scanned books: roughly 1–3 hours per 350-page book on the Pi 4 (4 cores), so days for 100 scans – measure on the first ones |
| Actor and topic matching (`index-actors`) | as now | about 20 % longer |

The machine is a Raspberry Pi 4 Model B with 8 GB RAM. Nothing here needs more memory than indexing reports does now.
EPUB files would be cheaper than PDFs: clean text and chapters without extraction problems. Accepting them is a small
addition.

## 2. Pipeline

1. **Folder:** `data/books/` holds the files and a hand-written `books.yaml` (file, ISBN, language, notes). Like all of
   `data/`, it is never committed. A personal reading list is personal, so it is not kept in the public repository the
   way the source registry is. Book text is never part of `export` unless asked for.
2. **Metadata and subjects:** the ISBN on the copyright page is looked up in [Open Library](https://openlibrary.org/developers/api)
   (catalogue data CC0; the API is for lookups, not bulk) and Wikidata. That gives author, publisher, year, edition and
   language.
   - **Authors and publishers become subjects** of the network, with ties from Wikidata: employer (a journalist at a
     state broadcaster), nationality, awards.
   - A publisher can get an ownership check, using the profile machinery of think tanks and commercial analysts (a
     state-owned publishing house is a fact to show).
3. **Structure:**
   - chapters from the PDF outline (pypdf reads it) or from the headings;
   - printed page numbers from the PDF page labels, so a citation says "p. 123" as printed, not the PDF page index;
   - the **book's own index** at the back is parsed into headwords with their pages. This is the editor's own list of
     what each page is about – the best keyword source there is – and the headwords are matched to the gazetteer actors
     and topics.
4. **The existing pipeline, per chapter:** full-text search, actors, topics, cross-language concepts, mentions.
   - Books then appear on actor pages, in mentions, in "named together" and in the network.
   - They are kept apart from reports in every count.

## 3. "Basic meanings" without a language model

| What | How | Shown as |
|---|---|---|
| **What a chapter is about** | actors, places, topics and index headwords, counted per chapter | ranked lists; each number opens the passages |
| **Distinctive terms** | words and phrases over-represented in a chapter or book compared with the whole library (log-likelihood or lift, as the topic matrix does) | the chapter's own vocabulary, with counts |
| **Key sentences** (an extractive summary) | the 3–5 sentences that share the most distinctive terms with the rest of the chapter (TextRank on word overlap – lexical, no trained model) | quoted verbatim with the page; the shared terms shown as "why chosen" |
| **Dated statements** | sentences that hold a date and a known actor or event ("In March 2014 Russia annexed Crimea"), found by date patterns in running text – new rules, built like the multilingual year rules of `dating.py` | a table {date, actors, event, sentence, page}. It feeds the timeline as "according to <book>, p. n", kept apart from official and Wikidata facts |
| **Stated relations between subjects** | two known subjects in one sentence joined by a verb from a short, published list (funded, ordered, recruited, attacked, met, owned …) | "the book states: X – funded – Y (p. n)" with the sentence. Precision is sampled as for actor matching; nothing is inferred beyond the sentence |

**What this cannot do:** restate the author's argument in new words, or reliably catch negation, irony or hypotheticals
("did *not* fund"). Doing that needs a language model.
- A local LLM and embeddings are excluded by the owner.
- Sending book text to a cloud service is not proposed (copyright and privacy).
- A trained parser such as spaCy would improve who-did-what extraction. It is a trained model too, so it is the owner's
  call.

Without it, the relation rule shows the sentence every time, so a reader sees a negation at once. The precision
sample measures how often it happens.

## 4. How it is shown

- A **fourth kind of source**, "book". It is marked apart from official agencies, think tanks and commercial analysts
  wherever it appears, is left out by "Official agencies only", and is counted separately.
- A book is a secondary source as of its publication date. Every statement from it shows author, title, year and page.
- **Copyright:** the portal (LAN only, no login) shows passages up to a paragraph long with page numbers, as it does for
  reports. The full text stays in the local file. No book pages appear in README screenshots.
- **Book page:** metadata and subjects (author and publisher ties), chapters with their actors, topics and key
  sentences, the book's index matched to the gazetteer, its dated statements, and "where else": reports and other books
  that name the same subjects.

## 5. Steps and effort

1. **H2a – import:** the `import-books` command, metadata from ISBN, search, actors and topics per chapter, the book
   kind in every view. · minor
2. **H2b – structure:** chapters from the outline or headings, printed page numbers, the back-of-book index parsed and
   matched. · minor
3. **H2c – meanings:** distinctive terms, key sentences, dated statements, stated relations, each with a precision
   sample on random passages. · minor
4. **H2d – to the timeline:** dated statements as events "according to <book>" (after H1). · minor

Overall this is roughly twice the work of the commercial-analysts category (0.69.0), plus OCR time if the books are
scans.

## 6. Questions for the owner (answered 2026-10-19)

1. Are the books born-digital PDFs (with a text layer) or scans? Is EPUB available for some?
2. Which languages?
3. Are extractive meanings (key sentences quoted, dated statements, stated relations, each with its page) enough? Or
   should a trained parser such as spaCy be allowed for better who-did-what extraction?

**Answers:** English books, a mix of PDF and EPUB. The owner prefers the smarter way: a trained parser (spaCy) may be used for
who-did-what extraction; every statement still shows its sentence and page.
