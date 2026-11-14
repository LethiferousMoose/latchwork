"""Start Latchwork: python latchwork.py (or the Latchwork.bat / .command / .sh wrappers).

The app lives in src/latchwork/; this launcher checks Python and Tkinter, puts src/ on the path
and starts it.
"""
import os
import sys

MIN_PYTHON = (3, 8)

TK_HELP = {
    "win32": "Reinstall Python from https://www.python.org/downloads/ and keep "
             "\"tcl/tk and IDLE\" ticked.",
    "darwin": "Install Python from https://www.python.org/downloads/ (includes Tkinter), "
              "or with Homebrew: brew install python-tk",
    "linux": "Install Tkinter with your package manager, e.g. sudo apt install python3-tk "
             "(Debian/Ubuntu), sudo dnf install python3-tkinter (Fedora), "
             "sudo pacman -S tk (Arch).",
}


def fail(message):
    sys.stderr.write("Latchwork can't start:\n%s\n" % message)
    sys.exit(1)


def check():
    if sys.version_info < MIN_PYTHON:
        fail("Python %d.%d or newer is needed (this is %d.%d). Get it from "
             "https://www.python.org/downloads/" % (MIN_PYTHON + sys.version_info[:2]))
    try:
        import tkinter  # noqa: F401
    except ImportError:
        platform = "linux" if sys.platform.startswith("linux") else sys.platform
        fail("Tkinter (Python's built-in GUI toolkit) is missing.\n" +
             TK_HELP.get(platform, TK_HELP["linux"]))


if __name__ == "__main__":
    check()
    if "--check" in sys.argv:      # used by the wrappers before starting without a console
        sys.exit(0)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
    from latchwork.app import main
    main()
