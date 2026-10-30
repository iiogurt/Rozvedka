"""Unit tests for the crawler's pure heuristics (no network)."""
import pytest

from rozvedka.crawler import (CALL_TO_ACTION, GENERIC_TITLES, LOW_RELEVANCE_RE, extract, guess_lang, guess_year,
                              humanize_filename, is_poor_title)
from rozvedka.downloader import good_pdf_title
from rozvedka.logos import candidates


@pytest.mark.parametrize("title,good", [
    ("Rapport annuel de la Sûreté de l'État 2025", True),
    ("Microsoft Word - VZ_2023_final.docx", False),
    ("untitled", False),
    ("", False),
])
def test_good_pdf_title(title, good):
    assert good_pdf_title(title) is good


def test_logo_candidates_prefer_own_logo_over_portal_mark():
    html = """<header><img src="/themes/ccbe/fonts/iconfont/svg/be.svg" class="logo">
              <a class="site-logo"><img src="/files/2025-02/vsse-logo.png" alt="VSSE"></a></header>
              <link rel="apple-touch-icon" href="/favicon/apple-touch-icon.png">"""
    urls = candidates(html, "https://vsse.be/", "VSSE")
    assert urls[0] == "https://vsse.be/files/2025-02/vsse-logo.png"
    assert urls.index("https://vsse.be/themes/ccbe/fonts/iconfont/svg/be.svg") > urls.index(
        "https://vsse.be/favicon/apple-touch-icon.png")


@pytest.mark.parametrize("url,text,page_lang,allowed,expected", [
    ("https://www.bis.cz/content/vyrocni-zpravy/2024-vz-aj.pdf", "Annual Report 2024", "en", {"cs", "en"}, "en"),
    ("https://www.bis.cz/content/vyrocni-zpravy/2024-vz-cj.pdf", "Výroční zpráva 2024", "cs", {"cs", "en"}, "cs"),
    ("https://www.bis.cz/content/vyrocni-zpravy/en/ar2017en.pdf", "Annual report", "cs", {"cs", "en"}, "en"),
    ("https://www.valisluureamet.ee/doc/raport/2026-et.pdf", "", "en", {"en", "et"}, "et"),
    ("https://example.gov/report_EN.pdf", "", "de", {"de", "en"}, "en"),
    ("https://example.gov/bericht.pdf", "English version", "de", {"de", "en"}, "en"),
    ("https://example.gov/bericht.pdf", "Jahresbericht", "de", {"de", "en"}, "de"),
    ("https://example.gov/raport.pdf", "", "ro+en", {"ro", "en"}, "ro"),
])
def test_guess_lang(url, text, page_lang, allowed, expected):
    assert guess_lang(url, text, page_lang, allowed) == expected


@pytest.mark.parametrize("title,url,expected", [
    ("Annual Report of the Security Information Service for 2023", "https://x/2023-vz-aj.pdf", 2023),
    ("", "https://x/doc/raport/2019-en.pdf", 2019),
    ("Report", "https://x/2020/04/21/report-2019.pdf", 2019),   # filename (covered year) beats publish-date path
    ("Report", "https://x/2021/05/annual-report.pdf", 2021),     # only the path has a year
    ("Nothing here", "https://x/report.pdf", None),
    ("Cyber Threats and NATO 2030", "https://x/uploads/2020/12/NATO-2030.pdf", 2020),   # horizon year is not the date
    ("Trendanalyse Bevölkerungsschutz 2035", "https://x/Trends2035_D.pdf", None),
    ("Who's Winning", "https://x/research_reports/RRA2000/RRA2032-1/RAND_RRA2032-1.pdf", None),   # serial numbers
])
def test_guess_year(title, url, expected):
    assert guess_year(title, url) == expected


@pytest.mark.parametrize("title", ["Download PDF", "Stáhnout PDF", "PDF (2,3 MB)", "Download", "", "pdf 1.2 MB"])
def test_generic_titles(title):
    assert GENERIC_TITLES.match(title)


