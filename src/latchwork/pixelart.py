"""Pixel-art images: decode PNG and BMP exactly (stdlib), GIF via Tk, encode PNG, count colors.

PNG pixel values are used as stored (no gamma or color-profile adjustment), the same values
GIMP shows for an untagged sRGB image.
"""
import base64
import struct
import zlib
from collections import Counter

from .colormath import to_hex

PNG_SIG = b"\x89PNG\r\n\x1a\n"
TRANSPARENT_BELOW = 128  # alpha < this counts as transparent (no knot)


class PixelImage:
    def __init__(self, width, height, pixels):
        self.width, self.height = width, height
        self.pixels = pixels  # row-major list of (r, g, b, a), 0..255

    def pixel(self, x, y):
        return self.pixels[y * self.width + x]


def sniff(data):
    if data.startswith(PNG_SIG):
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:2] == b"BM":
        return "bmp"
    return None


# ---------- PNG decode ----------
def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(ftype, line, prev, bpp):
    n = len(line)
    if ftype == 0:
        return
    if ftype == 1:
        for x in range(bpp, n):
            line[x] = (line[x] + line[x - bpp]) & 255
    elif ftype == 2:
        for x in range(n):
            line[x] = (line[x] + prev[x]) & 255
    elif ftype == 3:
        for x in range(n):
            a = line[x - bpp] if x >= bpp else 0
            line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
    elif ftype == 4:
        for x in range(n):
            a = line[x - bpp] if x >= bpp else 0
            c = prev[x - bpp] if x >= bpp else 0
            line[x] = (line[x] + _paeth(a, prev[x], c)) & 255
    else:
        raise ValueError("bad PNG filter type %d" % ftype)


