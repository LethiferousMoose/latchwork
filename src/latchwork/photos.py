"""Yarn photos: load, average, copy into a palette's swatch folder (Tk does the image work).

Only PNG and GIF: that's what Tk reads without extra packages. Where the photo links are kept
is in palette.py (photos.csv in the palette's swatch folder).
"""
import os
import shutil
import tkinter as tk

from . import palette as pal
from .colormath import average_rgb, suggest_from_photo

MAX_SIDE = 1280     # photos larger than this are shrunk (by whole steps) when they're copied in
AVERAGE_SIDE = 400  # colors are averaged on a copy shrunk to about this (same result, faster)
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


def shrink_factor(img, max_side):
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
    f = shrink_factor(img, AVERAGE_SIDE)
    avg = average_rgb(pixels(img.subsample(f) if f > 1 else img))
    return tuple(int(round(c)) for c in avg), suggest_from_photo(avg)


def thumbnail(img, max_side):
    f = shrink_factor(img, max_side)
    return img.subsample(f) if f > 1 else img


def cover_texture(img, w, h):
    """(image, x offset, y offset) covering a w x h picture, like a photo layer behind it:
    every color's knots show their own yarn's photo. Never enlarged (that only blurs it):
    a photo that covers the picture is shrunk by the largest whole step that still covers
    and centered; a smaller one is repeated at its own size."""
    pw, ph = img.width(), img.height()
    if pw >= w and ph >= h:
        f = min(pw // w, ph // h)
        if f > 1:
            img = img.subsample(f)
        return img, (img.width() - w) // 2, (img.height() - h) // 2
    tiled = tk.PhotoImage(master=img.tk, width=w, height=h)
    tiled.tk.call(tiled.name, "copy", img.name, "-to", 0, 0, w, h)   # Tk repeats the source
    return tiled, 0, 0


def copy_in(src, palette_path, yarn, img=None):
    """Copy a photo into the palette's swatch folder as 'Brand/Name.png', at its own size up to
    MAX_SIDE (a big photo covers a big picture without repeating; Tk can only shrink by whole
    steps, so a 2000 px photo comes in at 1000). Returns the relative name to store in
    yarn.photo."""
    img = img or load(src)
    rel = pal.new_photo_name(palette_path, yarn)
    dst = os.path.join(pal.swatch_dir(palette_path), *rel.split("/"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    f = shrink_factor(img, MAX_SIDE)
    if f == 1 and src.lower().endswith(".png"):
        shutil.copyfile(src, dst)
    else:
        (img.subsample(f) if f > 1 else img).write(dst, format="png")
    return rel
