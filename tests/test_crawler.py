"""Unit tests for the crawler's pure heuristics (no network)."""
import pytest

from rozvedka.crawler import (GENERIC_TITLES, LOW_RELEVANCE_RE, extract, guess_lang, guess_year,
                              humanize_filename)


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


def test_humanize_filename():
    assert humanize_filename("https://x/content/vyrocni-zprava-archivu_bis-2024-web.pdf") == \
        "vyrocni zprava archivu bis 2024 web"


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
