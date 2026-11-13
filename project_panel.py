"""Project sidebar: the pixel-art image, its colors with knot counts, and yarn assignments."""
import math
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from colormath import to_hex

BG = "#ECECEC"
UI_FONT = ("Segoe UI", 10)
IMG_W, IMG_H = 400, 260
TRANSPARENT_SHOW = "#F7F7F7"


def short_path(path, limit=62):
    """Keep the end of a long path (the file name matters most)."""
    return path if len(path) <= limit else "\u2026" + path[-(limit - 1):]


def _fade(hex_, amount=0.78):
    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return to_hex(*(c + (255 - c) * amount for c in (r, g, b)))


def _pair_image(left, right, w=40, h=16):
    """Image color | yarn color swatch for a list row (right may be None)."""
    img = tk.PhotoImage(width=w, height=h)
    half = w // 2
    img.put("#888888", to=(0, 0, half, h))
    img.put(left, to=(1, 1, half - 1, h - 1))
    if right:
        img.put("#888888", to=(half, 0, w, h))
        img.put(right, to=(half + 1, 1, w - 1, h - 1))
    return img


class ProjectPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG, padx=14, pady=12, width=IMG_W + 60)
        self.app = app
        self.project = None
        self.row_images = {}
        self.display = None
        self.scale = (1, 1)      # (zoom, subsample) used for the displayed image
        self.offset = (0, 0)
        self._quiet = False

        self.title = tk.Label(self, font=("Segoe UI", 16, "bold"), bg=BG, anchor="w")
        self.title.pack(fill="x")
        self.subtitle = tk.Label(self, font=("Segoe UI", 9), bg=BG, fg="#555", anchor="w",
                                 justify="left")
        self.subtitle.pack(fill="x")

        self.canvas = tk.Canvas(self, width=IMG_W, height=IMG_H, bg="#D8D8D8",
                                highlightthickness=1, highlightbackground="#AAA",
                                cursor="crosshair")
        self.canvas.pack(pady=(8, 2))
        self.canvas.bind("<Button-1>", self.on_image_click)
        self.highlight = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="Highlight the selected color in the image",
                        variable=self.highlight, command=self.render_image).pack(anchor="w")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, pady=(8, 0))
        self.tree = ttk.Treeview(body, columns=("knots", "yarn", "state"), selectmode="browse",
                                 height=10)
        for col, text, width, anchor in (("#0", "Color", 130, "w"), ("knots", "Knots", 55, "e"),
                                         ("yarn", "Yarn", 150, "w"), ("state", "", 70, "w")):
            self.tree.heading(col, text=text, anchor=anchor if col != "#0" else "w")
            self.tree.column(col, width=width, minwidth=40, anchor=anchor, stretch=(col == "yarn"))
        italic = tkfont.nametofont("TkDefaultFont").copy()
        italic.configure(slant="italic")
        self._italic = italic
        self.tree.tag_configure("suggested", foreground="#7A7A7A", font=italic)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())

        self.assigned_info = tk.Label(self, font=UI_FONT, bg=BG, anchor="w", justify="left",
                                      wraplength=IMG_W)
        self.assigned_info.pack(fill="x", pady=(8, 0))
        btns = tk.Frame(self, bg=BG)
        btns.pack(fill="x", pady=(6, 0))
        self.assign_btn = ttk.Button(btns, text="Assign current yarn (A)", command=app.assign)
        self.assign_btn.pack(side="left")
        self.unassign_btn = ttk.Button(btns, text="Back to suggestion", command=app.unassign)
        self.unassign_btn.pack(side="left", padx=6)
        self.progress = tk.Label(btns, font=("Segoe UI", 10, "bold"), bg=BG)
        self.progress.pack(side="right")

    # ---------- project ----------
    def set_project(self, project):
        self.project = project
        self.row_images = {}
        img = project.image
        self.hex_grid = [to_hex(r, g, b) if a >= 128 else TRANSPARENT_SHOW
                         for r, g, b, a in img.pixels]
        w, h = img.width, img.height
        if w <= IMG_W and h <= IMG_H:
            self.scale = (max(1, min(IMG_W // w, IMG_H // h)), 1)
        else:
            self.scale = (1, math.ceil(max(w / IMG_W, h / IMG_H)))
        self.title.config(text=project.name)
        sub = "%d × %d px  ·  %d colors  ·  %s knots" % (
            w, h, len(project.colors), format(project.knots, ","))
        if project.transparent:
            sub += "  ·  %s transparent (skipped)" % format(project.transparent, ",")
        self.subtitle.config(text=sub + "\n" + short_path(project.path))
        self.refresh_rows()
        self.render_image()

    def refresh_rows(self):
        keep = self.selected_hex()
        self._quiet = True
        self.tree.delete(*self.tree.get_children())
        for c in self.project.colors:
            self.tree.insert("", "end", iid=c.hex)
            self.update_row(c.hex)
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
        self._quiet = False
        self.update_footer()

    def update_row(self, hex_):
        c = self.project.entry(hex_)
        yhex = c.yarn["hex"] if c.yarn else None
        key = (c.hex, yhex)
        if key not in self.row_images:
            self.row_images[key] = _pair_image(c.hex, yhex)
        name = c.yarn["name"] if c.yarn else "(no yarns in palette)"
        state = "assigned" if c.confirmed else "suggested"
        self.tree.item(hex_, text="  " + c.hex, image=self.row_images[key],
                       values=(format(c.count, ","), name, state),
                       tags=() if c.confirmed else ("suggested",))
        self.update_footer()

    def update_footer(self):
        p = self.project
        if not p:
            return
        self.progress.config(text="%d / %d assigned" % (p.assigned_count, len(p.colors)))
        c = p.entry(self.selected_hex()) if self.selected_hex() else None
        if c is None:
            self.assigned_info.config(text="Select a color (or click the image) to match it.")
            self.assign_btn.state(["disabled"])
            self.unassign_btn.state(["disabled"])
            return
        self.assign_btn.state(["!disabled"] if self.app.yarns else ["disabled"])
        self.unassign_btn.state(["!disabled"] if c.confirmed else ["disabled"])
        if c.yarn is None:
            text = "%s: no yarn suggested (the open palette has no active yarns)." % c.hex
        else:
            y = c.yarn
            how = "Assigned" if c.confirmed else "Suggested"
            text = "%s: %s %s  %s  (from %s)" % (c.hex, how, y["name"], y["hex"],
                                                 y.get("palette") or "?")
            if c.confirmed and not self.app.yarn_in_palette(y):
                text += "\nThat yarn isn't in the open palette."
        self.assigned_info.config(text=text)

    # ---------- selection ----------
    def selected_hex(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def select(self, hex_):
        """Select a row without telling the app (the app already knows)."""
        self._quiet = True
        if hex_ and self.tree.exists(hex_):
            self.tree.selection_set(hex_)
            self.tree.see(hex_)
        else:
            self.tree.selection_set(())
        self._quiet = False
        self.update_footer()
        self.render_image()

    def on_select(self):
        if self._quiet:
            return
        self.update_footer()
        self.render_image()
        hex_ = self.selected_hex()
        if hex_:
            self.app.select_project_color(hex_)

    def on_image_click(self, event):
        if not self.project:
            return
        zoom, sub = self.scale
        x = (event.x - self.offset[0]) * sub // zoom
        y = (event.y - self.offset[1]) * sub // zoom
        img = self.project.image
        if 0 <= x < img.width and 0 <= y < img.height:
            r, g, b, a = img.pixel(x, y)
            if a >= 128:
                hex_ = to_hex(r, g, b)
                self.tree.selection_set(hex_)  # fires on_select -> app
                self.tree.see(hex_)

    # ---------- image ----------
    def render_image(self):
        c = self.canvas
        c.delete("all")
        if not self.project:
            return
        img = self.project.image
        sel = self.selected_hex() if self.highlight.get() else None
        grid = self.hex_grid
        if sel:
            faded = {}
            grid = [h if h == sel else faded.setdefault(h, _fade(h)) for h in grid]
        w = img.width
        rows = " ".join("{" + " ".join(grid[y * w:(y + 1) * w]) + "}" for y in range(img.height))
        base = tk.PhotoImage(width=w, height=img.height)
        base.put(rows, to=(0, 0))
        zoom, sub = self.scale
        self.display = base.zoom(zoom) if zoom > 1 else (base.subsample(sub) if sub > 1 else base)
        dw, dh = self.display.width(), self.display.height()
        self.offset = ((IMG_W - dw) // 2, (IMG_H - dh) // 2)
        c.create_image(self.offset[0], self.offset[1], image=self.display, anchor="nw")
