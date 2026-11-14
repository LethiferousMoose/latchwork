"""Start Latchwork: python latchwork.py

The app lives in src/latchwork/; this launcher puts src/ on the path first.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from latchwork.app import main  # noqa: E402

if __name__ == "__main__":
    main()
