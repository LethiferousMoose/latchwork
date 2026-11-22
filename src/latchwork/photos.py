"""Yarn photos: load, average, copy into a palette's swatch folder (Tk does the image work).

Only PNG and GIF: that's what Tk reads without extra packages. Where the photo links are kept
is in palette.py (photos.csv in the palette's swatch folder).
"""
import os
import shutil
import tkinter as tk
from fractions import Fraction

from . import palette as pal
from .colormath import average_rgb, suggest_from_photo

MAX_SIDE = 400      # photos larger than this are shrunk when they're copied in
FILETYPES = [("Photos (PNG, GIF)", "*.png *.gif"), ("PNG", "*.png"), ("GIF", "*.gif")]


def load(path, master=None):
    """PhotoImage of a PNG/GIF. Raises ValueError with a readable message when it can't."""
    if os.path.splitext(path)[1].lower() not in pal.PHOTO_TYPES:
        raise ValueError("Only PNG and GIF photos can be read. Save a copy as PNG first "
                         "(GIMP, Paint or most photo viewers can).")
    try:
        return tk.PhotoImage(master=master, file=path)
    except tk.TclError as e:
        raise ValueError("Could not read %s\n\n%s" % (os.path.basename(path), e))


def shrink_factor(img, max_side=MAX_SIDE):
    """Whole-number step that brings the longest side to max_side or less (Tk subsample)."""
    side = max(img.width(), img.height())
    return max(1, -(-side // max_side))


def pixels(img):
    """(r, g, b) of every pixel."""
    out = []
    for row in img.tk.splitlist(img.tk.call(img.name, "data")):
        for c in img.tk.splitlist(row):
            out.append((int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)))
    return out


def colors(img):
    """(average, suggested palette color) of a photo, both sRGB 0..255 ints."""
    avg = average_rgb(pixels(img))
    return tuple(int(round(c)) for c in avg), suggest_from_photo(avg)


def cover(img, side):
    """A side x side square filling the frame with the photo, centered and cropped, like a
    profile picture. Tk only scales by whole numbers, so it zooms by p and shrinks by q with
    p/q just above the needed scale."""
    w, h = img.width(), img.height()
    short = min(w, h)
    pre = max(1, short // (side * 2))           # big photos: shrink most of the way first
    if pre > 1:
        img = img.subsample(pre)
        w, h = img.width(), img.height()
        short = min(w, h)
    f = Fraction(side, short).limit_denominator(8)
    if f * short < side:                        # rounded below: step up to cover the frame
        f = Fraction(-(-side * f.denominator // short), f.denominator)
    if f.numerator > 1:
        img = img.zoom(f.numerator)
    if f.denominator > 1:
        img = img.subsample(f.denominator)
    w, h = img.width(), img.height()
    x0, y0 = (w - side) // 2, (h - side) // 2
    out = tk.PhotoImage(master=img.tk, width=side, height=side)
    out.tk.call(out.name, "copy", img.name, "-from", max(0, x0), max(0, y0),
                max(0, x0) + min(side, w), max(0, y0) + min(side, h))
    return out


def copy_in(src, palette_path, yarn, img=None):
    """Copy a photo into the palette's swatch folder as 'Brand/Name.png' (shrunk when it's
    larger than MAX_SIDE). Returns the relative name to store in yarn.photo."""
    img = img or load(src)
    rel = pal.new_photo_name(palette_path, yarn)
    dst = os.path.join(pal.swatch_dir(palette_path), *rel.split("/"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    f = shrink_factor(img)
    if f == 1 and src.lower().endswith(".png"):
        shutil.copyfile(src, dst)
    else:
        (img.subsample(f) if f > 1 else img).write(dst, format="png")
    return rel
