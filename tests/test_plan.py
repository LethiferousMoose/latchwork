import csv
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from latchwork import pixelart  # noqa: E402
from latchwork import plan as pl  # noqa: E402
from latchwork.palette import Brand, Yarn  # noqa: E402
from latchwork.project import Project  # noqa: E402
from test_project import RGB_ROWS, make_png  # noqa: E402


class TestMath(unittest.TestCase):
    def test_spare_and_bags(self):
        self.assertEqual(pl.with_spare(320, 0), 320)
        self.assertEqual(pl.with_spare(320, 10), 352)
        self.assertEqual(pl.with_spare(100, 5), 105)
        self.assertEqual(pl.with_spare(101, 5), 107)   # 106.05 rounds up
        line = pl.YarnLine("Light Teal", "#53AACC", "palette.csv", "Hershner's", 320)
        for count, bags in ((1, 1), (320, 1), (321, 2), (640, 2), (641, 3)):
            line.count = count
            self.assertEqual(line.need(0)[1], bags, count)
        line.count = 300
        self.assertEqual(line.need(10)[:2], (330, 2))
        rh = pl.YarnLine("Gold", "#D4A017", "", "Red Heart", None)
        rh.count = 300
        self.assertEqual(rh.need(10), (330, None, "330 pieces"))

    def test_sizes(self):
        p = Project.from_image_bytes(make_png(3, 2, RGB_ROWS, 2), "t.png", "t.latchwork")
        plan = pl.Plan(p)
        self.assertEqual(plan.canvas_cells, (3 + 6, 2 + 12))
        self.assertAlmostEqual(plan.finished_in[0], 3 / 3.75)
        self.assertAlmostEqual(plan.canvas_in[1], 14 / 3.75)
        # a 150 x 120 rug: 40 x 32 in finished, 156 x 132 holes = 41.6 x 35.2 in canvas
        plan.width, plan.height = 150, 120
        self.assertEqual(tuple(round(v, 1) for v in plan.finished_in), (40.0, 32.0))
        self.assertEqual(plan.canvas_cells, (156, 132))
        self.assertEqual(tuple(round(v, 1) for v in plan.canvas_in), (41.6, 35.2))

    def test_custom_canvas(self):
        p = Project.from_image_bytes(make_png(3, 2, RGB_ROWS, 2), "t.png", "t.latchwork")
        p.settings.update({"holes_per_inch": 5, "border_side": 2, "border_top": 0,
                           "border_bottom": "1"})
        plan = pl.Plan(p)
        self.assertEqual(plan.canvas_cells, (3 + 4, 2 + 1))
        self.assertAlmostEqual(plan.finished_in[0], 3 / 5)
        p.settings["holes_per_inch"] = "nonsense"
        self.assertEqual(pl.Plan(p).canvas["holes_per_inch"], 3.75)


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.p = Project.from_image_bytes(make_png(3, 2, RGB_ROWS, 2), "t.png",
                                          os.path.join(self.dir, "t.latchwork"))
        # colors: #FFFFFF x1, #C86432 x2, #0A141E x2, #000000 x1
        self.brands = [Brand("Hershner's", 320), Brand("Red Heart")]
        self.navy = Yarn("Navy", (20, 25, 60), brand="Red Heart")
        self.p.assign("#0A141E", self.navy, "palette.csv", self.brands)
        self.p.assign("#000000", self.navy, "palette.csv", self.brands)      # merged
        self.p.assign("#C86432", Yarn("Rust", (180, 80, 40), brand="Hershner's"), "sky.csv",
                      self.brands)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_lines_merged_unassigned(self):
        plan = pl.Plan(self.p)
        self.assertEqual([(l.label, l.count, l.pack, l.colors) for l in plan.lines],
                         [("Navy (Red Heart)", 3, None, ["#0A141E", "#000000"]),
                          ("Rust (Hershner's)", 2, 320, ["#C86432"])])
        self.assertEqual([l.name for l in plan.merged], ["Navy"])
        self.assertEqual(([c.hex for c in plan.unassigned], plan.unassigned_count), (["#FFFFFF"], 1))
        self.assertEqual((plan.assigned_count, plan.total_packs, plan.total_pieces_to_cut), (5, 1, 3))

    def test_palette_pack_size_wins_over_snapshot(self):
        def resolve(name, brand):          # the palette now sells Navy in packs of 2
            return (True, 2) if name == "Navy" else (False, None)
        plan = pl.Plan(self.p, resolve)
        navy = [l for l in plan.lines if l.name == "Navy"][0]
        self.assertEqual(navy.need(0), (3, 2, "2 packs"))
        rust = [l for l in plan.lines if l.name == "Rust"][0]
        self.assertEqual(rust.pack, 320)   # not in the palette: the saved snapshot is used

    def test_suggestions_are_not_counted(self):
        self.p.suggest([Yarn("White", (255, 255, 255))], "x.csv")
        self.assertEqual([c.hex for c in pl.Plan(self.p).unassigned], ["#FFFFFF"])

    def test_yarn_list_csv(self):
        self.p.settings["spare_percent"] = 10
        path = os.path.join(self.dir, "list.csv")
        pl.write_yarn_list(pl.Plan(self.p), path)
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0][:4], ["yarn", "brand", "hex", "count"])
        self.assertEqual(rows[1], ["Navy", "Red Heart", "#14193C", "3", "10", "4", "", "", "4",
                                   "#0A141E #000000", "palette.csv"])
        self.assertEqual(rows[2][:9], ["Rust", "Hershner's", "#B45028", "2", "10", "3", "320",
                                       "1", ""])
        total = [r for r in rows if r and r[0] == "TOTAL"][0]
        self.assertEqual(total[3], "5")
        self.assertTrue(any(r and r[0] == "UNASSIGNED" for r in rows))
        self.assertTrue(any(r and r[0] == "canvas to cut" and r[1] == "9 x 14 holes" for r in rows))

    def test_preview_pixels_and_png(self):
        px = pl.preview_pixels(self.p)
        self.assertEqual(px[3], (255, 255, 255, 255))      # unassigned stays original
        self.assertEqual(px[0], (20, 25, 60, 255))         # #0A141E -> Navy
        self.assertEqual(px[4], (20, 25, 60, 255))         # #000000 -> Navy (merged)
        self.assertEqual(px[1], (180, 80, 40, 255))        # orange -> Rust
        path = os.path.join(self.dir, "prev.png")
        pl.write_preview_png(self.p, path)
        with open(path, "rb") as fh:
            self.assertEqual(pixelart.decode_png(fh.read()).pixels, px)


if __name__ == "__main__":
    unittest.main()
