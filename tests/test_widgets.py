import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from latchwork.widgets import free_name  # noqa: E402


class FreeNameTest(unittest.TestCase):
    def test_free_name(self):
        with tempfile.TemporaryDirectory() as d:
            def touch(n):
                open(os.path.join(d, n), "w").close()
            self.assertEqual(free_name(d, "Ninji-pattern.html"), "Ninji-pattern.html")
            touch("Ninji-pattern.html")
            self.assertEqual(free_name(d, "Ninji-pattern.html"), "Ninji-pattern (1).html")
            touch("Ninji-pattern (1).html")
            self.assertEqual(free_name(d, "Ninji-pattern.html"), "Ninji-pattern (2).html")
            # a file that brings another along: both must be free
            touch("palette-yarns.brands.csv")
            brands = lambda p: [p[:-4] + ".brands.csv"]
            self.assertEqual(free_name(d, "palette-yarns.csv", brands), "palette-yarns (1).csv")


if __name__ == "__main__":
    unittest.main()