@pytest.mark.parametrize("title", ["Annual Report 2024", "Výroční zpráva 2023", "Download the TE-SAT 2024 report"])
def test_real_titles_not_generic(title):
    assert not GENERIC_TITLES.match(title)


@pytest.mark.parametrize("text,low", [
    ("2022 low and middle-value framework contracts", True),
    ("Raport_acces_la_informatiile_de_interes_public_2020.pdf", True),
    ("Списък на допуснатите кандидати", True),
    ("Raport_SRI_2014.pdf", False),
    ("Годишен доклад за дейността на ДАНС за 2020 г.", False),
    ("EU Terrorism Situation and Trend Report 2025", False),
    ("2025 APS Employee Census Highlight Report", True),
    ("National Emergency Management Agency Gift and Benefits Register", True),
    ("AusAlert decision support tool https://www.nema.gov.au/sites/default/files/2026-07/Document 1 (FOI 2526-22).pdf", True),
    ("Agency Procedures for Determining Suspected Breaches of the APS Code of Conduct", True),
    ("HCSS – Code of Conduct for Responsible Use of AI", False),   # a publication, not a staff rule
    ("2025–26 Annual Report", False),
    ("NSA 2024 Cybersecurity Year in Review", False),
    ("2025 Gender Pay Gap Report https://www.nationalcrimeagency.gov.uk/who-we-are/publications/815-2025-gender-pay-gap-report/file.pdf", True),
    ("The Cocaine Chemists [Podcast Transcript]", True),
    ("2024 Annual Report for Section 22 Protected Disclosures 03/03/2025", True),   # whistle-blowing statistics
    ("How to register your organisation for the Child Sexual Exploitation and Abuse Industry Reporting Portal", True),
    ("正誤表（23KB） https://www.npa.go.jp/publications/statistics/kikakubunseki/r7seigohyou.pdf", True),
    # a white paper whose row also offers its errata: only the file name tells the errata apart
    ("令和４年版防災白書（ html 、 PDF ）、正誤表（ PDF ） https://www.bousai.go.jp/kaigirep/hakusho/pdf/R4_honbun.pdf", False),
    ("令和７年における組織犯罪の情勢（7.3MB）", False),
    ("National Strategic Assessment of Serious and Organised Crime 2026", False),
    ("Інформація про стан розгляду запитів на інформацію в Національній поліції за ІІ квартал 2026 року", True),
    ("Звіт за результатами проведення інформаційного аудиту наборів даних", True),
    ("Звіт Національної поліції України про результати роботи у 2025 році", False),
])
def test_low_relevance(text, low):
    assert bool(LOW_RELEVANCE_RE.search(text)) is low


@pytest.mark.parametrize("text,cta", [
    ("Click here to access our report", True),
    ("Télécharger ici le rapport complet.", True),
    ("Download hier het volledige verslag.", True),
    ("Consultez les photos", True),
    ("Download the TE-SAT 2024 report", False),        # has a year -> a real title
    ("Open Source Intelligence and hybrid threats", False),
    ("Annual Report 2023", False),
])
def test_call_to_action(text, cta):
    assert CALL_TO_ACTION.match(text) is cta


def test_poor_titles():
    assert is_poor_title("web2-espionnage_et_ingerence-v3-uk-simple.pdf", "https://x/web2.pdf")
    assert is_poor_title("Click here to access our report", "https://x/r.pdf")
    assert not is_poor_title("Verfassungsschutzbericht 2025", "https://x/vsb.pdf")


def test_humanize_filename():
    assert humanize_filename("https://x/content/vyrocni-zprava-archivu_bis-2024-web.pdf") == \
        "vyrocni zprava archivu bis 2024 web"


