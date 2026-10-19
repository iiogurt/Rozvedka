"""The portal's menu: one table drives the header menus, the section tabs under the header, the highlight of the page you
are on and the /views overview. A test fails when a page is missing from it, so no page can become unreachable."""

# group: (key, label, hub link, [(label, link, other paths that belong to it, what it answers)])
GROUPS = [
    ("overview", "Overview", "/", [
        ("Overview", "/", (), "Search, the library at a glance, what changed lately."),
    ]),
    ("library", "Library", "/documents", [
        ("Documents", "/documents", ("/report", "/doc", "/search"), "Every report, with filters, full-text search and the file."),
        ("What's new", "/new", ("/feed.atom",), "Reports added to the library, by day."),
        ("Series", "/series", (), "Report series and their editions: what is out, what is missing."),
        ("Watchlist", "/watch", (), "Searches you follow: new reports that match."),
    ]),
    ("topics", "Topics & trends", "/topics", [
        ("Topics", "/topics", (), "The 64 topics and the reports behind each."),
        ("Mind map", "/topics/map", (), "Topics and how they cluster."),
        ("Over time", "/trends", (), "How much attention each topic gets, year by year."),
        ("Terms", "/trends/terms", (), "Any word or phrase over time."),
        ("Topics by country", "/trends/matrix", (), "Which agencies emphasise which topics."),
        ("Compare agencies", "/compare", (), "Two agencies, or two actors, side by side."),
    ]),
    ("actors", "Actors & threats", "/actors", [
        ("Actors", "/actors", (), "Groups, states, people and services named in the reports."),
        ("Network", "/graph", ("/entity",), "Stated links between groups, people, companies, malware: sanctions lists, Wikidata, ATT&CK."),
        ("Find a connection", "/graph/path", (), "How two groups, people or companies are linked: the most specific chains of links."),
        ("Toolkit twins", "/graph/twins", (), "Threat groups that use the same techniques and software (MITRE ATT&CK)."),
        ("Leads", "/graph/leads", (), "Hypotheses: actors never named together that share neighbours – to review."),
        ("Brokers", "/graph/brokers", (), "Entities whose links reach several worlds: state, cyber, terror, armed, crime."),
        ("Named together", "/network", (), "Who the reports name together with whom."),
        ("Sanctions", "/actors/sanctions", (), "EU, UK, UN and US lists matched with the actors."),
        ("Attributions", "/actors/attributions", (), "Official statements that name who is behind a cyber attack."),
        ("Threat levels", "/threat-levels", (), "Official terrorism threat levels, with the quote."),
        ("Events", "/events", (), "Dated events from Wikidata, EuRepoC (cyber incidents) and UCDP (organised violence)."),
        ("CVEs", "/cves", (), "Vulnerabilities named in reports, with CISA's exploited list."),
        ("ATT&CK techniques", "/techniques", (), "Attacker techniques named in reports, with MITRE's catalog."),
    ]),
    ("sources", "Sources", "/sources", [
        ("Agencies", "/sources", (), "The official agencies the library follows, by country."),
        ("Think tanks & analysts", "/publishers", ("/publisher",), "Think tanks and commercial analysts with their credibility profile."),
        ("Map", "/map", (), "Where the agencies are."),
        ("Ratings map", "/map/democracy", (), "Democracy, security and governance ratings of the states, over time."),
        ("Who reports on which country", "/map/mentions", (), "Where agencies' reports point."),
        ("Ratings", "/ratings", ("/ratings/",), "Ratings of the states: democracy, security and governance."),
        ("Citations", "/citations", (), "Which agencies and reports cite which."),
    ]),
    ("maintain", "Maintain", "/views#maintain", [
        ("Update", "/update", ("/jobs",), "Check the agencies for new reports and refresh the indexes."),
        ("Coverage", "/sources/coverage", (), "What is collected, what is missing, per series."),
        ("To collect", "/collect", (), "Reports that need to be added by hand."),
        ("Year conflicts", "/years", (), "Reports whose publication year is in doubt."),
        ("Actor names", "/actors/names", (), "The names used to find actors, and why some are not used."),
        ("Precision review", "/actors/review", (), "Sample passages: is the actor really meant?"),
        ("Data exchange", "/data", (), "Export or import the library's data."),
        ("Changelog", "/changelog", (), "What changed in each version."),
        ("All views", "/views", (), "Every page of the portal, with counts."),
    ]),
]
# a menu for pages of the portal that no menu item names (links in lists)
EXEMPT = ("/api/", "/actor-image", "/logo")


def _paths(item) -> list[str]:
    return [item[1].split("#")[0], *item[2]]


def locate(path: str):
    """(group key, item link) of the menu entry a page belongs to – the longest matching path wins – or (None, None)."""
    path = "/" + path.strip("/") if path.strip("/") else "/"
    best, found = -1, (None, None)
    for key, _label, _hub, items in GROUPS:
        for item in items:
            for p in _paths(item):
                hit = path == p if p == "/" else (path == p or path.startswith(p + "/"))
                if hit and len(p) > best:
                    best, found = len(p), (key, item[1])
    return found


def menu(path: str) -> dict:
    """What the templates draw for this page: the groups with their items, and which group and item are the current ones."""
    group, link = locate(path)
    return {"groups": [{"key": k, "label": label, "short": label.split(" ")[0], "hub": hub, "on": k == group,
                        "pages": [{"label": i[0], "href": i[1], "blurb": i[3], "on": i[1] == link} for i in items]}
                       for k, label, hub, items in GROUPS],
            "group": group, "link": link}
