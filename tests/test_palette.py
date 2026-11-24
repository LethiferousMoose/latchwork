import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from latchwork import palette as pal  # noqa: E402
from latchwork.palette import Brand, Entry, Yarn  # noqa: E402

H, RH = "Herrschners", "Red Heart"


def bank():
    return pal.sort_yarns([
        Yarn("Sunny Yellow", (254, 250, 190), brand=H),
        Yarn("Light Teal", (83, 170, 204), brand=H),
        Yarn("Bright Red", (210, 25, 35), brand=H),
        Yarn("Old Brown", (100, 70, 50), retired=True, brand=RH),
        Yarn("Black", (15, 14, 18), brand=RH),
    ])


def brands():
    return [Brand(H, 320), Brand(RH, None)]


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
    def test_bank_round_trip_keeps_brands_retired_and_sorts(self):
        p = self.path("p.csv")
        pal.save_bank(p, list(reversed(bank())), brands())
        self.assertTrue(os.path.exists(self.path("p.brands.csv")))
        back, br = pal.load_bank(p)
        self.assertEqual([(y.sku, y.brand, y.retired, y.hex) for y in back],
                         [(y.sku, y.brand, y.retired, y.hex) for y in bank()])
        self.assertEqual([(b.name, b.pack) for b in br], [(H, 320), (RH, None)])
        Ls = [y.L for y in back]
        self.assertEqual(Ls, sorted(Ls, reverse=True))
        self.assertFalse([f for f in os.listdir(self.dir) if f.endswith(".tmp")])

    def test_empty_palette_round_trip(self):
        p = self.path("empty.csv")
        pal.save_bank(p, [], [])
        self.assertEqual(pal.load_bank(p), ([], []))

    def test_legacy_csv_gets_brands_from_suffixes(self):
        p = self.write("old.csv", "order,sku,r,g,b,hex,L_gimp,retired\n"
                                  "1,White,247,243,234,#F7F3EA,95.9696,\n"
                                  "2,White RH,226,226,226,#E2E2E2,89.9,\n"
                                  "3,Spa L&T,204,206,232,#CCCEE8,91.3,yes\n")
        yarns, br = pal.load_bank(p)
        self.assertEqual(sorted((y.sku, y.brand, y.retired) for y in yarns),
                         [("Spa L&T", "Loops & Threads", True), ("White", H, False),
                          ("White RH", RH, False)])
        self.assertEqual({b.name: b.pack for b in br},
                         {H: 320, RH: None, "Loops & Threads": None})

    def test_brand_file_missing_brands_are_added(self):
        p = self.write("x.csv", "sku,brand,hex\nMint,Caron,#98D8B0\n")
        yarns, br = pal.load_bank(p)
        self.assertEqual([(b.name, b.pack) for b in br], [("Caron", None)])

    def test_import_csv_with_name_and_hex_only(self):
        p = self.write("in.csv", "Name,Hex,Retired\nMint, 98d8b0 ,\nGone,#102030,yes\n\n")
        entries, br = pal.read_import_file(p)
        self.assertEqual([(e.name, e.hex, e.retired, e.brand) for e in entries],
                         [("Mint", "#98D8B0", False, None), ("Gone", "#102030", True, None)])
        self.assertTrue(pal.needs_brand(entries))
        pal.set_brand(entries, "Caron")
        self.assertEqual({e.brand for e in entries}, {"Caron"})

    def test_import_csv_brings_its_brand_file(self):
        p = self.path("exp.csv")
        pal.save_bank(p, bank(), brands())
        entries, br = pal.read_import_file(p)
        self.assertFalse(pal.needs_brand(entries))
        self.assertEqual({b.name: b.pack for b in br}, {H: 320, RH: None})
        merged = pal.merge_brands([Brand(H, 640), Brand("Caron")], br)
        self.assertEqual({b.name: b.pack for b in merged}, {H: 640, RH: None, "Caron": None})

    def test_bad_csv_rejected(self):
        with self.assertRaises(ValueError):
            pal.read_csv_entries(self.write("a.csv", "hex\n#FFFFFF\n"))
        with self.assertRaises(ValueError):
            pal.read_csv_entries(self.write("b.csv", "name,hex\nX,notahex\n"))

    def test_old_per_yarn_pack_size_is_ignored(self):
        # Older palettes had a pack_size column per yarn: still loads, pack comes from the brand,
        # and saving drops the column.
        p = self.write("old.csv", "order,sku,brand,r,g,b,hex,L_gimp,pack_size,retired\n"
                                  "1,Mint,Caron,152,216,176,#98D8B0,82.6,100,\n"
                                  "2,Ash,Caron,90,90,90,#5A5A5A,38.0,lots,\n")
        self.write("old.brands.csv", "brand,pack_size\nCaron,250\n")
        yarns, br = pal.load_bank(p)
        self.assertEqual([pal.effective_pack(y, br) for y in yarns], [250, 250])
        pal.save_bank(p, yarns, br)
        with open(p, encoding="utf-8") as fh:
            self.assertEqual(fh.readline().strip(), ",".join(pal.FIELDS))
        self.assertNotIn("pack_size", pal.FIELDS)

    def test_gpl_round_trip_active_only(self):
        p = self.path("y.gpl")
        pal.write_gpl(p, bank())
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.startswith("GIMP Palette\n"))
        self.assertIn("254 250 190\tSunny Yellow (Herrschners)\n", text)
        entries, br = pal.read_import_file(p)
        self.assertEqual(len(entries), len(pal.active(bank())))
        self.assertEqual(br, [])
        self.assertTrue(pal.needs_brand(entries))

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
    def test_legacy_rules(self):
        self.assertEqual(pal.legacy_brand("Light Teal"), H)
        self.assertEqual(pal.legacy_brand("Gold RH"), RH)
        self.assertEqual(pal.legacy_brand("Mint L&T"), "Loops & Threads")
        self.assertEqual(pal.strip_legacy_suffix("Gold RH"), "Gold")
        self.assertEqual(pal.strip_legacy_suffix("Pretty N' Pink RH"), "Pretty N' Pink")
        self.assertEqual(pal.strip_legacy_suffix("Light Teal"), "Light Teal")
        self.assertEqual(pal.legacy_assignment("Gold RH"), ("Gold", RH, None))
        self.assertEqual(pal.legacy_assignment("Avocado"), ("Avocado", H, 320))

    def test_effective_pack_and_label(self):
        b = {y.sku: y for y in bank()}
        self.assertEqual(pal.effective_pack(b["Light Teal"], brands()), 320)
        self.assertIsNone(pal.effective_pack(b["Black"], brands()))            # brand is cut
        self.assertIsNone(pal.effective_pack(b["Old Brown"], brands()))        # cut
        self.assertIsNone(pal.effective_pack(Yarn("X", (1, 2, 3)), brands()))  # no brand
        self.assertEqual(b["Black"].label, "Black (Red Heart)")
        self.assertEqual(pal.label("Mint", ""), "Mint")
        self.assertEqual(pal.parse_pack(" 320 "), 320)
        self.assertIsNone(pal.parse_pack(""))
        self.assertIsNone(pal.parse_pack("cut"))
        with self.assertRaises(ValueError):
            pal.parse_pack("-5")

    def test_name_problem_is_per_brand(self):
        b = bank()
        self.assertIsNotNone(pal.name_problem("  ", H, b))
        self.assertIn("Light Teal", pal.name_problem("light  TEAL", "herrschners", b))
        self.assertIsNone(pal.name_problem("Light Teal", RH, b))       # other brand: fine
        self.assertIn("retired", pal.name_problem("old brown", RH, b))
        teal = [y for y in b if y.sku == "Light Teal"][0]
        self.assertIsNone(pal.name_problem("Light Teal", H, b, exclude=teal))

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
    def plan(self, *entries, brand=H):
        es = [Entry(*e) for e in entries]
        pal.set_brand(es, brand)
        return pal.plan_import(bank(), es)

    def test_classification(self):
        items = self.plan(("Mint", (152, 216, 176)),            # new
                          ("sunny yellow", (254, 250, 190)),    # same (case-insensitive)
                          ("Light Teal", (80, 170, 200)),       # clash
                          ("Fire Red", (210, 25, 35)),          # same hex as Bright Red
                          ("Index 4", (1, 2, 3)),               # placeholder
                          ("Mint", (150, 210, 170)))            # repeated in file
        self.assertEqual([i.kind for i in items],
                         [pal.NEW, pal.SAME, pal.CLASH, pal.HEX_MATCH, pal.PLACEHOLDER,
                          pal.DUPLICATE])
        self.assertEqual(items[3].existing.sku, "Bright Red")

    def test_same_name_other_brand_is_new(self):
        items = self.plan(("Light Teal", (80, 170, 200)), brand="Caron")
        self.assertEqual(items[0].kind, pal.NEW)
        new = pal.apply_import(bank(), items)
        self.assertEqual(sorted(y.label for y in new if y.sku == "Light Teal"),
                         ["Light Teal (Caron)", "Light Teal (Herrschners)"])

    def test_retired_match(self):
        items = self.plan(("old brown", (101, 70, 50)), brand=RH)
        self.assertEqual(items[0].kind, pal.RETIRED)
        self.assertEqual(items[0].options, ("restore", "restore_keep_hex", "skip"))
        by = {y.sku: y for y in pal.apply_import(bank(), items)}
        self.assertEqual((by["Old Brown"].retired, by["Old Brown"].hex), (False, "#654632"))

    def test_defaults_add_new_and_change_nothing_else(self):
        b = bank()
        es = [Entry(*e) for e in (("Mint", (152, 216, 176)), ("Light Teal", (80, 170, 200)),
                                  ("Fire Red", (210, 25, 35)), ("Index 4", (1, 2, 3)))]
        pal.set_brand(es, H)
        new = pal.apply_import(b, pal.plan_import(b, es))
        by = {y.sku: y for y in new}
        self.assertEqual(len(new), len(b) + 1)
        self.assertEqual(by["Mint"].brand, H)
        self.assertEqual(by["Light Teal"].hex, "#53AACC")   # kept mine
        self.assertNotIn("Fire Red", by)
        self.assertEqual(len(b), 5)                          # original not modified

    def test_clash_keep_both(self):
        items = self.plan(("Light Teal", (80, 170, 200)))
        items[0].action = "keep_both"
        self.assertTrue(pal.import_problems(bank(), items))      # no name yet
        items[0].new_name = "light teal"
        self.assertTrue(pal.import_problems(bank(), items))      # still clashes
        items[0].new_name = "Light Teal 2"
        by = {y.sku: y for y in pal.apply_import(bank(), items)}
        self.assertEqual((by["Light Teal"].hex, by["Light Teal 2"].hex), ("#53AACC", "#50AAC8"))

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

    def test_reimporting_an_export_is_all_already_there(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "x.csv")
            pal.save_bank(p, bank(), brands())
            entries, _ = pal.read_import_file(p)
            self.assertEqual({i.kind for i in pal.plan_import(bank(), entries)}, {pal.SAME})
        finally:
            shutil.rmtree(d)

    def test_suggest_name(self):
        taken = {pal.yarn_key(n, H) for n in ("Light Teal", "Light Teal 2")}
        self.assertEqual(pal.suggest_name("Light Teal", H, taken), "Light Teal 3")
        self.assertEqual(pal.suggest_name("Light Teal", RH, taken), "Light Teal 2")