def test_extract_liferay_document_links():
    html = '<a href="/documents/475963/0/Risikobild+2026+Teil+1.pdf/cfb12d11?t=1&amp;download=true">Risikobild 2026 Teil 1</a>'
    docs, _ = extract(html, "https://verteidigungspolitik.at/risikobild")
    assert len(docs) == 1 and docs[0]["title"] == "Risikobild 2026 Teil 1"


def test_extract_respects_base_href_and_skips_junk():
    html = """<html><head><base href="https://www.bsi.bund.de/"></head><body>
      <a href="SharedDocs/Downloads/DE/Lagebericht2025.pdf?__blob=publicationFile">Die Lage 2025 (PDF, barrierefrei)</a>
      <a href="/privacy.pdf">Privacy policy</a>
      <a href="DE/Service-Navi/Publikationen/Lagebericht/archiv.html">Lageberichte Archiv</a>
      <a href="mailto:x@y.z">mail</a>
    </body></html>"""
    docs, subs = extract(html, "https://www.bsi.bund.de/DE/Service-Navi/Publikationen/Lagebericht/lagebericht_node.html")
    assert [d["url"] for d in docs] == [
        "https://www.bsi.bund.de/SharedDocs/Downloads/DE/Lagebericht2025.pdf?__blob=publicationFile"]
    assert subs == [("https://www.bsi.bund.de/DE/Service-Navi/Publikationen/Lagebericht/archiv.html",
                     "Lageberichte Archiv")]


def test_domain_family_and_official_filter():
    from rozvedka.crawler import domain_family, official_families
    assert domain_family("https://assets.publishing.service.gov.uk/media/x.pdf") == "gov.uk"
    assert domain_family("https://www.bis.cz/vyrocni-zpravy/") == "bis.cz"
    src = {"homepage": "https://www.cyber.gc.ca/", "domains": ""}
    fams = official_families(src, "https://www.cyber.gc.ca/en/guidance/ncta")
    assert domain_family("https://www.cyber.gc.ca/sites/default/files/ncta.pdf") in fams
    assert domain_family("https://www.justice.gov/d9/complaint.pdf") not in fams      # cited in a footnote
    odni = {"homepage": "https://www.dni.gov/", "domains": "odni.gov"}
    assert domain_family("https://www.odni.gov/files/ATA-2026.pdf") in official_families(odni, None)


def test_extract_dspace_download_links():
    html = '<a href="/bitstreams/5b9dc559-233f-4be4-ae16-e5fd767707de/download">ABIN_Desafios_2026.pdf (77.28 MB)</a>'
    docs, _ = extract(html, "https://repositorio.enap.gov.br/handle/1/9285")
    assert len(docs) == 1 and docs[0]["url"].endswith("/download")


def test_title_size_suffix_removed_and_filename_title_is_poor():
    html = '<a href="/bitstreams/abc/download">ABIN_Desafios_2026.pdf (77.28 MB)</a>'
    docs, _ = extract(html, "https://repositorio.enap.gov.br/handle/1/9285")
    assert docs[0]["title"] == "ABIN_Desafios_2026.pdf"
    assert is_poor_title(docs[0]["title"], docs[0]["url"])


@pytest.mark.parametrize("text", ["Protocolo de Servicio al Ciudadano", "REPORTE COMPLEMENTARIO N.° 13180",
                                  "Política de tratamiento de datos personales"])
def test_low_relevance_latam_admin(text):
    assert LOW_RELEVANCE_RE.search(text)


