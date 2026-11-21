"""Planning: yarn quantities, packs, canvas size, merged colors, yarn-list CSV, preview image. No Tk."""
import csv
import math
import os
import tempfile

from . import pixelart
from .colormath import parse_hex
from .palette import label, name_key

# Canvas defaults (my setup); each project can override them in its settings.
CANVAS_DEFAULTS = {
    "holes_per_inch": 3.75,
    "border_side": 3,     # folded under on the left and on the right
    "border_top": 8,      # folded over at the top (hanging loop)
    "border_bottom": 4,   # 3 folded under + 1 empty row (the edge isn't stable to hook into)
}


def canvas_settings(settings):
    out = dict(CANVAS_DEFAULTS)
    for k in out:
        try:
            v = float((settings or {}).get(k, out[k]))
            out[k] = v if k == "holes_per_inch" else int(round(v))
        except (TypeError, ValueError):
            pass
    if out["holes_per_inch"] <= 0:
        out["holes_per_inch"] = CANVAS_DEFAULTS["holes_per_inch"]
    return out


def with_spare(count, spare_percent):
    return math.ceil(count * (1 + spare_percent / 100.0) - 1e-9)


class YarnLine:
    def __init__(self, name, hex_, palette, brand="", pack=None):
        self.name, self.hex, self.palette = name, hex_, palette
        self.brand, self.pack = brand, pack   # pack: pieces per pre-cut pack, None = cut
        self.count = 0
        self.colors = []  # image hexes using this yarn

    @property
    def label(self):
        return label(self.name, self.brand)

    @property
    def merged(self):
        return len(self.colors) > 1

    def need(self, spare_percent):
        """(total pieces incl. spare, packs or None, readable text)."""
        n = with_spare(self.count, spare_percent)
        if self.pack:
            packs = math.ceil(n / self.pack)
            return n, packs, "%d pack%s" % (packs, "" if packs == 1 else "s")
        return n, None, "%s pieces" % format(n, ",")


class Plan:
    def __init__(self, project, resolve=None):
        """resolve(name, brand) -> (found, pack): the pack size from the open palette, so a
        changed pack size applies to existing projects; otherwise the saved snapshot is used."""
        img = project.image
        self.width, self.height = img.width, img.height
        self.spare = float(project.settings.get("spare_percent", 0) or 0)
        self.canvas = canvas_settings(project.settings)
        lines = {}
        self.unassigned = []
        for c in project.colors:
            if not (c.confirmed and c.yarn):
                self.unassigned.append(c)
                continue
            y = c.yarn
            brand = y.get("brand") or ""
            key = (name_key(y["name"]), name_key(brand), y["hex"].upper())
            line = lines.get(key)
            if line is None:
                pack = y.get("pack")
                if resolve:
                    found, p = resolve(y["name"], brand)
                    if found:
                        pack = p
                line = lines[key] = YarnLine(y["name"], y["hex"].upper(), y.get("palette", ""),
                                             brand, pack)
            line.count += c.count
            line.colors.append(c.hex)
        self.lines = sorted(lines.values(), key=lambda l: (-l.count, l.label.lower()))

    # ---------- sizes ----------
    def inches(self, cells):
        return cells / self.canvas["holes_per_inch"]

    @property
    def finished_in(self):
        return self.inches(self.width), self.inches(self.height)

    @property
    def canvas_cells(self):
        c = self.canvas
        return (self.width + 2 * c["border_side"],
                self.height + c["border_top"] + c["border_bottom"])

    @property
    def canvas_in(self):
        w, h = self.canvas_cells
        return self.inches(w), self.inches(h)

    # ---------- totals ----------
    @property
    def assigned_count(self):
        return sum(l.count for l in self.lines)

    @property
    def unassigned_count(self):
        return sum(c.count for c in self.unassigned)

    @property
    def total_packs(self):
        return sum(l.need(self.spare)[1] or 0 for l in self.lines)

    @property
    def total_pieces_to_cut(self):
        return sum(l.need(self.spare)[0] for l in self.lines if not l.pack)

    @property
    def merged(self):
        return [l for l in self.lines if l.merged]


