"""Rozvedka – local library of public security, resilience and preparedness reports."""
import subprocess
from functools import lru_cache
from pathlib import Path

# Single source of the release version (Semantic Versioning, https://semver.org).
# Do not edit by hand: run `python3 tools/bump_version.py patch|minor|major` (see CHANGELOG.md, "Versioning").
__version__ = "0.9.1"


@lru_cache(maxsize=1)
def build_version() -> str:
    """Release version plus git build metadata between releases.

    '0.9.1'                   exactly the tagged release v0.9.1
    '0.9.1+3.g1a2b3c4'        3 commits after v0.9.1, at commit 1a2b3c4
    '0.9.1+3.g1a2b3c4.dirty'  same, with uncommitted local changes
    Falls back to __version__ when git or the tags are unavailable (e.g. an exported copy).
    """
    root = Path(__file__).resolve().parent.parent
    try:
        out = subprocess.run(["git", "-C", str(root), "describe", "--tags", "--long", "--dirty", "--match", "v*"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return __version__
    desc = out.stdout.strip()                       # v0.9.1-3-g1a2b3c4[-dirty]
    if out.returncode != 0 or not desc.startswith("v"):
        return __version__
    dirty = desc.endswith("-dirty")
    tag, ahead, commit = desc.removesuffix("-dirty").rsplit("-", 2)
    suffix = ".dirty" if dirty else ""
    if tag[1:] != __version__:                      # version bumped, release not tagged yet
        return f"{__version__}+{commit}{suffix}"
    if ahead == "0" and not dirty:
        return __version__
    return f"{__version__}+{ahead}.{commit}{suffix}"
