"""A rug project (.latchwork): the embedded image, its colors and their yarn assignments.

No Tk in here except GIF decoding (pixelart.decode), so it's unit-testable.

File format (JSON, version 1):
{
  "format": "latchwork-project", "version": 1,
  "image": {"filename": "dragon.png", "format": "png", "width": 64, "height": 48,
            "data": "<base64 of the original file bytes>"},
  "colors": [{"hex": "#88A048", "count": 123,
              "yarn": {"name": "Sage", "brand": "Loops & Threads", "pack": null,
                       "hex": "#959A78", "palette": "palette.csv"} | null,
              "confirmed": true, "carried_from": "mario-1"}],   # carried_from: optional
  "settings": {"spare_percent": 0, "holes_per_inch": 3.75, "border_side": 3, ...}
}
"""
import base64
import json
import os
import tempfile

from . import pixelart
from .colormath import lightness, match_order, parse_hex, rgb_to_lab, to_hex
from .palette import effective_pack, legacy_assignment, yarn_key

FORMAT = "latchwork-project"
VERSION = 1
EXTENSION = ".latchwork"
MANY_COLORS = 64  # more than this suggests the image isn't clean pixel art
# More than this is a photo or a smoothed/JPEG'd image, not pixel art, and is refused: every
# color gets its own swatch in the Colors list, and on Windows Tk aborts the whole program
# ("Fail to allocate bitmap") at around 5,000 of them.
MAX_COLORS = 1000


class ColorEntry:
    def __init__(self, hex_, count, yarn=None, confirmed=False):
        self.hex = hex_.upper()
        self.rgb = parse_hex(hex_)
        self.count = count
        self.L = lightness(*self.rgb)
        self.yarn = yarn            # {"name", "hex", "palette"} or None
        self.confirmed = confirmed  # True once I press Assign; False = a suggestion
        self.carried = None         # name of the project this assignment was carried over from

    def to_json(self):
        d = {"hex": self.hex, "count": self.count, "yarn": self.yarn,
             "confirmed": self.confirmed}
        if self.carried and self.confirmed:
            d["carried_from"] = self.carried
        return d


