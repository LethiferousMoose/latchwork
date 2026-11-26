"""Latchwork's version and which build this is. No Tk.

The git tag is the version (like Gradle's axion-release): a release is tagged v1.2.0 by the
Release workflow, and every build in between is a dev version of the next patch,
1.2.1.dev3+g2a6788c (3 commits after v1.2.0, PEP 440). SemVer: features bump the middle number,
fixes the last, and the first only if older versions can't open new project files.

A packaged build has _build.py stamped in by tools/build.py (git-ignored), so it knows its
version without git; running from source asks git."""
import os
import re
import subprocess
import sys

REPO_URL = "https://github.com/LethiferousMoose/latchwork"
UNKNOWN = "unknown"
_DESCRIBE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)-(\d+)-g([0-9a-f]+)(-dirty)?$")


def from_describe(describe, commits=0, sha=""):
    """The version for `git describe --tags --long --dirty --match v*` output, or with no
    release tag yet (describe None) for `commits` commits at sha.
    'v1.2.0-0-gabc1234' -> '1.2.0'; 'v1.2.0-3-gabc1234' -> '1.2.1.dev3+gabc1234';
    a '-dirty' tree adds '.dirty' to the local part; no tag -> '0.0.1.devN+g<sha>'."""
    m = _DESCRIBE.match(describe or "")
    if m:
        major, minor, patch, n, sha, dirty = m.groups()
        major, minor, patch, n = int(major), int(minor), int(patch), int(n)
    else:
        major, minor, patch, n, dirty = 0, 0, 0, max(1, commits), False
    if n == 0 and not dirty:
        return "%d.%d.%d" % (major, minor, patch)
    if n == 0:   # on the release commit, with local changes
        return "%d.%d.%d+g%s.dirty" % (major, minor, patch, sha)
    local = "g%s%s" % (sha, ".dirty" if dirty else "") if sha else ""
    return "%d.%d.%d.dev%d%s" % (major, minor, patch + 1, n, "+" + local if local else "")


def bump(release, part):
    """The next release after '1.2.3' (or None, no release yet): part is 'major', 'minor' or
    'patch'. From nothing, major gives 1.0.0."""
    major, minor, patch = (int(x) for x in (release or "0.0.0").split("."))
    if part == "major":
        return "%d.0.0" % (major + 1)
    if part == "minor":
        return "%d.%d.0" % (major, minor + 1)
    if part == "patch":
        return "%d.%d.%d" % (major, minor, patch + 1)
    raise ValueError("bump major, minor or patch, not %r" % part)


def git(*args):
    """git's output in the repository folder, or None (no git, not a repository, a build)."""
    if getattr(sys, "frozen", False):
        return None
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        out = subprocess.run(
            ["git", "-C", repo] + list(args), capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))   # no console flash
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def git_version():
    """The version from git (see from_describe), or None without git."""
    sha = git("rev-parse", "--short", "HEAD")
    if not sha:
        return None
    describe = git("describe", "--tags", "--long", "--dirty", "--match", "v[0-9]*")
    commits = int(git("rev-list", "--count", "HEAD") or 0)
    if not describe and git("status", "--porcelain", "--untracked-files=no"):
        sha += ".dirty"
    return from_describe(describe, commits, sha)


def last_release():
    """The newest release tag's version ('1.2.0'), or None."""
    tag = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*")
    return tag[1:] if tag and _DESCRIBE.match(tag + "-0-g0") else None


def _stamp():
    try:
        from . import _build
        return _build
    except ImportError:
        return None


def version():
    """'1.2.0', '1.2.1.dev3+gabc1234', or 'unknown' (source without git)."""
    stamp = _stamp()
    if stamp:
        return stamp.VERSION
    return git_version() or UNKNOWN


def build():
    """The About window's second line: 'Built Nov 25, 2026 from abc1234' for a packaged build;
    from source 'From source, commit abc1234' (plus ' with local changes'), or 'From source'."""
    stamp = _stamp()
    if stamp:
        return "Built %s from %s" % (stamp.DATE, stamp.COMMIT)
    commit = git("rev-parse", "--short", "HEAD")
    if not commit:
        return "From source"
    changed = git("status", "--porcelain", "--untracked-files=no")
    return "From source, commit %s%s" % (commit, " with local changes" if changed else "")
