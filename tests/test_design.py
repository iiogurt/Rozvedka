"""Design tokens and icons: one place for chart colours, and every icon a template asks for exists."""
import re
from pathlib import Path

STATIC = Path(__file__).parent.parent / "rozvedka" / "static"
TEMPLATES = Path(__file__).parent.parent / "rozvedka" / "templates"


def _block(css: str, selector: str) -> str:
    start = css.index(selector)
    return css[start:css.index("}", start)]


def test_chart_colours_are_defined_for_both_themes():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for selector in (":root {\n  --s1", ':root[data-theme="dark"] {\n  --cat-1'):
        block = _block(css, selector)
        for i in range(1, 9):
            assert f"--cat-{i}:" in block
        for i in range(1, 8):
            assert f"--seq-{i}:" in block
        assert "--nodata:" in block and "--thin:" in block


def test_charts_read_their_colours_from_the_tokens():
    for js in ("trends.js", "network.js", "mentions.js"):
        text = (STATIC / js).read_text(encoding="utf-8")
        assert "rzTokens" in text and not re.search(r'"#(?:1b2a3d|cde2fb|2a78d6)"', text), js


def test_every_icon_used_exists_in_the_sprite():
    sprite = set(re.findall(r'<symbol id="([\w-]+)"', (STATIC / "icons.svg").read_text(encoding="utf-8")))
    used = set()
    for f in TEMPLATES.glob("*.html"):
        used |= set(re.findall(r'ico\("([\w-]+)"\)', f.read_text(encoding="utf-8")))
    assert used and used <= sprite, used - sprite
