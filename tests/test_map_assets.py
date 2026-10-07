"""Front-end rules of the maps that broke once and are easy to break again."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "rozvedka" / "static"


def test_hover_cards_close_at_once():
    """Leaflet hides a closing card by setting its opacity to 0 and removes it 200 ms later; CSS that forces the
    opacity keeps closing cards visible, so several pile up when the pointer moves quickly."""
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert not re.search(r"\.leaflet-tooltip[^{]*\{[^}]*opacity:[^;}]*!important", css)
    for js in ("map.js", "map_democracy.js", "mentions.js"):
        text = (STATIC / js).read_text(encoding="utf-8")
        assert "L.Tooltip.mergeOptions({ opacity: 1 })" in text, js
        assert text.index('"use strict"') < text.index("L.Tooltip.mergeOptions"), js
