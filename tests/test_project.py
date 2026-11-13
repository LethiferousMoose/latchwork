import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pixelart  # noqa: E402
from palette import Yarn, sort_yarns  # noqa: E402
from project import Project  # noqa: E402


# ---------- helpers to build test PNGs of every flavor ----------
def _chunk(t, b):
    return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def _filter(ftype, line, prev, bpp):
    out = bytearray(len(line))
    for x in range(len(line)):
        a = line[x - bpp] if x >= bpp else 0
        b = prev[x]
        c = prev[x - bpp] if x >= bpp else 0
        pred = {0: 0, 1: a, 2: b, 3: (a + b) >> 1, 4: _paeth(a, b, c)}[ftype]
        out[x] = (line[x] - pred) & 255
    return out


def make_png(width, height, rows, color_type, depth=8, plte=None, trns=None, filters=(0,)):
    """rows: list of raw (unfiltered) scanline bytes. Filter type cycles through `filters`."""
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    bpp = max(1, channels * depth // 8)
    prev = bytes(len(rows[0]))
    data = bytearray()
    for y, line in enumerate(rows):
        f = filters[y % len(filters)]
        data.append(f)
        data.extend(_filter(f, line, prev, bpp))
        prev = line
    png = pixelart.PNG_SIG + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth,
                                                         color_type, 0, 0, 0))
    if plte:
        png += _chunk(b"PLTE", bytes(v for rgb in plte for v in rgb))
    if trns is not None:
        png += _chunk(b"tRNS", trns)
    return png + _chunk(b"IDAT", zlib.compress(bytes(data))) + _chunk(b"IEND", b"")


RGB_ROWS = [bytes([10, 20, 30, 200, 100, 50, 10, 20, 30]),
            bytes([255, 255, 255, 0, 0, 0, 200, 100, 50])]
RGB_PIXELS = [(10, 20, 30, 255), (200, 100, 50, 255), (10, 20, 30, 255),
              (255, 255, 255, 255), (0, 0, 0, 255), (200, 100, 50, 255)]


class TestDecodePNG(unittest.TestCase):
    def test_rgb_all_filters(self):
        for f in range(5):
            with self.subTest(filter=f):
                img = pixelart.decode_png(make_png(3, 2, RGB_ROWS, 2, filters=(f,)))
                self.assertEqual((img.width, img.height), (3, 2))
                self.assertEqual(img.pixels, RGB_PIXELS)

    def test_rgba_with_transparency(self):
        rows = [bytes([1, 2, 3, 255, 9, 9, 9, 0]), bytes([4, 5, 6, 127, 7, 8, 9, 128])]
        img = pixelart.decode_png(make_png(2, 2, rows, 6, filters=(4, 3)))
        self.assertEqual(img.pixels, [(1, 2, 3, 255), (9, 9, 9, 0), (4, 5, 6, 127), (7, 8, 9, 128)])
        counts, transparent = pixelart.color_counts(img)
        self.assertEqual(transparent, 2)
        self.assertEqual(dict(counts), {"#010203": 1, "#070809": 1})

    def test_palette_4bit_with_trns(self):
        plte = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        # 5 pixels of 4 bits: indices 0,1,2,1,0 -> bytes 0x01 0x21 0x00
        img = pixelart.decode_png(make_png(5, 1, [bytes([0x01, 0x21, 0x00])], 3, depth=4,
                                           plte=plte, trns=bytes([255, 0])))
        self.assertEqual(img.pixels, [(255, 0, 0, 255), (0, 255, 0, 0), (0, 0, 255, 255),
                                      (0, 255, 0, 0), (255, 0, 0, 255)])

    def test_gray_1bit_and_16bit(self):
        img = pixelart.decode_png(make_png(3, 1, [bytes([0b10100000])], 0, depth=1))
        self.assertEqual([p[0] for p in img.pixels], [255, 0, 255])
        rows = [bytes([0x12, 0x34, 0xAB, 0xCD])]
        img = pixelart.decode_png(make_png(1, 1, rows, 4, depth=16))
        self.assertEqual(img.pixels, [(0x12, 0x12, 0x12, 0xAB)])

    def test_rgb_trns_key(self):
        trns = struct.pack(">HHH", 0, 0, 0)
        img = pixelart.decode_png(make_png(3, 2, RGB_ROWS, 2, trns=trns))
        self.assertEqual(img.pixels[4], (0, 0, 0, 0))
        self.assertEqual(pixelart.color_counts(img)[1], 1)

    def test_encode_round_trip(self):
        for pixels in (RGB_PIXELS, RGB_PIXELS[:5] + [(9, 9, 9, 0)]):
            img = pixelart.PixelImage(3, 2, pixels)
            self.assertEqual(pixelart.decode_png(pixelart.encode_png(img)).pixels, pixels)

    def test_rejects(self):
        with self.assertRaises(ValueError) as cm:
            pixelart.decode(b"\xff\xd8\xff\xe0" + bytes(20))
        self.assertIn("JPEG", str(cm.exception))
        with self.assertRaises(ValueError):
            pixelart.decode(b"hello")
        with self.assertRaises(ValueError):
            pixelart.decode_png(pixelart.PNG_SIG + b"junk")


