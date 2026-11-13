"""Export a project as a self-contained HTML pattern for phone and print. No Tk.

The page is pattern_template.html with the pattern data embedded as JSON.
"""
import base64
import json
import os
import tempfile

import plan as pl
from colormath import lightness, parse_hex, to_hex

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "pattern_template.html")
PLACEHOLDER = "/*__LATCHWORK_DATA__*/null"
TRANSPARENT = 0xFFFF


def build_data(project):
    """Everything the page needs: yarn legend entries (most-used first) and one cell per knot."""
    plan = pl.Plan(project)
    entries, index_of = [], {}   # index_of: image hex -> legend index
    for line in plan.lines:
        n, bags, need = line.need(plan.spare)
        L = lightness(*parse_hex(line.hex))
        entries.append({"name": line.name, "hex": line.hex, "brand": line.brand,
                        "count": line.count, "need": need, "ink": "#000000" if L > 55 else "#FFFFFF",
                        "colors": line.colors, "unassigned": False})
    for c in plan.unassigned:
        entries.append({"name": "Unassigned %s" % c.hex, "hex": c.hex, "brand": "",
                        "count": c.count, "need": "", "colors": [c.hex], "unassigned": True,
                        "ink": "#000000" if c.L > 55 else "#FFFFFF"})
    entries.sort(key=lambda e: (e["unassigned"], -e["count"], e["name"].lower()))
    for i, e in enumerate(entries):
        for h in e["colors"]:
            index_of[h] = i

    img = project.image
    cells = bytearray()
    for r, g, b, a in img.pixels:
        i = index_of.get(to_hex(r, g, b)) if a >= 128 else None
        cells += (TRANSPARENT if i is None else i).to_bytes(2, "little")
    fw, fh = plan.finished_in
    cw, ch = plan.canvas_cells
    return {
        "version": 1,
        "key": "%s:%dx%d" % (project.name, img.width, img.height),
        "name": project.name,
        "width": img.width, "height": img.height,
        "knots": project.knots, "spare": plan.spare,
        "finished": "%.1f × %.1f in" % (fw, fh),
        "canvas": "%d × %d holes (%.1f × %.1f in)" % (cw, ch, *plan.canvas_in),
        "yarns": entries,
        "cells": base64.b64encode(bytes(cells)).decode("ascii"),   # uint16 little-endian
    }


def render_html(project, template_path=TEMPLATE):
    with open(template_path, encoding="utf-8") as fh:
        html = fh.read()
    if html.count(PLACEHOLDER) != 1:
        raise ValueError("pattern template is missing its data placeholder")
    data = json.dumps(build_data(project), separators=(",", ":"), ensure_ascii=False)
    data = data.replace("</", "<\\/")  # never close the <script> early
    title = project.name.replace("&", "&amp;").replace("<", "&lt;")
    return html.replace(PLACEHOLDER, data).replace("__LATCHWORK_TITLE__", title)


def export_pattern(project, path):
    html = render_html(project)
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".latchwork-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(html)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