def _samples(line, width, channels, depth):
    """Yield per-pixel sample tuples at full precision (0..2**depth-1)."""
    if depth == 8:
        for i in range(0, width * channels, channels):
            yield tuple(line[i:i + channels])
    elif depth == 16:
        for i in range(0, width * channels * 2, channels * 2):
            yield tuple((line[i + 2 * k] << 8) | line[i + 2 * k + 1] for k in range(channels))
    else:  # 1, 2, 4 bits: grayscale or palette, one channel
        per_byte = 8 // depth
        mask = (1 << depth) - 1
        for x in range(width):
            byte = line[x // per_byte]
            shift = 8 - depth * (x % per_byte + 1)
            yield ((byte >> shift) & mask,)


def decode_png(data):
    if not data.startswith(PNG_SIG):
        raise ValueError("not a PNG file")
    pos, ihdr, plte, trns, idat = 8, None, None, None, []
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif ctype == b"PLTE":
            plte = [tuple(body[i:i + 3]) for i in range(0, len(body) - 2, 3)]
        elif ctype == b"tRNS":
            trns = body
        elif ctype == b"IDAT":
            idat.append(body)
        elif ctype == b"IEND":
            break
    if ihdr is None:
        raise ValueError("PNG has no header (IHDR)")
    width, height, depth, color_type, _comp, _filt, interlace = ihdr
    if interlace:
        raise ValueError("interlaced PNGs aren't supported; save it again without interlacing")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None or depth not in (1, 2, 4, 8, 16):
        raise ValueError("unsupported PNG type (color type %d, depth %d)" % (color_type, depth))
    if color_type == 3 and not plte:
        raise ValueError("palette PNG without a palette")
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as e:
        raise ValueError("PNG image data is damaged (%s)" % e)

    stride = (width * channels * depth + 7) // 8
    bpp = max(1, channels * depth // 8)
    maxval = (1 << depth) - 1

    def to8(v):
        return v >> 8 if depth == 16 else (v if depth == 8 else v * 255 // maxval)

    trns_key = None
    if trns and color_type == 0 and len(trns) >= 2:
        trns_key = (struct.unpack(">H", trns[:2])[0],)
    elif trns and color_type == 2 and len(trns) >= 6:
        trns_key = struct.unpack(">HHH", trns[:6])

    pixels, prev, i = [], bytearray(stride), 0
    for _ in range(height):
        if i + 1 + stride > len(raw):
            raise ValueError("PNG image data is truncated")
        line = bytearray(raw[i + 1:i + 1 + stride])
        _unfilter(raw[i], line, prev, bpp)
        i += 1 + stride
        prev = line
        for s in _samples(line, width, channels, depth):
            if color_type == 3:
                idx = s[0]
                if idx >= len(plte):
                    raise ValueError("PNG palette index out of range")
                r, g, b = plte[idx]
                a = trns[idx] if trns and idx < len(trns) else 255
            elif color_type == 0:
                r = g = b = to8(s[0])
                a = 0 if trns_key == s else 255
            elif color_type == 2:
                r, g, b = (to8(v) for v in s)
                a = 0 if trns_key == s else 255
            elif color_type == 4:
                r = g = b = to8(s[0])
                a = to8(s[1])
            else:
                r, g, b, a = (to8(v) for v in s)
            pixels.append((r, g, b, a))
    return PixelImage(width, height, pixels)


# ---------- BMP decode ----------
BMP_MAX_PIXELS = 4000000   # far beyond any rug; only stops a damaged header asking for gigabytes


def _mask_channel(mask):
    """(shift, max value) for a BMP bitfield mask, e.g. 0x7C00 -> (10, 31)."""
    if not mask:
        return None
    shift = (mask & -mask).bit_length() - 1
    return shift, mask >> shift


def decode_bmp(data):
    """Windows BMP, uncompressed: 1/2/4/8-bit with a palette, 16/24/32-bit, bitfields (16/32-bit),
    bottom-up or top-down. RLE-compressed BMPs are refused (rare; save as PNG instead).

    A 32-bit BMP whose alpha is 0 everywhere is read as opaque: many programs leave that byte
    empty rather than meaning "fully transparent"."""
    if len(data) < 26 or data[:2] != b"BM":
        raise ValueError("not a BMP file")
    offset, hsize = struct.unpack_from("<II", data, 10)
    if hsize == 12:                                   # old OS/2 header
        width, height, _planes, bpp = struct.unpack_from("<HHHH", data, 18)
        comp, ncolors, entry = 0, 0, 3
    elif hsize >= 40 and len(data) >= 14 + 40:
        width, height, _planes, bpp, comp = struct.unpack_from("<iiHHI", data, 18)
        ncolors, entry = struct.unpack_from("<I", data, 46)[0], 4
    else:
        raise ValueError("unsupported BMP header (size %d)" % hsize)
    top_down = height < 0
    height = abs(height)
    if width <= 0 or height <= 0 or width * height > BMP_MAX_PIXELS:
        raise ValueError("BMP size %d \u00d7 %d isn't usable" % (width, height))
    if comp in (1, 2):
        raise ValueError("compressed (RLE) BMPs aren't supported; save it again uncompressed "
                         "or as PNG")
    if comp not in (0, 3, 6) or bpp not in (1, 2, 4, 8, 16, 24, 32):
        raise ValueError("unsupported BMP type (%d bits per pixel, compression %d)" % (bpp, comp))

    masks = None                                      # (r, g, b, a) bitfields for 16/32-bit
    if bpp in (16, 32):
        if comp in (3, 6):
            if len(data) < 14 + 40 + 12:
                raise ValueError("BMP is truncated")
            r, g, b = struct.unpack_from("<III", data, 54)
            a = struct.unpack_from("<I", data, 66)[0] if (hsize >= 56 or comp == 6) and \
                len(data) >= 70 else 0
            masks = (r, g, b, a)
        elif bpp == 16:
            masks = (0x7C00, 0x03E0, 0x001F, 0)       # 5-5-5
        else:
            masks = (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    elif comp != 0:
        raise ValueError("unsupported BMP type (%d bits per pixel, compression %d)" % (bpp, comp))

    palette = None
    if bpp <= 8:
        n = ncolors or (1 << bpp)
        start = 14 + hsize
        if n > 256 or start + n * entry > len(data):
            raise ValueError("BMP palette is damaged")
        palette = [(data[start + i * entry + 2], data[start + i * entry + 1],
                    data[start + i * entry]) for i in range(n)]

    stride = (width * bpp + 31) // 32 * 4
    if offset + stride * height > len(data):
        raise ValueError("BMP image data is truncated")
    chans = [_mask_channel(m) for m in masks] if masks else None

    def scale(v, ch):                                 # a bitfield value to 0..255
        if not ch:
            return 0
        shift, top = ch
        return ((v >> shift) & top) * 255 // top if top else 0

    rows = [None] * height
    alpha_seen = False
    for y in range(height):
        line = data[offset + y * stride:offset + (y + 1) * stride]
        row = []
        if bpp <= 8:
            per = 8 // bpp
            for x in range(width):
                byte = line[x // per]
                idx = (byte >> (8 - bpp * (x % per + 1))) & ((1 << bpp) - 1)
                if idx >= len(palette):
                    raise ValueError("BMP palette index out of range")
                row.append(palette[idx] + (255,))
        elif bpp == 24:
            for x in range(width):
                b, g, r = line[3 * x:3 * x + 3]
                row.append((r, g, b, 255))
        else:
            size = bpp // 8
            for x in range(width):
                v = int.from_bytes(line[size * x:size * x + size], "little")
                a = scale(v, chans[3]) if chans[3] else 255
                if chans[3] and a:
                    alpha_seen = True
                row.append((scale(v, chans[0]), scale(v, chans[1]), scale(v, chans[2]), a))
        rows[y if top_down else height - 1 - y] = row
    pixels = [p for row in rows for p in row]
    if chans and chans[3] and not alpha_seen:         # alpha byte left empty: opaque
        pixels = [p[:3] + (255,) for p in pixels]
    return PixelImage(width, height, pixels)


# ---------- PNG encode ----------
def _chunk(ctype, body):
    return (struct.pack(">I", len(body)) + ctype + body +
            struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF))


def encode_png(img):
    """PNG bytes for a PixelImage (RGB if fully opaque, else RGBA), 8 bits per channel."""
    opaque = all(p[3] == 255 for p in img.pixels)
    rows = bytearray()
    w = img.width
    for y in range(img.height):
        rows.append(0)
        for p in img.pixels[y * w:(y + 1) * w]:
            rows.extend(p[:3] if opaque else p)
    ihdr = struct.pack(">IIBBBBB", img.width, img.height, 8, 2 if opaque else 6, 0, 0, 0)
    return (PNG_SIG + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(rows), 9)) +
            _chunk(b"IEND", b""))


# ---------- GIF (via Tk) ----------
def decode_gif_with_tk(data):
    import tkinter as tk
    img = tk.PhotoImage(data=base64.b64encode(data).decode("ascii"), format="gif")
    w, h = img.width(), img.height()
    pixels = []
    for y in range(h):
        for x in range(w):
            r, g, b = img.get(x, y)
            pixels.append((r, g, b, 0 if img.transparency_get(x, y) else 255))
    return PixelImage(w, h, pixels)


def decode(data):
    kind = sniff(data)
    if kind == "png":
        return decode_png(data)
    if kind == "gif":
        return decode_gif_with_tk(data)
    if kind == "bmp":
        return decode_bmp(data)
    if kind == "jpeg":
        raise ValueError("JPEG isn't supported: its compression smears pixel art into many "
                         "slightly different colors. Export the image as PNG instead.")
    raise ValueError("not a PNG, GIF or BMP image")


# ---------- colors ----------
def color_counts(img):
    """(Counter of '#RRGGBB' -> pixel count for opaque pixels, number of transparent pixels)."""
    counts = Counter()
    transparent = 0
    for r, g, b, a in img.pixels:
        if a < TRANSPARENT_BELOW:
            transparent += 1
        else:
            counts[to_hex(r, g, b)] += 1
    return counts, transparent
