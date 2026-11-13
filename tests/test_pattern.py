import base64
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pattern  # noqa: E402
from palette import Yarn  # noqa: E402
from project import Project  # noqa: E402
from test_project import make_png  # noqa: E402

# 3x2: white, rust, navy / navy, black, transparent
ROWS = [bytes([255, 255, 255, 255, 200, 100, 50, 255, 10, 20, 30, 255]),
        bytes([10, 20, 30, 255, 0, 0, 0, 255, 0, 0, 0, 0])]


class TestPattern(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.p = Project.from_image_bytes(make_png(3, 2, ROWS, 6), "t.png",
                                          os.path.join(self.dir, "My <Rug> & co.latchwork"))
        navy = Yarn("Navy RH", (20, 25, 60))
        self.p.assign("#0A141E", navy, "palette.csv")
        self.p.assign("#000000", navy, "palette.csv")
        self.p.assign("#C86432", Yarn("Rust", (180, 80, 40)), "palette.csv")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def cells(self, data):
        raw = base64.b64decode(data["cells"])
        return [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]

    def test_data(self):
        d = pattern.build_data(self.p)
        self.assertEqual((d["width"], d["height"], d["knots"]), (3, 2, 5))
        names = [y["name"] for y in d["yarns"]]
        self.assertEqual(names, ["Navy RH", "Rust", "Unassigned #FFFFFF"])   # most used first
        self.assertTrue(d["yarns"][2]["unassigned"])
        self.assertEqual(d["yarns"][0]["ink"], "#FFFFFF")                      # dark yarn, white symbol
        self.assertEqual(d["yarns"][0]["need"], "3 pieces")
        self.assertEqual(self.cells(d), [2, 1, 0, 0, 0, pattern.TRANSPARENT])

    def test_html_embeds_data_safely(self):
        self.p.assign("#FFFFFF", Yarn("Snow </script> White", (250, 250, 250)), "palette.csv")
        html = pattern.render_html(self.p)
        self.assertNotIn(pattern.PLACEHOLDER, html)
        self.assertNotIn("__LATCHWORK_TITLE__", html)
        self.assertIn("<title>My &lt;Rug> &amp; co · Latchwork pattern</title>", html)
        m = re.search(r'<script id="latchwork-data" type="application/json">(.*?)</script>', html, re.S)
        d = json.loads(m.group(1))
        self.assertIn("Snow </script> White", [y["name"] for y in d["yarns"]])
        self.assertEqual(html.count("</script>"), 2)    # the data didn't close its tag early

    def test_export_file(self):
        out = os.path.join(self.dir, "out.html")
        pattern.export_pattern(self.p, out)
        with open(out, encoding="utf-8") as fh:
            self.assertIn('"name":"My <Rug> & co"', fh.read())
        self.assertFalse([f for f in os.listdir(self.dir) if f.endswith(".tmp")])


if __name__ == "__main__":
    unittest.main()