def write_yarn_list(plan, path):
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".latchwork-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["yarn", "brand", "hex", "count", "spare_percent", "count_with_spare",
                        "pack_size", "packs", "pieces_to_cut", "image_colors", "palette"])
            for l in plan.lines:
                n, packs, _ = l.need(plan.spare)
                w.writerow([l.name, l.brand, l.hex, l.count, "%g" % plan.spare, n,
                            l.pack or "", packs if packs is not None else "",
                            "" if packs is not None else n, " ".join(l.colors), l.palette])
            w.writerow([])
            w.writerow(["TOTAL", "", "", plan.assigned_count, "%g" % plan.spare, "", "",
                        plan.total_packs, plan.total_pieces_to_cut, "", ""])
            if plan.unassigned:
                w.writerow(["UNASSIGNED", "", "", plan.unassigned_count, "", "", "", "", "",
                            " ".join(c.hex for c in plan.unassigned), ""])
            fw, fh_ = plan.finished_in
            cw, ch = plan.canvas_cells
            ciw, cih = plan.canvas_in
            w.writerow([])
            w.writerow(["finished size", "%d x %d holes" % (plan.width, plan.height),
                        "%.1f x %.1f in" % (fw, fh_)])
            w.writerow(["canvas to cut", "%d x %d holes" % (cw, ch), "%.1f x %.1f in" % (ciw, cih)])
            w.writerow(["holes per inch", "%g" % plan.canvas["holes_per_inch"]])
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def preview_pixels(project):
    """Image pixels with each color replaced by its yarn: the assigned one, or the suggested one
    for unassigned colors. Colors with no yarn at all stay original."""
    swap = {}
    for c in project.colors:
        if c.yarn:
            swap[c.rgb] = parse_hex(c.yarn["hex"])
    out = []
    for r, g, b, a in project.image.pixels:
        if a >= pixelart.TRANSPARENT_BELOW and (r, g, b) in swap:
            out.append(swap[(r, g, b)] + (a,))
        else:
            out.append((r, g, b, a))
    return out


def write_preview_png(project, path):
    img = pixelart.PixelImage(project.image.width, project.image.height, preview_pixels(project))
    data = pixelart.encode_png(img)
    with open(path, "wb") as fh:
        fh.write(data)


BA_BOX = 500                 # each picture fits in this many pixels (whole-number zoom)
BA_FRAME = 10                # gray border around each picture
BA_GAP = 20                  # white gap between the two
BA_GRAY = (216, 216, 216)    # the larger view's background; transparent knots show it too
BA_WHITE = (255, 255, 255)


def before_after_image(project):
    """The original and the yarn preview next to each other, for sharing: each zoomed by the
    largest whole number that fits BA_BOX (at least 1), in a gray frame, a white gap between.
    Side by side, or one above the other (original on top) when the art is wider than tall."""
    src = project.image
    w, h = src.width, src.height
    z = max(1, min(BA_BOX // w, BA_BOX // h))
    pw, ph = w * z + 2 * BA_FRAME, h * z + 2 * BA_FRAME        # one framed picture
    stacked = w > h
    W, H = (pw, 2 * ph + BA_GAP) if stacked else (2 * pw + BA_GAP, ph)
    cut = pixelart.TRANSPARENT_BELOW

    def rows(pixels):
        """The framed picture's rows, each a list of pw RGB tuples."""
        edge = [BA_GRAY] * pw
        out = [edge] * BA_FRAME
        for y in range(h):
            row = [BA_GRAY] * BA_FRAME
            for p in pixels[y * w:(y + 1) * w]:
                row.extend([p[:3] if p[3] >= cut else BA_GRAY] * z)
            row.extend([BA_GRAY] * BA_FRAME)
            out.extend([row] * z)
        return out + [edge] * BA_FRAME

    a, b = rows(src.pixels), rows(preview_pixels(project))
    if stacked:
        lines = a + [[BA_WHITE] * W] * BA_GAP + b
    else:
        gap = [BA_WHITE] * BA_GAP
        lines = [ra + gap + rb for ra, rb in zip(a, b)]
    pixels = [p + (255,) for line in lines for p in line]
    return pixelart.PixelImage(W, H, pixels)


def write_before_after_png(project, path):
    data = pixelart.encode_png(before_after_image(project))
    with open(path, "wb") as fh:
        fh.write(data)
