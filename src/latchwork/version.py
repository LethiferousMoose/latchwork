"""Latchwork's version and which build this is. No Tk.

VERSION is the release number (SemVer: 1.1.0 adds features, 1.0.1 fixes, 2.0.0 if older
versions can't open new project files). Tag releases "v" + VERSION. A packaged build has a
_build.py stamped in by tools/build.py (git-ignored); running from source asks git instead."""
import os
import subprocess
import sys

VERSION = "1.0.0"
REPO_URL = "https://github.com/LethiferousMoose/latchwork"


def build():
    """'Built Nov 25, 2026 from a1b2c3d' for a packaged build; from source 'From source, commit
    a1b2c3d' (plus ' with local changes'), or just 'From source' without git."""
    try:
        from ._build import COMMIT, DATE
        return "Built %s from %s" % (DATE, COMMIT)
    except ImportError:
        pass
    commit = git("rev-parse", "--short", "HEAD")
    if not commit:
        return "From source"
    changed = git("status", "--porcelain", "--untracked-files=no")
    return "From source, commit %s%s" % (commit, " with local changes" if changed else "")


def git(*args):
    """git's output in the repository folder, or None (no git, not a repository, a build)."""
    if getattr(sys, "frozen", False):
        return None
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        out = subprocess.run(
            ["git", "-C", repo] + list(args), capture_output=True, text=True, timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))   # no console flash
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None