def test_yearly_report_pages_are_followed_despite_navigation_pdfs(monkeypatch):
    """An archive page with a few navigation PDFs and one page per yearly report: the report pages are followed."""
    from types import SimpleNamespace
    from rozvedka import crawler
    listing = """<a href="/files/eidas-list.pdf">eIDAS</a><a href="/files/scheme.pdf">e-ID scheme</a><a href="/files/brochure.pdf">Brochure</a><a href="/files/guide.pdf">Guide</a>
                 <a href="/files/RFC-2350.pdf">RFC 2350</a><a href="/files/privacy-statement-x.pdf">Statement</a>
                 <a href="/raport-vjetor-2021/">Raport vjetor 2021</a><a href="/raport-vjetor-2022/">Raport vjetor 2022</a>
                 <a href="/raport-vjetor-2023/">Raport vjetor 2023</a><a href="/raport-vjetor-2024/">Raport vjetor 2024</a>
                 <a href="/2026/05/dobesi-kritike-ne-notepad/">Dobësi kritike në Notepad++ – raport</a>"""
    pages = {"https://x.al/raporte/": listing}
    for y in (2021, 2022, 2023, 2024):
        pages[f"https://x.al/raport-vjetor-{y}/"] = f'<a href="/files/raport-{y}.pdf">Shkarko</a>'
    monkeypatch.setattr(crawler, "get_page", lambda url, src: SimpleNamespace(status=200, content_type="text/html",
                                                                             text=pages.get(url, ""), url=url))
    stored = {}
    monkeypatch.setattr(crawler, "_store", lambda con, sid, pid, docs, *a: stored.update({d["url"]: d for d in docs}) or len(stored))
    src = {"id": 1, "access": "auto", "homepage": "https://x.al/", "agency": "X", "domains": None}
    status, n = crawler.crawl_page(None, src, {"url": "https://x.al/raporte/", "id": 1, "lang": "sq", "note": None}, {"sq"})
    assert status.startswith("ok") and "4 sub-pages" in status
    assert {u for u in stored if "raport-20" in u} == {f"https://x.al/files/raport-{y}.pdf" for y in (2021, 2022, 2023, 2024)}
    assert not any("RFC-2350" in u or "eidas" in u for u in stored)
    assert crawler.LOW_RELEVANCE_RE.search("Përditësime të Sigurisë – Mozilla CVE-2026-8090")


def test_related_publications_on_a_publication_page_keep_their_own_names(monkeypatch):
    """A publication page (followed from a think tank's or agency's list) also links other publications' PDFs: those keep
    the name their link gives, not this page's heading (seen on the Swedish Psychological Defence Agency's pages)."""
    from types import SimpleNamespace
    from rozvedka import crawler
    pages = {"https://x.org/pubs": '<a href="https://x.org/pubs/archive/a">A</a><a href="https://x.org/pubs/archive/b">B</a>',
             "https://x.org/pubs/archive/a": '<h1>The Architecture of Repression</h1><a href="/d/a.pdf">Get publication</a>'
                                            '<a href="/d/b.pdf">Get publication The Last European Colonial Empire</a>',
             "https://x.org/pubs/archive/b": '<h1>The Last European Colonial Empire</h1><a href="/d/b.pdf">Get publication</a>'
                                            '<p>The report maps the organisations, programmes and resources of the Presidential '
                                            'Administration and how they shape the indoctrination of the population. '
                                            '<a href="/d/b-sv.pdf">här pdf, 1 MB, öppnas i nytt fönster</a></p>'}
    monkeypatch.setattr(crawler, "get_page", lambda url, src: SimpleNamespace(status=200, content_type="text/html",
                                                                             text=pages.get(url, ""), url=url))
    stored = {}
    monkeypatch.setattr(crawler, "_store", lambda con, sid, pid, docs, *a: stored.update({d["url"]: d["title"] for d in docs}) or len(stored))
    src = {"id": 1, "access": "auto", "homepage": "https://x.org/", "agency": "X", "name_en": "X", "name_local": "X", "domains": None}
    crawler.crawl_page(None, src, {"url": "https://x.org/pubs", "id": 1, "lang": "en", "note": None, "follow": r"pubs/archive/"}, {"en"})
    assert stored == {"https://x.org/d/a.pdf": "The Architecture of Repression", "https://x.org/d/b.pdf": "The Last European Colonial Empire",
                      "https://x.org/d/b-sv.pdf": "The Last European Colonial Empire"}


