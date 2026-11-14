"""Find the Vexo Open kit (never edited, never committed) and make its library importable.

Looked for, in this order: <repo root>/vexo-open-kit, one level up, then the folder named
by the VEXO_KIT environment variable.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KIT_URL = "https://github.com/VexoAI-Org/vexo-open-kit.git"


def find():
    places = [REPO_ROOT / "vexo-open-kit", REPO_ROOT.parent / "vexo-open-kit"]
    if os.environ.get("VEXO_KIT"):
        places.append(Path(os.environ["VEXO_KIT"]))
    for place in places:
        if (place / "python" / "vexo_open").is_dir():
            return place
    return None


def use():
    """Put the kit's library on Python's path. Ends the program with one clear sentence
    when the kit is missing."""
    kit = find()
    if kit is None:
        raise SystemExit("The band kit was not found. In %s run:  git clone %s   (or set VEXO_KIT to its folder)."
                         % (REPO_ROOT, KIT_URL))
    library = str(kit / "python")
    if library not in sys.path:
        sys.path.insert(0, library)
    return kit