class TestProject(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        # 3x2 image: 2x dark blue-ish, 2x orange, 1x white, 1x black
        self.png = make_png(3, 2, RGB_ROWS, 2)
        self.path = os.path.join(self.dir, "test.latchwork")
        self.yarns = sort_yarns([Yarn("White", (247, 243, 234)), Yarn("Orange", (200, 110, 60)),
                                 Yarn("Navy", (20, 25, 60)), Yarn("Black", (15, 14, 18))])

    def tearDown(self):
        shutil.rmtree(self.dir)

    def new(self):
        return Project.from_image_bytes(self.png, "test.png", self.path)

    def test_counts_and_order(self):
        p = self.new()
        self.assertEqual([(c.hex, c.count) for c in p.colors],
                         [("#FFFFFF", 1), ("#C86432", 2), ("#0A141E", 2), ("#000000", 1)])
        self.assertEqual((p.knots, p.transparent, p.name), (6, 0, "test"))

    def test_suggest_assign_and_round_trip(self):
        p = self.new()
        self.assertTrue(p.suggest(self.yarns, "palette.csv"))
        self.assertEqual(p.entry("#C86432").yarn["name"], "Orange")
        self.assertFalse(p.entry("#C86432").confirmed)
        p.assign("#0a141e", self.yarns[2], "sky.csv")
        p.save()

        q = Project.load(self.path)
        self.assertEqual(q.assigned_count, 1)
        e = q.entry("#0A141E")
        self.assertEqual((e.yarn, e.confirmed),
                         ({"name": self.yarns[2].sku, "hex": self.yarns[2].hex, "palette": "sky.csv"},
                          True))
        self.assertEqual(q.entry("#C86432").yarn["name"], "Orange")   # suggestion kept
        self.assertEqual(q.image.pixels, p.image.pixels)                # image embedded
        self.assertFalse([f for f in os.listdir(self.dir) if f.endswith(".tmp")])

    def test_confirmed_survive_resuggest_and_unassign(self):
        p = self.new()
        p.suggest(self.yarns, "palette.csv")
        p.assign("#FFFFFF", self.yarns[3], "palette.csv")      # deliberately "wrong"
        other = sort_yarns([Yarn("Cream", (250, 240, 220)), Yarn("Rust", (180, 80, 40))])
        p.suggest(other, "other.csv")
        self.assertEqual(p.entry("#FFFFFF").yarn["name"], self.yarns[3].sku)
        self.assertEqual(p.entry("#C86432").yarn, {"name": "Rust", "hex": "#B45028",
                                                    "palette": "other.csv"})
        p.unassign("#FFFFFF")
        p.suggest(other, "other.csv")
        self.assertEqual(p.entry("#FFFFFF").yarn["name"], "Cream")
        p.suggest([], "empty.csv")
        self.assertIsNone(p.entry("#FFFFFF").yarn)

    def test_file_is_readable_json(self):
        p = self.new()
        p.save()
        with open(self.path, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual((doc["format"], doc["version"], doc["image"]["width"]),
                         ("latchwork-project", 1, 3))

    def test_load_rejects_other_json(self):
        bad = os.path.join(self.dir, "bad.latchwork")
        with open(bad, "w") as fh:
            json.dump({"hello": 1}, fh)
        with self.assertRaises(ValueError):
            Project.load(bad)

    def test_transparent_only_image_rejected(self):
        png = make_png(1, 1, [bytes([1, 2, 3, 0])], 6)
        with self.assertRaises(ValueError):
            Project.from_image_bytes(png, "x.png", self.path)


if __name__ == "__main__":
    unittest.main()