def test_documents_cited_in_the_text_do_not_take_the_page_heading(monkeypatch):
    """Graphika's report pages cite its earlier reports inside sentences; those PDFs are not the page's publication."""
    from types import SimpleNamespace
    from rozvedka import crawler
    pages = {"https://x.com/reports": '<a href="https://x.com/reports/posing-as-patriots">Posing as Patriots</a>',
             "https://x.com/reports/posing-as-patriots":
                 '<h1>Posing as Patriots</h1><p>The actors behind the campaign succeeded in hiring freelance authors to produce '
                 'content, and also ran a fake left-wing outlet called <a href="/d/ira_again_unlucky_thirteen.pdf">Peace Data</a> '
                 'to target both sides of the political debate.</p><p><a href="/d/posing-as-patriots.pdf">Read the full report</a></p>'}
    monkeypatch.setattr(crawler, "get_page", lambda url, src: SimpleNamespace(status=200, content_type="text/html",
                                                                             text=pages.get(url, ""), url=url))
    stored = {}
    monkeypatch.setattr(crawler, "_store", lambda con, sid, pid, docs, *a: stored.update({d["url"]: d["title"] for d in docs}) or 0)
    src = {"id": 1, "access": "auto", "homepage": "https://x.com/", "agency": "X", "name_en": "X", "name_local": "X", "domains": None}
    crawler.crawl_page(None, src, {"url": "https://x.com/reports", "id": 1, "lang": "en", "note": None, "follow": r"x\.com/reports/[\w-]+$"}, {"en"})
    assert stored == {"https://x.com/d/ira_again_unlucky_thirteen.pdf": "ira again unlucky thirteen",
                      "https://x.com/d/posing-as-patriots.pdf": "Posing as Patriots"}


def test_a_download_attribute_names_the_file():
    from bs4 import BeautifulSoup
    from rozvedka.crawler import _title_for
    a = BeautifulSoup('<a href="/p/eset-threat-report-h12026.pdf" download="ESET Threat Report H1 2026">Download</a>', "html.parser").a
    assert _title_for(a) == "ESET Threat Report H1 2026"
    a = BeautifulSoup('<a href="/p/annual-2025.pdf" download="annual-2025.pdf">Download</a>', "html.parser").a
    assert _title_for(a) == "annual 2025"
    a = BeautifulSoup('<a href="/p/t1.pdf" download="ESET Threat Report T&amp;hairsp;1 2022">Download</a>', "html.parser").a
    assert _title_for(a) == "ESET Threat Report T1 2022"
    a = BeautifulSoup('<a href="/p/q4.pdf">ESET APT Activity Report Q4 2022\u00ad–Q1\u200a2023</a>', "html.parser").a
    assert _title_for(a) == "ESET APT Activity Report Q4 2022–Q1 2023"


def test_a_sitemap_lists_the_publication_pages_to_follow():
    from rozvedka.crawler import extract
    xml = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           '<url><loc>https://x.com/reports/posing-as-patriots</loc></url><url><loc>https://x.com/about</loc></url>'
           '<url><loc> https://x.com/reports/a&amp;b </loc></url></urlset>')
    assert extract(xml, "https://x.com/sitemap.xml", r"x\.com/reports/[\w&-]+$") == (
        [], [("https://x.com/reports/posing-as-patriots", ""), ("https://x.com/reports/a&b", "")])
    assert extract(xml, "https://x.com/sitemap.xml")[1] == []      # without `follow` a sitemap is not a list of reports


