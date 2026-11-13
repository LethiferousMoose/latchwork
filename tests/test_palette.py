import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import palette as pal  # noqa: E402
from palette import Entry, Yarn  # noqa: E402


def bank():
    return pal.sort_yarns([
        Yarn("Sunny Yellow", (254, 250, 190)),
        Yarn("Light Teal", (83, 170, 204)),
        Yarn("Bright Red", (210, 25, 35)),
        Yarn("Old Brown RH", (100, 70, 50), retired=True),
        Yarn("Black RH", (15, 14, 18)),
    ])


class TempDir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def path(self, name):
        return os.path.join(self.dir, name)

    def write(self, name, text):
        with open(self.path(name), "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return self.path(name)


class TestFiles(TempDir):
    def test_csv_round_trip_keeps_retired_and_sorts(self):
        p = self.path("p.csv")
        pal.save_palette(p, list(reversed(bank())))
        back = pal.load_palette(p)
        self.assertEqual([y.sku for y in back], [y.sku for y in bank()])
        self.assertEqual([y.retired for y in back], [y.retired for y in bank()])
        self.assertEqual([y.hex for y in back], [y.hex for y in bank()])
        Ls = [y.L for y in back]
        self.assertEqual(Ls, sorted(Ls, reverse=True))
        self.assertFalse([f for f in os.listdir(self.dir) if f.endswith(".tmp")])

    def test_old_csv_without_retired_column_loads(self):
        p = self.write("old.csv", "order,sku,r,g,b,hex,L_gimp,color_stddev\n"
                                  "1,White,247,243,234,#F7F3EA,95.9696,0.0000\n")
        (y,) = pal.load_palette(p)
        self.assertEqual((y.sku, y.rgb, y.retired), ("White", (247, 243, 234), False))

    def test_import_csv_with_name_and_hex_only(self):
        p = self.write("in.csv", "Name,Hex,Retired\nMint, 98d8b0 ,\nGone,#102030,yes\n\n")
        entries = pal.read_csv_entries(p)
        self.assertEqual([(e.name, e.hex, e.retired) for e in entries],
                         [("Mint", "#98D8B0", False), ("Gone", "#102030", True)])

    def test_bad_csv_rejected(self):
        with self.assertRaises(ValueError):
            pal.read_csv_entries(self.write("a.csv", "hex\n#FFFFFF\n"))
        with self.assertRaises(ValueError):
            pal.read_csv_entries(self.write("b.csv", "name,hex\nX,notahex\n"))

    def test_gpl_round_trip_active_only(self):
        p = self.path("y.gpl")
        pal.write_gpl(p, bank())
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.startswith("GIMP Palette\n"))
        self.assertIn("254 250 190\tSunny Yellow\n", text)
        entries = pal.read_gpl(p)
        self.assertEqual([e.name for e in entries], [y.sku for y in pal.active(bank())])
        self.assertNotIn("Old Brown RH", [e.name for e in entries])

    def test_read_gimp_style_gpl(self):
        p = self.write("g.gpl", "GIMP Palette\nName: Yarn\nColumns: 16\n#\n"
                                " 86  38  24\tIndex 0\n255 255 255 Snow White\n0 0 0\n")
        entries = pal.read_gpl(p)
        self.assertEqual([(e.name, e.rgb) for e in entries],
                         [("Index 0", (86, 38, 24)), ("Snow White", (255, 255, 255)),
                          ("", (0, 0, 0))])

    def test_not_a_gpl(self):
        with self.assertRaises(ValueError):
            pal.read_gpl(self.write("x.gpl", "hello\n1 2 3 x\n"))


class TestHelpers(unittest.TestCase):
    def test_brand(self):
        self.assertEqual(pal.brand_of("Light Teal"), "Hershner's")
        self.assertEqual(pal.brand_of("Gold RH"), "Red Heart")
        self.assertEqual(pal.brand_of("Mint L&T"), "Loops & Threads")

    def test_name_problem(self):
        b = bank()
        self.assertIsNotNone(pal.name_problem("  ", b))
        self.assertIn("Light Teal", pal.name_problem("light  TEAL", b))
        self.assertIn("retired", pal.name_problem("old brown rh", b))
        self.assertIsNone(pal.name_problem("Light Teal", b, exclude=b[1]))
        self.assertIsNone(pal.name_problem("Mint", b))

    def test_placement(self):
        b = bank()
        pos, total, lighter, darker = pal.placement(b, 60.0)
        self.assertEqual((pos, total, lighter.sku, darker.sku), (3, 5, "Light Teal", "Bright Red"))
        pos, total, lighter, darker = pal.placement(b, 99.0)
        self.assertEqual((pos, lighter, darker.sku), (1, None, "Sunny Yellow"))
        teal = [y for y in b if y.sku == "Light Teal"][0]
        self.assertEqual(pal.placement(b, teal.L, exclude=teal)[:2], (2, 4))

    def test_placeholders(self):
        for n in ("", "Index 3", "index", "Untitled", "Color 12"):
            self.assertTrue(pal.is_placeholder(n), n)
        for n in ("Indigo", "Coral", "Light Teal"):
            self.assertFalse(pal.is_placeholder(n), n)


