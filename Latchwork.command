#!/bin/sh
# Double-click in Finder to start Latchwork on macOS.
# (First time: if macOS blocks it, right-click > Open, or run: chmod +x Latchwork.command)
cd "$(dirname "$0")" || exit 1

for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info[0] != 3)' 2>/dev/null; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "Python 3 was not found."
    echo "Install it from https://www.python.org/downloads/ (includes Tkinter)."
    printf "Press Return to close."; read -r _
    exit 1
fi

if ! "$PY" latchwork.py --check; then
    printf "Press Return to close."; read -r _
    exit 1
fi

# Start in the background so this Terminal window can be closed.
nohup "$PY" latchwork.py >/dev/null 2>&1 &
exit 0
