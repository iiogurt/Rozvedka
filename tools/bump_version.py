"""Cut a release: bump the version by significance and move the Unreleased changelog notes into it.

    python3 tools/bump_version.py patch      # 0.9.0 → 0.9.1   fixes, sources, keywords, visual tweaks, docs
    python3 tools/bump_version.py minor      # 0.9.1 → 0.10.0  new capability (page, filter, command, data field)
    python3 tools/bump_version.py major      # 0.10.0 → 1.0.0  incompatible change needing manual migration
    python3 tools/bump_version.py patch --dry-run

It edits rozvedka/__init__.py and CHANGELOG.md only. Commit, open a PR, merge, then tag the merge commit:
    git tag -a v<new> -m "Rozvedka <new>" && git push origin v<new>
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "rozvedka" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
REPO = "https://github.com/iiogurt/Rozvedka"


def bump(version: str, level: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(level)


def release_changelog(text: str, old: str, new: str, date: str) -> str:
    """Move the notes under '## [Unreleased]' into a new '## [new] – date' section and update the links."""
    m = re.search(r"^## \[Unreleased\]\n(.*?)(?=^## \[)", text, re.S | re.M)
    if not m or not m.group(1).strip():
        raise SystemExit("CHANGELOG.md: nothing under ## [Unreleased] – describe the changes first")
    notes = m.group(1).strip()
    text = text[:m.start()] + f"## [Unreleased]\n\n## [{new}] – {date}\n\n{notes}\n\n" + text[m.end():]
    text = re.sub(r"^\[Unreleased\]: .*$",
                  f"[Unreleased]: {REPO}/compare/v{new}...HEAD\n[{new}]: {REPO}/compare/v{old}...v{new}",
                  text, count=1, flags=re.M)
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("level", choices=["patch", "minor", "major"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    init = INIT.read_text(encoding="utf-8")
    old = re.search(r'^__version__ = "(\d+\.\d+\.\d+)"', init, re.M).group(1)
    new = bump(old, a.level)
    changelog = release_changelog(CHANGELOG.read_text(encoding="utf-8"), old, new, dt.date.today().isoformat())
    if a.dry_run:
        print(f"{old} → {new} ({a.level}); CHANGELOG and __init__.py would be updated")
        return
    INIT.write_text(re.sub(r'^__version__ = "[^"]+"', f'__version__ = "{new}"', init, count=1, flags=re.M), encoding="utf-8")
    CHANGELOG.write_text(changelog, encoding="utf-8")
    print(f"{old} → {new} ({a.level})")
    print(f"next: commit, open a PR, merge, then: git tag -a v{new} -m 'Rozvedka {new}' <merge commit> && git push origin v{new}")


if __name__ == "__main__":
    sys.exit(main())
