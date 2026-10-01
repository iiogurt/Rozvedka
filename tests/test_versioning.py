"""Version bumping by significance and changelog release sections."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from bump_version import bump, readme_badge, release_changelog  # noqa: E402

from rozvedka import __version__, build_version  # noqa: E402


@pytest.mark.parametrize("version,level,expected", [
    ("0.9.0", "patch", "0.9.1"),
    ("0.9.1", "minor", "0.10.0"),     # minor resets patch; 0.9 → 0.10, not 1.0
    ("0.10.3", "major", "1.0.0"),
    ("1.4.2", "patch", "1.4.3"),
])
def test_bump(version, level, expected):
    assert bump(version, level) == expected


CHANGELOG = """# Changelog

## [Unreleased]

### Fixed
- Something small.

## [0.9.0] – 2026-09-30

### Added
- Earlier things.

[Unreleased]: https://github.com/iiogurt/Rozvedka/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/iiogurt/Rozvedka/compare/v0.8.0...v0.9.0
"""


def test_release_changelog_moves_notes_and_links():
    out = release_changelog(CHANGELOG, "0.9.0", "0.9.1", "2026-10-01")
    assert "## [Unreleased]\n\n## [0.9.1] – 2026-10-01\n\n### Fixed\n- Something small." in out
    assert "[Unreleased]: https://github.com/iiogurt/Rozvedka/compare/v0.9.1...HEAD" in out
    assert "[0.9.1]: https://github.com/iiogurt/Rozvedka/compare/v0.9.0...v0.9.1" in out
    assert out.count("## [0.9.0]") == 1


def test_release_refuses_empty_unreleased():
    empty = CHANGELOG.replace("### Fixed\n- Something small.\n", "")
    with pytest.raises(SystemExit):
        release_changelog(empty, "0.9.0", "0.9.1", "2026-10-01")


def test_build_version_starts_with_release_version():
    assert build_version() == __version__ or build_version().startswith(__version__ + "+")


def test_readme_badge_follows_version():
    text = "![version](https://img.shields.io/badge/version-0.11.0-1f4e79)\n![python](https://img.shields.io/badge/python-3.13-3776ab)"
    out = readme_badge(text, "0.12.0")
    assert "badge/version-0.12.0-1f4e79" in out and "python-3.13" in out


def test_readme_badge_matches_current_version():
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    assert f"badge/version-{__version__}-" in readme
