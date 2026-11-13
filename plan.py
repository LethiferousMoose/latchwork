"""Planning: yarn quantities, canvas size, merged colors, yarn-list CSV, preview image. No Tk."""
import csv
import math
import os
import tempfile

import pixelart
from colormath import parse_hex
from palette import brand_of, name_key

HOLES_PER_INCH = 3.75
BAG_SIZE = 320                 # Hershner's pre-cut pieces per bag
EXTRA_W = 6                    # 3-cell fold on each side
EXTRA_TOP, EXTRA_BOTTOM = 8, 4  # 8 fold at top (loop); 3 fold + 1 empty row at the bottom
EXTRA_H = EXTRA_TOP + EXTRA_BOTTOM


def inches(cells):
    return cells / HOLES_PER_INCH


def with_spare(count, spare_percent):
    return math.ceil(count * (1 + spare_percent / 100.0) - 1e-9)


class YarnLine:
    def __init__(self, name, hex_, palette):
        self.name, self.hex, self.palette = name, hex_, palette
        self.brand = brand_of(name)
        self.count = 0
        self.colors = []  # image hexes using this yarn

    @property
    def merged(self):
        return len(self.colors) > 1

    def need(self, spare_percent):
        """(total pieces incl. spare, bags or None, readable text)."""
        n = with_spare(self.count, spare_percent)
        if self.brand == "Hershner's":
            bags = math.ceil(n / BAG_SIZE)
            return n, bags, "%d bag%s" % (bags, "" if bags == 1 else "s")
        return n, None, "%s pieces" % format(n, ",")


class Plan:
    def __init__(self, project):
        img = project.image
        self.width, self.height = img.width, img.height
        self.spare = float(project.settings.get("spare_percent", 0) or 0)
        lines = {}
        self.unassigned = []
        for c in project.colors:
            if not (c.confirmed and c.yarn):
                self.unassigned.append(c)
                continue
            y = c.yarn
            key = (name_key(y["name"]), y["hex"].upper())
            line = lines.get(key)
            if line is None:
                line = lines[key] = YarnLine(y["name"], y["hex"].upper(), y.get("palette", ""))
            line.count += c.count
            line.colors.append(c.hex)
        self.lines = sorted(lines.values(), key=lambda l: (-l.count, l.name.lower()))

    # ---------- sizes ----------
    @property
    def finished_in(self):
        return inches(self.width), inches(self.height)

    @property
    def canvas_cells(self):
        return self.width + EXTRA_W, self.height + EXTRA_H

    @property
    def canvas_in(self):
        w, h = self.canvas_cells
        return inches(w), inches(h)

    # ---------- totals ----------
    @property
    def assigned_count(self):
        return sum(l.count for l in self.lines)

    @property
    def unassigned_count(self):
        return sum(c.count for c in self.unassigned)

    @property
    def total_bags(self):
        return sum(l.need(self.spare)[1] or 0 for l in self.lines)

    @property
    def total_pieces_to_cut(self):
        return sum(l.need(self.spare)[0] for l in self.lines if l.need(self.spare)[1] is None)

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
                        "bags", "pieces_to_cut", "image_colors", "palette"])
            for l in plan.lines:
                n, bags, _ = l.need(plan.spare)
                w.writerow([l.name, l.brand, l.hex, l.count, "%g" % plan.spare, n,
                            bags if bags is not None else "", "" if bags is not None else n,
                            " ".join(l.colors), l.palette])
            w.writerow([])
            w.writerow(["TOTAL", "", "", plan.assigned_count, "%g" % plan.spare, "",
                        plan.total_bags, plan.total_pieces_to_cut, "", ""])
            if plan.unassigned:
                w.writerow(["UNASSIGNED", "", "", plan.unassigned_count, "", "", "", "",
                            " ".join(c.hex for c in plan.unassigned), ""])
            fw, fh_ = plan.finished_in
            cw, ch = plan.canvas_cells
            ciw, cih = plan.canvas_in
            w.writerow([])
            w.writerow(["finished size", "%d x %d holes" % (plan.width, plan.height),
                        "%.1f x %.1f in" % (fw, fh_)])
            w.writerow(["canvas to cut", "%d x %d holes" % (cw, ch), "%.1f x %.1f in" % (ciw, cih)])
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def preview_pixels(project):
    """Image pixels with assigned colors replaced by their yarn; unassigned stay original."""
    swap = {}
    for c in project.colors:
        if c.confirmed and c.yarn:
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
