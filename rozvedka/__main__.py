"""CLI: python -m rozvedka {sync-registry|crawl|download|update|serve|stats|index-topics|fetch-actors|index-actors|…}"""
import argparse
import os
import logging

from . import __version__, build_version, crawler, db, downloader, registry


def main():
    ap = argparse.ArgumentParser(prog="rozvedka")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--version", action="version", version=f"rozvedka {build_version()}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync-registry", help="load sources/registry.yaml into the database")
    c = sub.add_parser("crawl", help="discover documents on source pages")
    c.add_argument("--country"); c.add_argument("--agency")
    d = sub.add_parser("download", help="download discovered documents")
    d.add_argument("--country"); d.add_argument("--retry-failed", action="store_true")
    d.add_argument("--limit", type=int); d.add_argument("--workers", type=int, default=4)
    u = sub.add_parser("update", help="crawl + download new documents (for the timer)")
    u.add_argument("--country")
    s = sub.add_parser("serve", help="run the web portal")
    s.add_argument("--host", default=os.environ.get("ROZVEDKA_HOST", "127.0.0.1"),
                   help="address to listen on: 127.0.0.1 (default) = this computer only; 0.0.0.0 = the whole network "
                        "(no login – only on a trusted home network)")
    s.add_argument("--port", type=int, default=int(os.environ.get("ROZVEDKA_PORT", 8080)))
    sub.add_parser("stats", help="print document counts")
    sub.add_parser("improve-titles", help="replace poor document titles with the title stored in the PDF")
    ix = sub.add_parser("index-topics", help="extract report text (full-text search) and tag documents with topics")
    ix.add_argument("--reextract", action="store_true", help="extract text again for all documents")
    ix.add_argument("--limit", type=int, help="only extract this many new documents (for trying it out)")
    ix.add_argument("--workers", type=int, default=4)
    oc = sub.add_parser("ocr", help="recognise the text of scanned reports (Tesseract via OCRmyPDF)")
    oc.add_argument("--limit", type=int); oc.add_argument("--workers", type=int, default=3)
    dd = sub.add_parser("date-documents", help="give undated reports a year from their first pages (with the evidence)")
    dd.add_argument("--check", action="store_true", help="only measure accuracy on reports whose year is known")
    sub.add_parser("type-documents", help="give every report a document type (annual report, assessment, … form) by rule, "
                                          "and group language versions and summaries into one report")
    ex = sub.add_parser("export", help="write the whole library as a dataset (parts + manifest) for backup or exchange")
    ex.add_argument("dir", help="folder to write into (e.g. a USB disk)")
    ex.add_argument("--no-files", action="store_true", help="catalogue only: database, lists and gazetteer, no report files")
    ex.add_argument("--since", help="only report files added on or after this day (YYYY-MM-DD); the catalogue is complete")
    ex.add_argument("--part-size", default="2G", help="largest part, e.g. 2G, 500M (default 2G)")
    ex.add_argument("--name", default="", help="a label for the file name, e.g. your name or the occasion")
    im = sub.add_parser("import", help="compare a dataset with this library and restore or merge it")
    im.add_argument("path", help="the dataset's .manifest.json, one of its parts, or its folder")
    im.add_argument("--check", action="store_true", help="only verify the dataset and compare it with this library")
    im.add_argument("--prefer", choices=["local", "dataset"], default="local", help="whose hand edits win in a conflict")
    im.add_argument("--no-index", action="store_true", help="skip matching topics, dates and actors afterwards")
    sub.add_parser("fetch-publishers", help="checks of the think tanks: EU register, FARA, sanctions lists, Wikidata")
    sub.add_parser("fetch-ratings", help="democracy ratings of states over time (V-Dem, Freedom House, World Bank WGI)")
    sub.add_parser("fetch-sanctions", help="download the EU, UK, UN and US sanctions lists and match them with the actors")
    sub.add_parser("match-sanctions", help="match the downloaded sanctions lists with the actors again (no download)")
    fp = sub.add_parser("fetch-actor-profiles", help="pictures, key facts and Wikipedia summaries of the actors the reports name")
    fp.add_argument("--refresh", action="store_true", help="download every picture again")
    sub.add_parser("fetch-concepts", help="names of the search concepts in every language, from Wikidata (cross-language search)")
    fa = sub.add_parser("fetch-actors", help="download the actor gazetteer (Wikidata, Wikipedia, MITRE ATT&CK)")
    fa.add_argument("--refresh", action="store_true", help="read the Wikipedia infoboxes again instead of the cache")
    ia = sub.add_parser("index-actors", help="find the gazetteer's actors in the report texts")
    ia.add_argument("--rematch", action="store_true", help="match every document again")
    ia.add_argument("--workers", type=int, default=4)
    lg = sub.add_parser("fetch-logos", help="download agency logos from their home pages")
    lg.add_argument("--refresh", action="store_true", help="re-fetch logos that already exist")
    a = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pypdf").setLevel(logging.ERROR)   # noisy about harmless PDF quirks
    db.init()
    if a.cmd == "sync-registry":
        print(registry.sync())
    elif a.cmd == "crawl":
        print(crawler.crawl(a.country, a.agency))
    elif a.cmd == "download":
        print(downloader.download(a.country, a.retry_failed, a.limit, a.workers))
        print({"titles_improved": downloader.improve_titles()})
    elif a.cmd == "update":
        print(crawler.crawl(a.country))
        print(downloader.download(a.country))
        print({"titles_improved": downloader.improve_titles()})
        from . import actor_sources, actors, topics
        print(topics.index())
        from . import ocr
        if ocr.available():
            print(ocr.run())
        from . import dating, doctypes
        print(dating.date_documents())
        print(doctypes.type_documents())
        from . import works
        print(works.group())
        if actor_sources.GAZETTEER.exists():
            print(actors.index())
    elif a.cmd == "ocr":
        from . import ocr
        print(ocr.run(a.limit, a.workers))
    elif a.cmd == "date-documents":
        from . import dating
        print(dating.check() if a.check else dating.date_documents())
    elif a.cmd == "type-documents":
        from . import doctypes, works
        print(doctypes.type_documents())
        print(works.group())
    elif a.cmd == "fetch-actors":
        from . import actor_sources, concepts
        print(actor_sources.fetch(refresh=a.refresh))
        print(concepts.fetch())     # the search concepts' names too: widening the scope refreshes both
        from . import ratings
        print(ratings.fetch())      # and the states' democracy ratings
        from . import publishers
        print(publishers.fetch())   # and the think tanks' checks
        from . import actor_profiles
        print(actor_profiles.fetch(refresh=a.refresh))   # and the actors' pictures and facts
    elif a.cmd == "fetch-sanctions":
        from . import sanctions
        print(sanctions.fetch_all())
    elif a.cmd == "match-sanctions":
        from . import sanctions
        print(sanctions.match())
    elif a.cmd == "fetch-actor-profiles":
        from . import actor_profiles
        print(actor_profiles.fetch(refresh=a.refresh))
    elif a.cmd == "fetch-publishers":
        from . import publishers
        print(publishers.fetch())
    elif a.cmd == "fetch-ratings":
        from . import ratings
        print(ratings.fetch())
    elif a.cmd == "fetch-concepts":
        from . import concepts
        print(concepts.fetch())
    elif a.cmd == "export":
        from . import dataset
        size = a.part_size.strip().upper()
        mult = {"K": 1e3, "M": 1e6, "G": 1e9}.get(size[-1:], 1)
        m = dataset.export(a.dir, files=not a.no_files, since=a.since, name=a.name,
                           part_size=int(float(size.rstrip("KMG")) * mult))
        print(f"dataset {m['dataset_id']}: {len(m['parts'])} part(s), {m['bytes'] / 1e9:.2f} GB, "
              f"{m['scope']['files_included']} report files\nmanifest: {m['manifest_path']}")
    elif a.cmd == "import":
        from . import dataset
        r = dataset.import_dataset(a.path, check=a.check, prefer=a.prefer, index=not a.no_index)
        print(dataset.describe(r))
    elif a.cmd == "index-actors":
        from . import actors
        print(actors.index(a.workers, rematch=a.rematch))
        from . import sanctions
        if (sanctions.DIR / "meta.json").exists():          # the actors' names may have changed: match the lists again
            print(sanctions.match())
    elif a.cmd == "index-topics":
        from . import topics
        print(topics.index(a.reextract, a.limit, a.workers))
    elif a.cmd == "improve-titles":
        print({"titles_improved": downloader.improve_titles()})
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("rozvedka.app:app", host=a.host, port=a.port)
    elif a.cmd == "fetch-logos":
        from . import logos
        print(logos.fetch_logos(a.refresh))
    elif a.cmd == "stats":
        with db.session() as con:
            for r in con.execute("""SELECT s.country, COUNT(*) n, SUM(d.status='downloaded') ok
                                    FROM documents d JOIN sources s ON s.id=d.source_id
                                    GROUP BY s.country ORDER BY s.country"""):
                print(f"{r['country']:<6} {r['n']:>5} found  {r['ok'] or 0:>5} downloaded")


if __name__ == "__main__":
    main()
