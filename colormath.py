"""Color math for Latchwork, matching GIMP 2.10 (babl) exactly.

GIMP's LCh is CIE LCh(ab) computed from sRGB via babl's D50-adapted sRGB -> XYZ matrix.
L* was verified against GIMP's LCh selector (see CLAUDE.md). C and h use the same path.
"""
import math

# babl's sRGB -> XYZ (D50, Bradford-adapted) matrix, applied to linear-light RGB 0..1.
_M = (
    (0.4360747, 0.3850649, 0.1430804),
    (0.2225045, 0.7168786, 0.0606169),
    (0.0139322, 0.0971045, 0.7141733),
)
# D50 reference white (the matrix rows sum to these, so white -> a = b = 0).
_WX, _WY, _WZ = 0.9642200, 1.0, 0.8252100

_EPS = 216 / 24389
_KAPPA = 24389 / 27


def srgb_decode(c):
    """sRGB 0..255 -> linear 0..1."""
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def srgb_encode(v):
    """linear 0..1 -> sRGB 0..255 (float, clamped)."""
    v = min(1.0, max(0.0, v))
    c = v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return c * 255.0


def _f(t):
    return t ** (1 / 3) if t > _EPS else (_KAPPA * t + 16) / 116


def lightness(r, g, b):
    """CIE L* (0..100) of an sRGB 0..255 color, exactly as GIMP's LCh selector shows it."""
    y = _M[1][0] * srgb_decode(r) + _M[1][1] * srgb_decode(g) + _M[1][2] * srgb_decode(b)
    return 116 * y ** (1 / 3) - 16 if y > _EPS else y * _KAPPA


def rgb_to_lab(r, g, b):
    lin = (srgb_decode(r), srgb_decode(g), srgb_decode(b))
    x, y, z = (sum(m * c for m, c in zip(row, lin)) for row in _M)
    fx, fy, fz = _f(x / _WX), _f(y / _WY), _f(z / _WZ)
    return lightness(r, g, b), 500 * (fx - fy), 200 * (fy - fz)


def rgb_to_lch(r, g, b):
    """(L, C, h) with h in degrees 0..360."""
    L, a, bb = rgb_to_lab(r, g, b)
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def _inverse3(m):
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return ((( e * i - f * h) / det, -(b * i - c * h) / det, ( b * f - c * e) / det),
            (-(d * i - f * g) / det, ( a * i - c * g) / det, -(a * f - c * d) / det),
            (( d * h - e * g) / det, -(a * h - b * g) / det, ( a * e - b * d) / det))


_MINV = _inverse3(_M)


def _finv(t):
    return t ** 3 if t ** 3 > _EPS else (116 * t - 16) / _KAPPA


def lch_to_rgb(L, C, h):
    """CIE LCh(ab) -> sRGB 0..255 floats, clamped to the sRGB gamut (for drawing gradients)."""
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    fy = (L + 16) / 116
    x = _finv(fy + a / 500) * _WX
    y = fy ** 3 if L > _KAPPA * _EPS else L / _KAPPA
    z = _finv(fy - b / 200) * _WZ
    return tuple(srgb_encode(sum(m * v for m, v in zip(row, (x, y, z)))) for row in _MINV)


def gray_for_lightness(L):
    """sRGB 0..255 gray level whose L* equals L (R = G = B, so Y = linear value)."""
    y = ((L + 16) / 116) ** 3 if L > _KAPPA * _EPS else L / _KAPPA
    return srgb_encode(y)


def parse_hex(text):
    """'#88A048', '88a048', ' #88A048 ' -> (136, 160, 72); anything else -> None."""
    s = text.strip()
    if s.startswith("#"):
        s = s[1:].strip()
    if len(s) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in s):
        return None
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def to_hex(r, g, b):
    return "#%02X%02X%02X" % (int(round(r)), int(round(g)), int(round(b)))


def nearest_index(target_L, Ls):
    """Index of the value in Ls closest to target_L. Ties go to the earliest index."""
    best, best_d = None, None
    for i, L in enumerate(Ls):
        d = abs(L - target_L)
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best
