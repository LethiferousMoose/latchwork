"""Build a portable Latchwork for this OS with PyInstaller (a build tool only; the app itself
needs nothing beyond the standard library).

    python tools/build.py                  build; the version comes from git (see version.py)
    python tools/build.py --version 1.2.0  build as that version (the Release workflow does this)
    python tools/build.py next minor       print the next release version (major/minor/patch)

Needs PyInstaller: pip install pyinstaller (best in a virtual environment). The result is
dist/Latchwork-<version>-<os>-<arch>.zip (.tar.gz on Linux): a folder laid out like the
repository, with the program, data/ (the shipped palette, without photos) and an empty
settings/ next to it, so it runs from wherever it's unzipped. In GitHub Actions the archive's
path is also written to GITHUB_OUTPUT as `archive`.
"""
import argparse
import datetime
import os
import platform
import shutil
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from latchwork import version as v  # noqa: E402

PACKAGE = os.path.join(ROOT, "src", "latchwork")
STAMP = os.path.join(PACKAGE, "_build.py")
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")


def system():
    """'windows-x64', 'macos-arm64', 'linux-x64'..."""
    name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    arch = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(arch, arch)
    return "%s-%s" % (name, arch)


def stamp(version):
    """Write _build.py, so the packaged app knows its version and build without git."""
    now = datetime.datetime.now(datetime.timezone.utc)
    with open(STAMP, "w", encoding="utf-8") as fh:
        fh.write('"""Written by tools/build.py; not in git."""\n')
        fh.write("VERSION = %r\n" % version)
        fh.write("COMMIT = %r\n" % (v.git("rev-parse", "--short", "HEAD") or "unknown"))
        fh.write("DATE = %r\n" % ("%s %d, %d" % (now.strftime("%b"), now.day, now.year)))


def pyinstaller():
    """One-folder, windowed build into build/dist (Latchwork/, and Latchwork.app on macOS).
    The entry is a small script of its own: latchwork.py has the package's name, so analysing
    it would find the script instead of the package (and the build needs no Python checks)."""
    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(BUILD)
    entry = os.path.join(BUILD, "start_latchwork.py")
    with open(entry, "w", encoding="utf-8") as fh:
        fh.write("from latchwork.app import main\n\nmain()\n")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "Latchwork",
        "--paths", os.path.join(ROOT, "src"),
        "--hidden-import", "latchwork._build",
        "--add-data", "%s%slatchwork" % (os.path.join(PACKAGE, "pattern_template.html"),
                                         os.pathsep),
        "--distpath", os.path.join(BUILD, "dist"), "--workpath", os.path.join(BUILD, "work"),
        "--specpath", BUILD,
        entry], check=True)
    return os.path.join(BUILD, "dist")


def assemble(built, version):
    """dist/Latchwork-<version>-<system>/: the program, data/, settings/, README and LICENSE."""
    name = "Latchwork-%s-%s" % (version, system())
    folder = os.path.join(DIST, name)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    if sys.platform == "darwin":
        shutil.copytree(os.path.join(built, "Latchwork.app"),
                        os.path.join(folder, "Latchwork.app"), symlinks=True)
    else:
        src = os.path.join(built, "Latchwork")
        for item in os.listdir(src):
            path = os.path.join(src, item)
            if os.path.isdir(path):
                shutil.copytree(path, os.path.join(folder, item), symlinks=True)
            else:
                shutil.copy2(path, folder)
    data = os.path.join(folder, "data")
    os.makedirs(data)
    for item in os.listdir(os.path.join(ROOT, "data")):   # the palette files; not the photos
        path = os.path.join(ROOT, "data", item)
        if os.path.isfile(path):
            shutil.copy2(path, data)
    os.makedirs(os.path.join(folder, "settings"))
    for doc in ("README.md", "LICENSE"):
        shutil.copy2(os.path.join(ROOT, doc), folder)
    return folder


def archive(folder):
    """A zip (keeping the macOS app's symlinks and permissions), or tar.gz on Linux."""
    base = os.path.basename(folder)
    if sys.platform == "darwin":
        out = folder + ".zip"
        subprocess.run(["ditto", "-c", "-k", "--keepParent", folder, out], check=True)
    elif sys.platform == "win32":
        out = shutil.make_archive(folder, "zip", DIST, base)
    else:
        out = folder + ".tar.gz"
        with tarfile.open(out, "w:gz") as tar:
            tar.add(folder, arcname=base)
    return out


def build(version):
    if os.path.exists(STAMP):
        os.remove(STAMP)
    stamp(version)
    try:
        built = pyinstaller()
    finally:
        os.remove(STAMP)     # running from source asks git again
    out = archive(assemble(built, version))
    print("Built", out)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write("archive=%s\n" % out)
    return out


def next_release(part):
    """The version the next release gets; refuses when this commit is already released."""
    last = v.last_release()
    if last and v.git("describe", "--tags", "--exact-match", "--match", "v[0-9]*", "HEAD"):
        sys.exit("This commit is already released as v%s." % last)
    return v.bump(last, part)


def main():
    if sys.argv[1:2] == ["next"]:
        parser = argparse.ArgumentParser(prog="build.py next")
        parser.add_argument("next")
        parser.add_argument("part", choices=("major", "minor", "patch"))
        print(next_release(parser.parse_args().part))
        return
    parser = argparse.ArgumentParser(description="Build a portable Latchwork for this OS.")
    parser.add_argument("--version", help="the version to build as (default: from git)")
    args = parser.parse_args()
    version = args.version or v.git_version()
    if not version:
        sys.exit("No version: run from a git checkout or pass --version.")
    build(version)


if __name__ == "__main__":
    main()