class TestPhotos(TempDir):
    def test_links_live_in_the_swatch_folder_not_the_palette(self):
        p = self.path("p.csv")
        yarns = bank()
        yarns[0].photo = "Herrschners/Sunny Yellow.png"
        pal.save_bank(p, yarns, brands())
        with open(p, encoding="utf-8") as fh:
            self.assertNotIn("photo", fh.read())
        self.assertTrue(os.path.exists(os.path.join(self.dir, "p.swatches", "photos.csv")))
        back, _ = pal.load_bank(p)
        self.assertEqual({y.sku: y.photo for y in back if y.photo},
                         {"Sunny Yellow": "Herrschners/Sunny Yellow.png"})
        self.assertFalse(pal.has_photo(p, back[0]))     # linked, but the file isn't there

    def test_no_photos_no_folder(self):
        p = self.path("p.csv")
        pal.save_bank(p, bank(), brands())
        self.assertFalse(os.path.exists(pal.swatch_dir(p)))
        self.assertTrue(all(y.photo is None for y in pal.load_bank(p)[0]))

    def test_rename_keeps_the_photo_and_removing_clears_it(self):
        p = self.path("p.csv")
        yarns = bank()
        yarns[0].photo = "Herrschners/Sunny Yellow.png"
        pal.save_bank(p, yarns, brands())
        back, br = pal.load_bank(p)
        renamed = [y.copy() for y in back]
        renamed[0].sku, renamed[0].brand = "Lemon", RH
        pal.save_bank(p, renamed, br)
        again, _ = pal.load_bank(p)
        self.assertEqual([(y.label, y.photo) for y in again if y.photo],
                         [("Lemon (Red Heart)", "Herrschners/Sunny Yellow.png")])
        cleared = [y.copy() for y in again]
        cleared[0].photo = None
        pal.save_bank(p, cleared, br)
        self.assertTrue(all(y.photo is None for y in pal.load_bank(p)[0]))

    def test_new_photo_names(self):
        p = self.path("p.csv")
        y = Yarn('Odd: Name?', (1, 2, 3), brand="L&T")
        self.assertEqual(pal.new_photo_name(p, y), "L&T/Odd- Name-.png")
        os.makedirs(os.path.join(pal.swatch_dir(p), "L&T"))
        open(os.path.join(pal.swatch_dir(p), "L&T", "Odd- Name-.png"), "w").close()
        self.assertEqual(pal.new_photo_name(p, y), "L&T/Odd- Name- (2).png")
        self.assertEqual(pal.new_photo_name(p, Yarn("Gray", (1, 2, 3))), "No brand/Gray.png")

    def test_tidy_photo_name_after_a_replace(self):
        p = self.path("p.csv")
        folder = os.path.join(pal.swatch_dir(p), "Red Heart")
        os.makedirs(folder)
        open(os.path.join(folder, "Gold (2).png"), "w").close()
        y = Yarn("Gold", (1, 2, 3), brand=RH, photo="Red Heart/Gold (2).png")
        open(os.path.join(folder, "Gold.png"), "w").close()       # old copy still there
        self.assertIsNone(pal.tidy_photo_name(p, y))
        os.remove(os.path.join(folder, "Gold.png"))
        self.assertEqual(pal.tidy_photo_name(p, y), "Red Heart/Gold.png")
        self.assertEqual(os.listdir(folder), ["Gold.png"])
        y.photo = "Red Heart/Gold.png"
        self.assertIsNone(pal.tidy_photo_name(p, y))

    def test_export_copies_photos_and_drops_missing_ones(self):
        src, dst = self.path("a.csv"), self.path("b.csv")
        yarns = bank()
        yarns[0].photo, yarns[1].photo = "H/one.png", "H/gone.png"
        os.makedirs(os.path.join(pal.swatch_dir(src), "H"))
        with open(os.path.join(pal.swatch_dir(src), "H", "one.png"), "wb") as fh:
            fh.write(b"png")
        pal.save_bank(src, yarns, brands())
        out = pal.copy_photos(src, dst, pal.load_bank(src)[0])
        pal.save_bank(dst, out, brands())
        back, _ = pal.load_bank(dst)
        self.assertEqual([y.photo for y in back if y.photo], ["H/one.png"])
        self.assertTrue(pal.has_photo(dst, next(y for y in back if y.photo)))


if __name__ == "__main__":
    unittest.main()
