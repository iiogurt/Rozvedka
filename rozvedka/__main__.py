"""CLI: python -m rozvedka {sync-registry|crawl|download|update|serve|stats|index-topics|fetch-actors|index-actors|…}"""
import argparse
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
    s.add_argument("--host", default="0.0.0.0"); s.add_argument("--port", type=int, default=8080)
    sub.add_parser("stats", help="print document counts")
    sub.add_parser("improve-titles", help="replace poor document titles with the title stored in the PDF")
    ix = sub.add_parser("index-topics", help="extract report text (full-text search) and tag documents with topics")
    ix.add_argument("--reextract", action="store_true", help="extract text again for all documents")
    ix.add_argument("--limit", type=int, help="only extract this many new documents (for trying it out)")
    ix.add_argument("--workers", type=int, default=4)
    dd = sub.add_parser("date-documents", help="give undated reports a year from their first pages (with the evidence)")
    dd.add_argument("--check", action="store_true", help="only measure accuracy on reports whose year is known")
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
        from . import dating
        print(dating.date_documents())
        if actor_sources.GAZETTEER.exists():
            print(actors.index())
    elif a.cmd == "date-documents":
        from . import dating
        print(dating.check() if a.check else dating.date_documents())
    elif a.cmd == "fetch-actors":
        from . import actor_sources
        print(actor_sources.fetch(refresh=a.refresh))
    elif a.cmd == "index-actors":
        from . import actors
        print(actors.index(a.workers, rematch=a.rematch))
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