class TestImport(unittest.TestCase):
    def plan(self, *entries):
        return pal.plan_import(bank(), [Entry(*e) for e in entries])

    def test_classification(self):
        items = self.plan(("Mint", (152, 216, 176)),            # new
                          ("sunny yellow", (254, 250, 190)),    # same (case-insensitive)
                          ("Light Teal", (80, 170, 200)),       # clash
                          ("Old Brown RH", (101, 70, 50)),      # retired match
                          ("Fire Red", (210, 25, 35)),          # same hex as Bright Red
                          ("Index 4", (1, 2, 3)),               # placeholder
                          ("Mint", (150, 210, 170)))            # repeated in file
        self.assertEqual([i.kind for i in items],
                         [pal.NEW, pal.SAME, pal.CLASH, pal.RETIRED, pal.HEX_MATCH,
                          pal.PLACEHOLDER, pal.DUPLICATE])
        self.assertEqual(items[4].existing.sku, "Bright Red")

    def test_defaults_add_new_and_change_nothing_else(self):
        b = bank()
        items = pal.plan_import(b, [Entry(*e) for e in (
            ("Mint", (152, 216, 176)), ("Light Teal", (80, 170, 200)),
            ("Fire Red", (210, 25, 35)), ("Index 4", (1, 2, 3)))])
        new = pal.apply_import(b, items)
        by = {y.sku: y for y in new}
        self.assertEqual(len(new), len(b) + 1)
        self.assertIn("Mint", by)
        self.assertEqual(by["Light Teal"].hex, "#53AACC")   # kept mine
        self.assertNotIn("Fire Red", by)
        self.assertEqual(by["Old Brown RH"].retired, True)   # untouched yarns left alone
        # the original bank is not modified
        self.assertEqual(len(b), 5)

    def test_clash_choices(self):
        items = self.plan(("Light Teal", (80, 170, 200)))
        items[0].action = "take_file"
        by = {y.sku: y for y in pal.apply_import(bank(), items)}
        self.assertEqual(by["Light Teal"].hex, "#50AAC8")

        items = self.plan(("Light Teal", (80, 170, 200)))
        items[0].action = "keep_both"
        self.assertTrue(pal.import_problems(bank(), items))      # no name yet
        items[0].new_name = "light teal"
        self.assertTrue(pal.import_problems(bank(), items))      # still clashes
        items[0].new_name = "Light Teal 2"
        by = {y.sku: y for y in pal.apply_import(bank(), items)}
        self.assertEqual((by["Light Teal"].hex, by["Light Teal 2"].hex), ("#53AACC", "#50AAC8"))

    def test_retired_restore(self):
        items = self.plan(("old brown rh", (101, 70, 50)))
        self.assertEqual(items[0].options, ("restore", "restore_keep_hex", "skip"))
        by = {y.sku: y for y in pal.apply_import(bank(), items)}
        self.assertEqual((by["Old Brown RH"].retired, by["Old Brown RH"].hex), (False, "#654632"))
        items = self.plan(("Old Brown RH", (101, 70, 50)))
        items[0].action = "restore_keep_hex"
        by = {y.sku: y for y in pal.apply_import(bank(), items)}
        self.assertEqual((by["Old Brown RH"].retired, by["Old Brown RH"].hex), (False, "#644632"))

    def test_hex_match_rename(self):
        items = self.plan(("Fire Red", (210, 25, 35)))
        items[0].action = "rename_existing"
        names = [y.sku for y in pal.apply_import(bank(), items)]
        self.assertIn("Fire Red", names)
        self.assertNotIn("Bright Red", names)

    def test_placeholder_needs_real_name(self):
        items = self.plan(("Index 4", (1, 2, 3)))
        items[0].action = "add_named"
        items[0].new_name = "Index 5"
        self.assertTrue(pal.import_problems(bank(), items))
        items[0].new_name = "Ink"
        self.assertIn("Ink", [y.sku for y in pal.apply_import(bank(), items)])

    def test_two_new_names_colliding_is_blocked(self):
        items = self.plan(("Mint", (152, 216, 176)), ("Mint", (150, 210, 170)))
        items[1].action = "add_named"
        items[1].new_name = "MINT"
        self.assertTrue(pal.import_problems(bank(), items))
        with self.assertRaises(ValueError):
            pal.apply_import(bank(), items)

    def test_suggest_name(self):
        taken = {pal.name_key(n) for n in ("Light Teal", "Light Teal 2")}
        self.assertEqual(pal.suggest_name("Light Teal", taken), "Light Teal 3")


if __name__ == "__main__":
    unittest.main()
