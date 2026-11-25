"""Per-user settings (settings/latchwork_settings.json, not in git) and where the repository
and its data folder are."""
import json
import os

# src/latchwork/settings.py -> the repository folder
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
DEFAULT_PALETTE = os.path.join(DATA_DIR, "palette.csv")
SETTINGS = os.path.join(ROOT, "settings", "latchwork_settings.json")  # per-user, not in git
OLD_SETTINGS = os.path.join(ROOT, "latchwork_settings.json")          # before the data/ move


def _migrate_settings():
    """Move settings from the old repo-root location (before data/ and settings/ existed) and
    point the old root palette.csv at data/palette.csv."""
    if os.path.exists(SETTINGS) or not os.path.exists(OLD_SETTINGS):
        return
    try:
        with open(OLD_SETTINGS, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    old = os.path.normcase(os.path.join(ROOT, "palette.csv"))

    def fix(q):
        return DEFAULT_PALETTE if isinstance(q, str) and os.path.normcase(q) == old else q
    if isinstance(data, dict):
        if "palette" in data:
            data["palette"] = fix(data["palette"])
        if isinstance(data.get("palettes"), list):
            data["palettes"] = [fix(q) for q in data["palettes"]]
        write_settings(data)
        if os.path.exists(SETTINGS):
            os.remove(OLD_SETTINGS)


def read_settings():
    _migrate_settings()
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
