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