def test_screen_reader_notes_are_not_part_of_a_link_title():
    from bs4 import BeautifulSoup
    from rozvedka.crawler import _title_for, is_poor_title
    a = BeautifulSoup('<a href="/d/a.pdf">här pdf, 19.5 MB, öppnas i nytt fönster.</a>', "html.parser").a
    assert is_poor_title(_title_for(a), "https://x.se/d/a.pdf")
    a = BeautifulSoup('<a href="/d/a.pdf">Annual Report 2025 (opens in a new window)</a>', "html.parser").a
    assert _title_for(a) == "Annual Report 2025"
    a = BeautifulSoup('<a href="/d/a.summary.pdf">Research Summary PDF, 0.1 MB</a>', "html.parser").a
    assert _title_for(a) == "Research Summary"


def test_documents_on_the_domain_a_page_redirects_to_are_kept(monkeypatch):
    from types import SimpleNamespace
    from rozvedka import crawler
    html = '<a href="https://crisiscenter.be/files/BNRA-2023-2026_EN.pdf">Belgian National Risk Assessment 2023-2026</a>'
    monkeypatch.setattr(crawler, "get_page", lambda url, src: SimpleNamespace(status=200, content_type="text/html", text=html,
                                                                             url="https://crisiscenter.be/en/identifying-risks"))
    stored = []
    monkeypatch.setattr(crawler, "_store", lambda con, sid, pid, docs, lang, allowed, families: stored.extend(
        d["url"] for d in docs if crawler.domain_family(d["url"]) in families) or len(stored))
    src = {"id": 1, "access": "auto", "homepage": "https://crisiscentrum.be/", "agency": "NCCN", "domains": None}
    crawler.crawl_page(None, src, {"url": "https://crisiscentrum.be/en/identifying-risks", "id": 1, "lang": "en", "note": None}, {"en"})
    assert stored == ["https://crisiscenter.be/files/BNRA-2023-2026_EN.pdf"]


def test_language_names_only_in_short_link_texts_and_file_name_endings():
    from rozvedka.crawler import guess_lang
    assert guess_lang("https://v-dem.net/d/Democracy_Report_2026_Spanish_lowres.pdf", "x", "en", {"en"}) == "es"
    assert guess_lang("https://x.org/a.pdf", "Spanish", "en", {"en"}) == "es"
    # a title or file name *about* a country is not in its language
    assert guess_lang("https://x.org/a.pdf", "Spinning the Globe: Russian Information Warfare and Its Reach", "en", {"en"}) == "en"
    assert guess_lang("https://x.org/chinese-presence-caribbean.pdf", "x", "en", {"en"}) == "en"


def test_publication_page_heading_and_link_noise():
    from rozvedka.crawler import clean_link_text, page_heading
    assert page_heading('<meta property="og:title" content="Bewitched sleep: Russians views | ECFR">') == "Bewitched sleep: Russians views"
    assert page_heading("<h1> Chinese presence in the Caribbean </h1>") == "Chinese presence in the Caribbean"
    assert clean_link_text("Read more about Adapting to War") == "Adapting to War"
    assert clean_link_text("September 7, 2026 Lessons from Extremism Prevention") == "Lessons from Extremism Prevention"


def test_site_name_is_dropped_from_titles():
    from rozvedka.crawler import strip_site_name
    src = {"agency": "ICDS", "name_en": "International Centre for Defence and Security (ICDS)", "name_local": None}
    assert strip_site_name("Connecting the Ends - International Centre for Defence and Sec", src) == "Connecting the Ends"
    assert strip_site_name("A European Theory of Victory - ICDS", src) == "A European Theory of Victory"
    assert strip_site_name("Russia - the long war", src) == "Russia - the long war"


def test_pgp_signature_files_are_not_documents():
    from rozvedka.crawler import DOC_RE
    assert DOC_RE.search("https://www.jpcert.or.jp/english/doc/IR_Report2024Q4_en.pdf")
    assert not DOC_RE.search("https://www.jpcert.or.jp/english/doc/IR_Report2017Q2_en.pdf.asc")


