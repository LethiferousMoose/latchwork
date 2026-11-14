#!/bin/sh
# Start Latchwork on Linux: ./latchwork.sh  (or double-click, if your file manager runs scripts)
cd "$(dirname "$0")" || exit 1

for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info[0] != 3)' 2>/dev/null; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "Python 3 was not found. Install it with your package manager, e.g."
    echo "  sudo apt install python3 python3-tk"
    exit 1
fi

"$PY" latchwork.py --check || exit 1
exec "$PY" latchwork.py "$@"
