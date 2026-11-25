"""Per-user settings (settings/latchwork_settings.json, not in git) and where the repository
and its data folder are."""
import json
import os

# src/latchwork/settings.py -> the repository folder
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