def test_korean_file_servlet_links_are_documents():
    from rozvedka.crawler import DOC_RE
    assert DOC_RE.search("https://www.police.go.kr/component/file/ND_fileDownload.do?q_fileSn=158073&q_fileId=2a160836")
    assert not DOC_RE.search("https://www.police.go.kr/user/bbs/BD_selectBbsList.do?q_bbsCode=1113")
    # Contentful's file host: island.is links reports there, without a file extension
    assert DOC_RE.search("https://assets.ctfassets.net/8k0h54kbe6bj/4PAOb3h3QXthUt0cF3P7yU/b6bdb5/Ný%5Fskýrsla-2")
    assert not DOC_RE.search("https://images.ctfassets.net/8k0h54kbe6bj/logo.png")
    # the Slovak Interior Ministry serves files as ?<page>&subor=<id>
    assert DOC_RE.search("https://www.minv.sk/?Spravy_PT&subor=571129")
    assert not DOC_RE.search("https://www.minv.sk/?Spravy_PT")
    # Plone file objects on gov.br: the object URL and its download view serve the PDF, the /view page does not
    base = "https://www.gov.br/mj/pt-br/assuntos/sua-seguranca/seguranca-publica/estatistica/download/mapa-2026.pdf"
    assert DOC_RE.search(base + "/") and DOC_RE.search(base + "/@@download/file")
    assert not DOC_RE.search(base + "/view")


@pytest.mark.parametrize("url,expected", [
    ("https://stratcomcoe.org/pdfjs/?file=/publications/download/Report_final.pdf?zoom=page-fit",
     "https://stratcomcoe.org/publications/download/Report_final.pdf"),
    ("https://example.org/pdf.js/web/viewer.html?file=https%3A%2F%2Fexample.org%2Fa%2Fb.pdf",
     "https://example.org/a/b.pdf"),
    ("https://example.org/pdfjs/?file=/page.html", "https://example.org/pdfjs/?file=/page.html"),
    ("https://example.org/reports/annual.pdf", "https://example.org/reports/annual.pdf"),
])
def test_pdf_viewer_links_point_at_the_pdf(url, expected):
    from rozvedka.crawler import unwrap_viewer
    assert unwrap_viewer(url) == expected


def test_extract_reads_the_pdf_behind_a_viewer_link():
    html = '<a href="/pdfjs/?file=/publications/download/R.pdf?zoom=page-fit">Read online</a>'
    docs, _ = extract(html, "https://stratcomcoe.org/publications")
    assert [d["url"] for d in docs] == ["https://stratcomcoe.org/publications/download/R.pdf"]


@pytest.mark.parametrize("title", ["true true", "EN FR ES AR", "عرب 中文 Español Français Русский"])
def test_label_only_titles_are_poor(title):
    from rozvedka.crawler import is_poor_title
    assert is_poor_title(title, "https://x.org/a.pdf")


def test_real_title_not_poor():
    from rozvedka.crawler import is_poor_title
    assert not is_poor_title("World Drug Report 2025", "https://x.org/a.pdf")


def test_label_only_titles_take_the_file_name(tmp_path, monkeypatch):
    """A link text of language labels says nothing: without a title in the PDF, the file name names the report."""
    from rozvedka import db, downloader
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(downloader, "pdf_info", lambda path: (3, None))
    db.init()
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(1,'X/U','OTHER','U','other')")
        for i, title, url in [(1, "true true", "https://u.org/WDR25_Special_points_of_interest.pdf"),
                              (2, "Español", "https://u.org/2314940S.pdf"),                     # no word in the name: kept
                              (3, "World Drug Report 2025", "https://u.org/WDR25.pdf")]:        # a real title: kept
            con.execute("INSERT INTO documents(id,source_id,url,title,status,local_path) VALUES(?,1,?,?,'downloaded','f.pdf')",
                        (i, url, title))
    assert downloader.improve_titles() == 1
    with db.session() as con:
        titles = [r[0] for r in con.execute("SELECT title FROM documents ORDER BY id")]
    assert titles == ["WDR25 Special points of interest", "Español", "World Drug Report 2025"]