class Project:
    def __init__(self, path, image_bytes, image_format, image_filename, image, colors,
                 transparent=0, settings=None):
        self.path = path
        self.image_bytes, self.image_format = image_bytes, image_format
        self.image_filename = image_filename
        self.image = image
        self.colors = colors          # ColorEntry list, lightest -> darkest
        self.transparent = transparent
        self.settings = settings or {"spare_percent": 0}

    @property
    def name(self):
        return os.path.splitext(os.path.basename(self.path))[0]

    @property
    def knots(self):
        return sum(c.count for c in self.colors)

    def entry(self, hex_):
        hex_ = hex_.upper()
        return next((c for c in self.colors if c.hex == hex_), None)

    # ---------- create / load / save ----------
    @classmethod
    def from_image_file(cls, image_path, project_path):
        with open(image_path, "rb") as fh:
            data = fh.read()
        return cls.from_image_bytes(data, os.path.basename(image_path), project_path)

    @classmethod
    def from_image_bytes(cls, data, filename, project_path):
        fmt = pixelart.sniff(data)
        image = pixelart.decode(data)  # raises ValueError with a readable message
        if fmt == "bmp":   # kept as PNG: the same pixels, a fraction of the size
            data, fmt = pixelart.encode_png(image), "png"
        counts, transparent = pixelart.color_counts(image)
        if not counts:
            raise ValueError("the image has no opaque pixels")
        if len(counts) > MAX_COLORS:
            raise ValueError(
                "The image has %s different colors; Latchwork works with up to %s. That many "
                "usually means a photo, or pixel art that was scaled with smoothing or saved as "
                "JPEG at some point (even if it's a PNG or BMP now). Reduce it to its real "
                "colors in an image editor first (e.g. GIMP: Image \u2192 Mode \u2192 Indexed)."
                % (format(len(counts), ","), format(MAX_COLORS, ",")))
        colors = sorted((ColorEntry(h, n) for h, n in counts.items()), key=lambda c: -c.L)
        return cls(project_path, data, fmt, filename, image, colors, transparent)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as fh:
            try:
                doc = json.load(fh)
            except ValueError as e:
                raise ValueError("not a Latchwork project (%s)" % e)
        if not isinstance(doc, dict) or doc.get("format") != FORMAT:
            raise ValueError("not a Latchwork project file")
        if doc.get("version", 0) > VERSION:
            raise ValueError("made by a newer version of Latchwork (format %s)" % doc["version"])
        img = doc["image"]
        data = base64.b64decode(img["data"])
        project = cls.from_image_bytes(data, img.get("filename", ""), path)
        saved = {c["hex"].upper(): c for c in doc.get("colors", [])}
        for entry in project.colors:
            s = saved.get(entry.hex)
            if s and s.get("yarn"):
                y = s["yarn"]
                if parse_hex(y.get("hex", "")) and y.get("name"):
                    if "brand" in y:
                        name, brand, pack = y["name"], y.get("brand") or "", y.get("pack")
                    else:   # saved before brands existed: 'Gold RH' -> Gold (Red Heart)
                        name, brand, pack = legacy_assignment(y["name"])
                    entry.yarn = {"name": name, "brand": brand, "pack": pack,
                                  "hex": y["hex"].upper(), "palette": y.get("palette", "")}
                    entry.confirmed = bool(s.get("confirmed"))
                    if entry.confirmed and s.get("carried_from"):
                        entry.carried = str(s["carried_from"])
        project.settings.update(doc.get("settings") or {})
        return project

    def to_json(self):
        return {
            "format": FORMAT, "version": VERSION,
            "image": {"filename": self.image_filename, "format": self.image_format,
                      "width": self.image.width, "height": self.image.height,
                      "data": base64.b64encode(self.image_bytes).decode("ascii")},
            "colors": [c.to_json() for c in self.colors],
            "settings": self.settings,
        }

    def save(self):
        folder = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(prefix=".latchwork-", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_json(), fh, indent=1)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    # ---------- assignments ----------
    @staticmethod
    def snapshot(yarn, palette_name, brands=()):
        """What a project stores about a yarn, so it stays readable without the palette."""
        return {"name": yarn.sku, "brand": yarn.brand, "pack": effective_pack(yarn, brands),
                "hex": yarn.hex, "palette": palette_name}

    def suggest(self, yarns, palette_name, brands=(), weight=0.0):
        """Give every unconfirmed color the best match from `yarns` (active, sorted); see
        colormath.match_order for `weight` (0 = nearest lightness)."""
        labs = [y.lab for y in yarns]
        changed = False
        for c in self.colors:
            if c.confirmed:
                continue
            if not yarns:
                new = None
            else:
                y = yarns[match_order(rgb_to_lab(*c.rgb), labs, weight)[0]]
                new = self.snapshot(y, palette_name, brands)
            if new != c.yarn:
                c.yarn, changed = new, True
        return changed

    def assign(self, hex_, yarn, palette_name, brands=()):
        c = self.entry(hex_)
        c.yarn = self.snapshot(yarn, palette_name, brands)
        c.confirmed = True
        c.carried = None

    def unassign(self, hex_):
        """Back to a suggestion (filled in by the next suggest())."""
        c = self.entry(hex_)
        c.confirmed = False
        c.carried = None

    # ---------- carry over from earlier projects ----------
    def carry_options(self, sources):
        """What earlier projects could carry over into this one, by exact hex.

        sources: [(name, Project)], newest first. Only colors not assigned here yet are
        considered. Returns {hex: [(source name, yarn snapshot), ...]}: one option per distinct
        yarn (name + brand + hex), newest source first; more than one option is a conflict."""
        out = {}
        for c in self.colors:
            if c.confirmed:
                continue
            options, seen = [], set()
            for name, src in sources:
                e = src.entry(c.hex)
                if not (e and e.confirmed and e.yarn):
                    continue
                y = e.yarn
                key = (yarn_key(y["name"], y.get("brand") or ""), y["hex"].upper())
                if key not in seen:
                    seen.add(key)
                    options.append((name, dict(y)))
            if options:
                out[c.hex] = options
        return out

    def carry(self, hex_, yarn, source_name):
        """Assign a yarn snapshot taken from another project."""
        c = self.entry(hex_)
        c.yarn = dict(yarn)
        c.confirmed = True
        c.carried = source_name

    # ---------- assign from a yarn image ----------
    def read_yarn_image(self, image, yarns):
        """Read assignments from a yarn image: this rug's image, same size, recolored so every
        pixel is a yarn's exact color (how patterns were made by hand before Latchwork).

        yarns: every yarn of the palette; for a color shared by two, an active yarn wins.
        Returns {hex: result} for every color of this rug, where result is one of
          ("yarn", Yarn)                 all its pixels are that yarn's color
          ("split", [(hex, count), ...]) its pixels hold several colors, most first
          ("unknown", hex)               one color, but no yarn has it
          ("empty", None)                transparent in the yarn image
        Raises ValueError if the sizes differ."""
        if (image.width, image.height) != (self.image.width, self.image.height):
            raise ValueError(
                "The yarn image is %d × %d but this rug's image is %d × %d. It has to "
                "be the same size, one pixel per knot (not enlarged, no grid lines)."
                % (image.width, image.height, self.image.width, self.image.height))
        by_hex = {}
        for y in sorted(yarns, key=lambda y: y.retired):
            by_hex.setdefault(y.hex.upper(), y)
        seen = {}
        cut = pixelart.TRANSPARENT_BELOW
        for (r, g, b, a), (yr, yg, yb, ya) in zip(self.image.pixels, image.pixels):
            if a < cut:
                continue
            under = to_hex(yr, yg, yb) if ya >= cut else None
            counts = seen.setdefault(to_hex(r, g, b), {})
            counts[under] = counts.get(under, 0) + 1
        out = {}
        for c in self.colors:
            counts = seen.get(c.hex, {})
            if len(counts) > 1:
                out[c.hex] = ("split", sorted(counts.items(), key=lambda kv: -kv[1]))
            elif None in counts:
                out[c.hex] = ("empty", None)
            else:
                (h,) = counts
                out[c.hex] = ("yarn", by_hex[h]) if h in by_hex else ("unknown", h)
        return out

    @property
    def assigned_count(self):
        return sum(1 for c in self.colors if c.confirmed)
