"""Pixel-art images: decode PNG exactly (stdlib zlib), GIF via Tk, encode PNG, count colors.

PNG pixel values are used as stored (no gamma or color-profile adjustment), the same values
GIMP shows for an untagged sRGB image.
"""
import base64
import struct
import zlib
from collections import Counter

from colormath import to_hex

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
    if kind == "jpeg":
        raise ValueError("JPEG isn't supported: its compression smears pixel art into many "
                         "slightly different colors. Export the image as PNG instead.")
    raise ValueError("not a PNG or GIF image")


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
