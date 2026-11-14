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
              "confirmed": true}],
  "settings": {"spare_percent": 0, "holes_per_inch": 3.75, "border_side": 3, ...}
}
"""
import base64
import json
import os
import tempfile

import pixelart
from colormath import lightness, match_order, parse_hex, rgb_to_lab
from palette import effective_pack, legacy_assignment

FORMAT = "latchwork-project"
VERSION = 1
EXTENSION = ".latchwork"
MANY_COLORS = 64  # more than this suggests the image isn't clean pixel art


class ColorEntry:
    def __init__(self, hex_, count, yarn=None, confirmed=False):
        self.hex = hex_.upper()
        self.rgb = parse_hex(hex_)
        self.count = count
        self.L = lightness(*self.rgb)
        self.yarn = yarn            # {"name", "hex", "palette"} or None
        self.confirmed = confirmed  # True once I press Assign; False = a suggestion

    def to_json(self):
        return {"hex": self.hex, "count": self.count, "yarn": self.yarn,
                "confirmed": self.confirmed}


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
        counts, transparent = pixelart.color_counts(image)
        if not counts:
            raise ValueError("the image has no opaque pixels")
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

    def unassign(self, hex_):
        """Back to a suggestion (filled in by the next suggest())."""
        c = self.entry(hex_)
        c.confirmed = False

    @property
    def assigned_count(self):
        return sum(1 for c in self.colors if c.confirmed)
