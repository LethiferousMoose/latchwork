import csv
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from colormath import (gray_for_lightness, lch_to_rgb, lightness, nearest_index,  # noqa: E402
                       parse_hex, rgb_to_lch, to_hex)
from latchwork import load_palette  # noqa: E402

PALETTE = os.path.join(ROOT, "palette.csv")


def palette_rows():
    with open(PALETTE, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


class TestLightness(unittest.TestCase):
    def test_every_palette_row_matches_L_gimp(self):
        rows = palette_rows()
        self.assertEqual(len(rows), 198)
        for row in rows:
            with self.subTest(sku=row["sku"]):
                L = lightness(int(row["r"]), int(row["g"]), int(row["b"]))
                self.assertAlmostEqual(L, float(row["L_gimp"]), delta=1e-4)

    def test_gimp_spot_checks(self):
        # Values read from GIMP 2.10's LCh selector by the user.
        checks = {(254, 250, 190): 97.5, (83, 170, 204): 65.3, (153, 157, 166): 64.6,
                  (136, 160, 72): 62.6, (210, 25, 35): 45.8, (15, 14, 18): 4.1}
        for rgb, expected in checks.items():
            with self.subTest(rgb=rgb):
                self.assertEqual(round(lightness(*rgb), 1), expected)

    def test_gimp_lch_spot_checks(self):
        # L / C / h read from GIMP 2.10's LCh selector by the user.
        checks = {(254, 250, 190): (97.5, 29.9, 100.4), (210, 25, 35): (45.8, 82.1, 34.8),
                  (83, 170, 204): (65.3, 32.5, 232.7), (136, 160, 72): (62.6, 46.2, 114.2)}
        for rgb, expected in checks.items():
            with self.subTest(rgb=rgb):
                self.assertEqual(tuple(round(v, 1) for v in rgb_to_lch(*rgb)), expected)

    def test_extremes(self):
        self.assertAlmostEqual(lightness(0, 0, 0), 0.0, places=6)
        self.assertAlmostEqual(lightness(255, 255, 255), 100.0, places=4)

    def test_lch_lightness_agrees_and_white_is_neutral(self):
        self.assertEqual(rgb_to_lch(136, 160, 72)[0], lightness(136, 160, 72))
        self.assertAlmostEqual(rgb_to_lch(255, 255, 255)[1], 0.0, places=3)

    def test_lch_to_rgb_round_trip(self):
        for row in palette_rows():
            rgb = (int(row["r"]), int(row["g"]), int(row["b"]))
            with self.subTest(sku=row["sku"]):
                back = lch_to_rgb(*rgb_to_lch(*rgb))
                for x, y in zip(rgb, back):
                    self.assertAlmostEqual(x, y, delta=1e-6)

    def test_gray_round_trip(self):
        for L in (4.1, 25.0, 50.0, 62.6, 97.5):
            v = gray_for_lightness(L)
            self.assertAlmostEqual(lightness(v, v, v), L, places=6)


class TestPaletteOrder(unittest.TestCase):
    def test_csv_is_sorted_lightest_to_darkest(self):
        Ls = [float(r["L_gimp"]) for r in palette_rows()]
        self.assertEqual(Ls, sorted(Ls, reverse=True))

    def test_excluded_layers_absent(self):
        names = {"%s (%s)" % (r["sku"], r["brand"]) for r in palette_rows()}
        self.assertNotIn("Mask", names)
        self.assertNotIn("Cafe (Red Heart)", names)       # old name of Cafe Latte
        self.assertIn("Cafe Latte (Red Heart)", names)

    def test_light_teal_before_dusty_grey(self):
        names = [y.label for y in load_palette(PALETTE)]
        self.assertLess(names.index("Light Teal (Hershner's)"), names.index("Dusty Grey (Red Heart)"))


class TestMatching(unittest.TestCase):
    def test_exact_palette_color_lands_on_itself(self):
        yarns = load_palette(PALETTE)
        Ls = [y.L for y in yarns]
        for i, y in enumerate(yarns):
            with self.subTest(sku=y.sku):
                j = nearest_index(lightness(*y.rgb), Ls)
                self.assertEqual(Ls[j], Ls[i])
                # Only an exact L tie may land elsewhere, and then on the earlier yarn.
                self.assertLessEqual(j, i)

    def test_ties_resolve_to_first(self):
        self.assertEqual(nearest_index(50.0, [60.0, 40.0]), 0)
        self.assertEqual(nearest_index(50.0, [70.0, 55.0, 45.0, 55.0]), 1)
        self.assertEqual(nearest_index(10.0, [30.0, 20.0, 20.0]), 1)


class TestHex(unittest.TestCase):
    def test_accepts(self):
        for text in ("#88A048", "88a048", " #88A048 ", "\t88A048\n", "# 88a048"):
            with self.subTest(text=text):
                self.assertEqual(parse_hex(text), (136, 160, 72))

    def test_rejects(self):
        for text in ("", "#", "88A04", "88A0488", "#GGA048", "136,160,72", "##88A048"):
            with self.subTest(text=text):
                self.assertIsNone(parse_hex(text))

    def test_to_hex(self):
        self.assertEqual(to_hex(136, 160, 72), "#88A048")


if __name__ == "__main__":
    unittest.main()
