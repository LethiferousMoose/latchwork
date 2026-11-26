"""Per-user settings (settings/latchwork_settings.json, not in git) and where the repository
and its data folder are."""
import json
import os
import sys


def app_folder():
    """The folder that holds data/ and settings/: the repository when running from source; next
    to the program in a packaged (PyInstaller) build, which is a portable folder laid out like
    the repository. On macOS that's the folder holding Latchwork.app."""
    if getattr(sys, "frozen", False):
        here = os.path.dirname(os.path.abspath(sys.executable))
        marker = os.sep + os.path.join("Contents", "MacOS")
        if here.endswith(marker) and here[:-len(marker)].endswith(".app"):
            here = os.path.dirname(here[:-len(marker)])
        return here
    # src/latchwork/settings.py -> the repository folder
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


ROOT = app_folder()
DATA_DIR = os.path.join(ROOT, "data")
DEFAULT_PALETTE = os.path.join(DATA_DIR, "palette.csv")
SETTINGS = os.path.join(ROOT, "settings", "latchwork_settings.json")  # per-user, not in git


def read_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_settings(data):
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass  # remembering is a convenience; never fail over it
