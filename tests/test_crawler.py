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
