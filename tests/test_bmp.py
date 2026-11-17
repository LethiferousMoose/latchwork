import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from latchwork import pixelart  # noqa: E402
from latchwork.project import Project  # noqa: E402

# 3 x 2 test image (top row first); width 3 makes 24-bit rows need padding
PIX = [[(255, 0, 0), (0, 255, 0), (0, 0, 255)],
       [(255, 255, 255), (16, 32, 48), (0, 0, 0)]]
RGBA = [p + (255,) for row in PIX for p in row]


def make_bmp(width, height, bpp, rows_bottom_up, palette=(), hsize=40, comp=0, masks=None,
             top_down=False):
    """rows_bottom_up: raw pixel bytes per row, unpadded, in file order."""
    stride = (width * bpp + 31) // 32 * 4
    body = b"".join(r + b"\0" * (stride - len(r)) for r in rows_bottom_up)
    pal = b"".join(bytes((b, g, r, 0)) for r, g, b in palette)
    extra = b"".join(struct.pack("<I", m) for m in masks) if masks and hsize == 40 else b""
    if hsize == 40:
        head = struct.pack("<IiiHHIIiiII", 40, width, -height if top_down else height, 1, bpp,
                           comp, len(body), 2835, 2835, len(palette), 0)
    else:   # V4 header (108 bytes) with masks inside
        m = list(masks or (0, 0, 0, 0)) + [0] * 4
        head = struct.pack("<IiiHHIIiiII", hsize, width, -height if top_down else height, 1,
                           bpp, comp, len(body), 2835, 2835, len(palette), 0)
        head += struct.pack("<IIII", *m[:4]) + b"\0" * (hsize - 56)
    offset = 14 + len(head) + len(extra) + len(pal)
    return b"BM" + struct.pack("<IHHI", offset + len(body), 0, 0, offset) + head + extra + pal + body


def rows24(top_down=False):
    rows = [b"".join(bytes((b, g, r)) for r, g, b in row) for row in PIX]
    return rows if top_down else rows[::-1]


class BmpTest(unittest.TestCase):
    def check(self, data, expect=RGBA):
        self.assertEqual(pixelart.sniff(data), "bmp")
        img = pixelart.decode(data)
        self.assertEqual((img.width, img.height), (3, 2))
        self.assertEqual(img.pixels, expect)

    def test_24bit_bottom_up_and_top_down(self):
        self.check(make_bmp(3, 2, 24, rows24()))
        self.check(make_bmp(3, 2, 24, rows24(True), top_down=True))

    def test_palette_8_4_1_bit(self):
        pal = [p for row in PIX for p in row]
        self.check(make_bmp(3, 2, 8, [bytes([3, 4, 5]), bytes([0, 1, 2])], pal))
        self.check(make_bmp(3, 2, 4, [bytes([0x34, 0x50]), bytes([0x01, 0x20])], pal))
        bw = [(0, 0, 0), (255, 255, 255)]
        img = pixelart.decode(make_bmp(3, 2, 1, [bytes([0b01000000]), bytes([0b10100000])], bw))
        self.assertEqual([p[0] for p in img.pixels], [255, 0, 255, 0, 255, 0])

    def test_32bit_empty_alpha_is_opaque(self):
        rows = [b"".join(bytes((b, g, r, 0)) for r, g, b in row) for row in PIX][::-1]
        self.check(make_bmp(3, 2, 32, rows))

    def test_32bit_real_alpha(self):
        rows = [b"".join(bytes((b, g, r, 0 if (r, g, b) == (0, 0, 0) else 255)) for r, g, b in row)
                for row in PIX][::-1]
        expect = [p[:3] + (0 if p[:3] == (0, 0, 0) else 255,) for p in RGBA]
        masks = (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
        self.check(make_bmp(3, 2, 32, rows, hsize=108, comp=3, masks=masks), expect)
        counts, transparent = pixelart.color_counts(pixelart.decode(
            make_bmp(3, 2, 32, rows, hsize=108, comp=3, masks=masks)))
        self.assertEqual(transparent, 1)

    def test_16bit_555_and_565(self):
        pix = [[(255, 0, 0), (0, 255, 0), (0, 0, 255)], [(255, 255, 255), (0, 0, 0), (0, 0, 0)]]
        expect = [p + (255,) for row in pix for p in row]
        def pack(row, rb, gb, bb, gs, rs):
            return b"".join(struct.pack("<H", (r >> (8 - rb)) << rs | (g >> (8 - gb)) << gs |
                                        (b >> (8 - bb))) for r, g, b in row)
        rows555 = [pack(r, 5, 5, 5, 5, 10) for r in pix][::-1]
        self.check(make_bmp(3, 2, 16, rows555), expect)
        rows565 = [pack(r, 5, 6, 5, 5, 11) for r in pix][::-1]
        self.check(make_bmp(3, 2, 16, rows565, comp=3, masks=(0xF800, 0x07E0, 0x001F)), expect)

    def test_refused(self):
        good = make_bmp(3, 2, 24, rows24())
        for bad, msg in ((good[:-5], "truncated"),
                         (make_bmp(3, 2, 8, [b"\0\0\0"] * 2, [(0, 0, 0)], comp=1), "RLE"),
                         (good[:22] + struct.pack("<i", 2000000) + good[26:], "isn't usable")):
            with self.assertRaises(ValueError) as cm:
                pixelart.decode(bad)
            self.assertIn(msg, str(cm.exception))

    def test_too_many_colors_is_refused(self):
        from latchwork.project import MAX_COLORS
        n = MAX_COLORS + 1   # one row, every pixel a different color
        row = b"".join(bytes((i & 255, i >> 8, 7)) for i in range(n))
        with self.assertRaises(ValueError) as cm:
            Project.from_image_bytes(make_bmp(n, 1, 24, [row]), "photo.bmp", "x.latchwork")
        self.assertIn("1,001 different colors", str(cm.exception))
        row = row[:3 * MAX_COLORS]
        p = Project.from_image_bytes(make_bmp(MAX_COLORS, 1, 24, [row]), "ok.bmp", "x.latchwork")
        self.assertEqual(len(p.colors), MAX_COLORS)

    def test_project_keeps_it_as_png(self):
        data = make_bmp(3, 2, 24, rows24())
        with tempfile.TemporaryDirectory() as tmp:
            p = Project.from_image_bytes(data, "sprite.bmp", os.path.join(tmp, "s.latchwork"))
            self.assertEqual(p.image_format, "png")
            self.assertEqual(pixelart.decode_png(p.image_bytes).pixels, RGBA)
            p.save()
            q = Project.load(p.path)
            self.assertEqual(q.image.pixels, RGBA)
            self.assertEqual(q.image_filename, "sprite.bmp")
            self.assertEqual([c.hex for c in q.colors], [c.hex for c in p.colors])


if __name__ == "__main__":
    unittest.main()
