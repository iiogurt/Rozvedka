from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "sources" / "registry.yaml"
DATA = Path(os.environ.get("ROZVEDKA_DATA", ROOT / "data"))
FILES = DATA / "files"
DB_PATH = Path(os.environ.get("ROZVEDKA_DB") or DATA / "rozvedka.db")   # ROZVEDKA_DB: another database file

USER_AGENT = "Mozilla/5.0 (X11; Linux aarch64; rv:128.0) Gecko/20100101 Firefox/128.0"
HOST_DELAY = 2.0          # seconds between requests to the same host
TIMEOUT = 40.0
MAX_FILE_MB = 600         # IPCC full assessment reports are 200–450 MB
FOLLOW_LIMIT = 25         # sub-pages followed per page when it has no direct documents
