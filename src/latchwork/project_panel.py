"""Project sidebar: the image (original or yarn preview, flat or textured with yarn photos), its
colors and assignments, and the plan."""
import math
import os
import tkinter as tk
from collections import OrderedDict
import tkinter.font as tkfont
from tkinter import ttk

from . import palette as pal
from . import photos
from . import plan as pl
from .palette import label as yarn_label
from .colormath import gray_for_lightness, lightness, parse_hex, to_hex
from .widgets import Tooltip, TreeSort

BG = "#ECECEC"
UI_FONT = ("Segoe UI", 10)
IMG_W, IMG_H = 400, 250
TRANSPARENT_SHOW = "#F7F7F7"
TABLE_ROWS = 6     # requested table height; tables shrink on short windows
# Yarn photos kept in memory besides the ones the picture uses (stepping back is instant, and
# memory stays bounded: a 1280 px photo takes about 6 MB).
SPARE_PHOTOS = 12
# Textures are painted into strips about this tall, then each strip into the picture: every
# copy into a Tk photo costs time in proportion to the size of the image copied into.
TEXTURE_BAND = 32


def fit_scale(w, h, box_w, box_h):
    """(zoom, subsample) showing a w x h image as large as fits in box_w x box_h, keeping every
    pixel the same size: a whole-number zoom, or a whole-number shrink for big images."""
    if w <= box_w and h <= box_h:
        return max(1, min(box_w // w, box_h // h)), 1
    return 1, math.ceil(max(w / box_w, h / box_h))


FADE_DARK = 58           # highlight a light color: the rest fades toward this gray, not white
LIGHT_SELECTION = 65     # L* from which the selected color counts as light


def _fade(hex_, amount=0.78, toward=255):
    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return to_hex(*(c + (toward - c) * amount for c in (r, g, b)))


def _gray(hex_):
    v = gray_for_lightness(lightness(*parse_hex(hex_)))
    return to_hex(v, v, v)


def _pair_image(left, right, w=40, h=16):
    """Two-color swatch for a list row (right may be None)."""
    img = tk.PhotoImage(width=w, height=h)
    half = w // 2
    img.put("#888888", to=(0, 0, half, h))
    img.put(left, to=(1, 1, half - 1, h - 1))
    if right:
        img.put("#888888", to=(half, 0, w, h))
        img.put(right, to=(half + 1, 1, w - 1, h - 1))
    return img


def _swatch(hex_, w=18, h=14):
    img = tk.PhotoImage(width=w, height=h)
    img.put("#888888", to=(0, 0, w, h))
    img.put(hex_, to=(1, 1, w - 1, h - 1))
    return img


class ProjectPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG, padx=14, pady=12, width=IMG_W + 60)
        self.pack_propagate(False)  # fixed width; contents wrap instead of widening the sidebar
        self.app = app
        self.project = None
        self.row_images = {}
        self.plan_images = {}
        self.display = None
        self.scale = (1, 1)      # (zoom, subsample) used for the displayed image
        self.offset = (0, 0)
        self.large = None        # the "View larger" window, while open
        self._large_geometry = None
        self._quiet = False
        # yarn photo path -> (mtime, PhotoImage), least recently used first (see _trim_textures)
        self._photos = OrderedDict()
        self._textures = {}      # (path, mtime, w, h) -> (image, x offset, y offset)
        self._texture_sizes = []  # picture sizes drawn lately (sidebar, larger view), newest last
        self._render_job = None  # a picture redraw waiting for the app to be idle
        italic = tkfont.nametofont("TkDefaultFont").copy()
        italic.configure(slant="italic")
        self._italic = italic

        # ----- shown when no project is open -----
        self.welcome = tk.Frame(self, bg=BG, width=IMG_W + 30)
        tk.Label(self.welcome, text="No project open", font=("Segoe UI", 16, "bold"),
                 bg=BG).pack(anchor="w")
        tk.Label(self.welcome, bg=BG, fg="#555", justify="left", wraplength=IMG_W,
                 font=UI_FONT, text="Start a rug from a pixel-art image (PNG, GIF or BMP), or open a "
                                    "saved .latchwork project. You can also match single colors "
                                    "on the right without a project.").pack(anchor="w", pady=(4, 12))
        start = tk.Frame(self.welcome, bg=BG)
        start.pack(anchor="w")
        for row, (text, keys, cmd) in enumerate((
                ("New project from image...", "Ctrl+N", app.new_project),
                ("Open project...", "Ctrl+O", app.open_project))):
            ttk.Button(start, text=text, width=28, command=cmd).grid(
                row=row, column=0, sticky="ew", ipady=3, pady=3)
            tk.Label(start, text=keys, font=("Segoe UI", 9), bg=BG, fg="#888").grid(
                row=row, column=1, sticky="w", padx=(10, 0))

        # ----- shown when a project is open -----
        self.content = tk.Frame(self, bg=BG)
        c = self.content
        self.subtitle = tk.Label(c, font=("Segoe UI", 9), bg=BG, fg="#555", anchor="w",
                                 justify="left")
        self.subtitle.pack(fill="x")

        views = tk.Frame(c, bg=BG)
        views.pack(fill="x", pady=(8, 4))
        self.view = tk.StringVar(value="original")
        for value, text in (("original", "Original"), ("preview", "Yarn preview")):
            ttk.Radiobutton(views, text=text, value=value, variable=self.view, style="Toolbutton",
                            command=self.on_view).pack(side="left", ipadx=8)
        self.texture = tk.BooleanVar(value=False)
        self.texture_cb = ttk.Checkbutton(views, text="Texture", variable=self.texture,
                                          command=self.render_image)
        self.texture_cb.pack(side="left", padx=(12, 0))
        Tooltip(self.texture_cb, lambda e: (None, [([], (
            "Yarn preview with each yarn's photo instead of its flat color (T),\n"
            "like a photo layer behind the picture. Yarns without a photo stay\n"
            "flat; so does everything in grayscale, and the colors that\n"
            "Highlight fades or Mark unassigned stripes."))]))
        larger = tk.Label(views, text="View larger", font=("Segoe UI", 9, "underline"), bg=BG,
                          fg="#1565C0", cursor="hand2")
        larger.pack(side="right", padx=(0, 4))
        larger.bind("<Button-1>", lambda e: self.open_large())

        self.canvas = tk.Canvas(c, width=IMG_W, height=IMG_H, bg="#D8D8D8",
                                highlightthickness=1, highlightbackground="#AAA",
                                cursor="crosshair")
        self.canvas.pack(pady=(2, 2))
        self.canvas.bind("<Button-1>", self.on_image_click)
        opts = tk.Frame(c, bg=BG)
        opts.pack(fill="x")
        self.highlight = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Highlight selected color", variable=self.highlight,
                        command=self.render_image).pack(side="left")
        self.mark_unassigned = tk.BooleanVar(value=False)
        self.mark_cb = ttk.Checkbutton(opts, text="Mark unassigned (preview)",
                                       variable=self.mark_unassigned, command=self.render_image)
        self.mark_cb.pack(side="left", padx=(16, 0))

        self.tabs = ttk.Notebook(c)
        self.tabs.pack(fill="both", expand=True, pady=(8, 0))
        self._build_colors_tab()
        self._build_plan_tab()
        self.show_welcome()

    # ---------- tabs ----------
    def _build_colors_tab(self):
        tab = tk.Frame(self.tabs, bg=BG, padx=4, pady=6)
        self.tabs.add(tab, text="  Colors  ")
        # Bottom parts are packed first so a short window squeezes the table, never the buttons.
        btns = tk.Frame(tab, bg=BG)
        btns.pack(side="bottom", fill="x", pady=(6, 0))
        self.progress = tk.Label(btns, font=("Segoe UI", 10, "bold"), bg=BG)
        self.progress.pack(side="right")
        info = tk.Frame(tab, bg=BG)
        info.pack(side="bottom", fill="x", pady=(8, 0))
        self._no_pair = tk.PhotoImage(width=40, height=16)   # keeps the text in place
        self.info_swatch = tk.Label(info, bg=BG, image=self._no_pair)
        self.info_swatch.pack(side="left", padx=(2, 10))
        text = tk.Frame(info, bg=BG)
        text.pack(side="left", fill="x", expand=True)
        self.info_title = tk.Label(text, font=("Segoe UI", 10, "bold"), bg=BG, anchor="w")
        self.info_title.pack(fill="x")
        # always two lines high, so the list above doesn't jump as the text changes
        self.info_sub = tk.Label(text, font=("Segoe UI", 9), bg=BG, fg="#666", anchor="nw",
                                 justify="left", wraplength=IMG_W - 70, height=2)
        self.info_sub.pack(fill="x")

        body = tk.Frame(tab, bg=BG)
        body.pack(side="top", fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("count", "yarn", "state"), selectmode="browse",
                                 height=TABLE_ROWS)
        for col, text, width, anchor in (("#0", "Color", 130, "w"), ("count", "Count", 55, "e"),
                                         ("yarn", "Yarn", 145, "w"), ("state", "Status", 70, "w")):
            self.tree.heading(col, text=text, anchor=anchor if col != "#0" else "w")
            self.tree.column(col, width=width, minwidth=40, anchor=anchor, stretch=False)
        self.tree.tag_configure("suggested", foreground="#7A7A7A", font=self._italic)
        _scrolled(body, self.tree)
        self.tree.bind("<Configure>", lambda e: self.size_columns())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        # Clickable headings. Color sorts by lightness (L*); the default order is lightest first,
        # so the first click shows darkest first. Status: suggested, carried over, assigned.
        entry = lambda iid: self.project.entry(iid)
        self.color_sort = TreeSort(self.tree, {
            "#0": (lambda i: entry(i).L, False),
            "count": (lambda i: entry(i).count, True),
            "yarn": (lambda i: self.tree.set(i, "yarn").lower(), False),
            "state": (lambda i: (entry(i).confirmed, not entry(i).carried), False),
        }, default=lambda i: self._color_order[i], on_change=lambda st: self._sort_changed("colors", st))

    def _build_plan_tab(self):
        tab = tk.Frame(self.tabs, bg=BG, padx=4, pady=6)
        self.tabs.add(tab, text="  Plan  ")
        # Same shape as the Colors tab: table on top, details below. Exports live in the File
        # menu (Ctrl+E for the pattern).
        tk.Label(tab, text="Export the pattern, yarn list or preview from the File menu "
                           "(Ctrl+E = pattern).", font=("Segoe UI", 8), bg=BG, fg="#888",
                 anchor="w").pack(side="bottom", fill="x", pady=(6, 0))
        lower = tk.Frame(tab, bg=BG)
        lower.pack(side="bottom", fill="x")
        self.totals = tk.Label(lower, font=("Segoe UI", 10, "bold"), bg=BG, anchor="w",
                               justify="left")
        self.totals.pack(fill="x", pady=(6, 0))
        self.notes = tk.Label(lower, font=("Segoe UI", 9), bg=BG, fg="#555", anchor="w",
                              justify="left", wraplength=IMG_W)
        self.notes.pack(fill="x")
        sizes = tk.Frame(lower, bg=BG)
        sizes.pack(fill="x", pady=(8, 0))
        self.size_vals = {}
        for row, key in enumerate(("Finished size", "Canvas to cut")):
            tk.Label(sizes, text=key, font=UI_FONT, bg=BG, fg="#555").grid(row=row, column=0,
                                                                          sticky="w")
            v = tk.Label(sizes, font=("Segoe UI", 10, "bold"), bg=BG)
            v.grid(row=row, column=1, sticky="w", padx=10)
            self.size_vals[key] = v
        note = tk.Frame(sizes, bg=BG)
        note.grid(row=2, column=0, columnspan=2, sticky="w")
        self.canvas_note = tk.Label(note, font=("Segoe UI", 8), bg=BG, fg="#888", justify="left")
        self.canvas_note.pack(side="left")
        link = tk.Label(note, text="Change…", font=("Segoe UI", 8, "underline"), bg=BG,
                        fg="#1565C0", cursor="hand2")
        link.pack(side="left", padx=(6, 0))
        link.bind("<Button-1>", lambda e: self.edit_canvas())
        spare = tk.Frame(sizes, bg=BG)
        spare.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        tk.Label(spare, text="Spare", font=UI_FONT, bg=BG).pack(side="left")
        self.spare_var = tk.StringVar(value="0")
        sp = ttk.Spinbox(spare, from_=0, to=100, increment=5, width=4, textvariable=self.spare_var,
                         command=self.on_spare)
        sp.pack(side="left", padx=4)
        sp.bind("<Return>", lambda e: self.on_spare())
        sp.bind("<FocusOut>", lambda e: self.on_spare())
        tk.Label(spare, text="%   added to every count before packs and pieces",
                 font=("Segoe UI", 9), bg=BG, fg="#666").pack(side="left")

        body = tk.Frame(tab, bg=BG)
        body.pack(side="top", fill="both", expand=True)
        self.plan_tree = ttk.Treeview(body, columns=("count", "need", "colors"), selectmode="none",
                                      height=TABLE_ROWS)
        for col, text, width, anchor in (("#0", "Yarn (assigned)", 190, "w"),
                                         ("count", "Count", 55, "e"), ("need", "Need", 95, "e"),
                                         ("colors", "Colors", 55, "e")):
            self.plan_tree.heading(col, text=text, anchor="w" if col == "#0" else anchor)
            self.plan_tree.column(col, width=width, minwidth=40, anchor=anchor,
                                  stretch=(col == "#0"))
        self.plan_tree.tag_configure("merged", background="#FFF4CC")
        line = lambda iid: self._plan.lines[int(iid)]
        self.plan_sort = TreeSort(self.plan_tree, {
            "#0": (lambda i: line(i).label.lower(), False),
            "count": (lambda i: line(i).count, True),
            "need": (lambda i: line(i).need(self._plan.spare)[0], True),   # pieces incl. spare
            "colors": (lambda i: len(line(i).colors), True),
        }, default=int, on_change=lambda st: self._sort_changed("plan", st))
        _scrolled(body, self.plan_tree)
        self._plan = None
        Tooltip(self.plan_tree, self._merged_row_tip)
        Tooltip(self.notes, self._merged_summary_tip)

    # ---------- project ----------
    def show_welcome(self):
        self.project = None
        if self.large:
            self.large.destroy()
        self.content.pack_forget()
        self.welcome.pack(fill="both", expand=True)

    def set_project(self, project):
        self.project = project
        self.welcome.pack_forget()
        self.content.pack(fill="both", expand=True)
        self.row_images = {}
        img = project.image
        self.orig_hex = [to_hex(r, g, b) if a >= 128 else None for r, g, b, a in img.pixels]
        w, h = img.width, img.height
        self.scale = fit_scale(w, h, IMG_W, IMG_H)
        sub = "%d × %d px  ·  %d colors  ·  %s total" % (
            w, h, len(project.colors), format(project.knots, ","))
        if project.transparent:
            sub += "  ·  %s transparent (skipped)" % format(project.transparent, ",")
        self.subtitle.config(text=sub)
        self.spare_var.set("%g" % float(project.settings.get("spare_percent", 0) or 0))
        sort = project.settings.get("sort") or {}
        self._color_order = {c.hex: i for i, c in enumerate(project.colors)}
        self.color_sort.state = None
        self.plan_sort.state = None
        self.refresh_rows()   # also fills the plan
        self.color_sort.set(sort.get("colors"))
        self.plan_sort.set(sort.get("plan"))
        self.size_columns()
        self.on_view()

    def _sort_changed(self, table, state):
        """A heading was clicked: keep the order with the project (saved like the spare %)."""
        if not self.project:
            return
        sort = dict(self.project.settings.get("sort") or {})
        if state:
            sort[table] = state
        else:
            sort.pop(table, None)
        if sort:
            self.project.settings["sort"] = sort
        else:
            self.project.settings.pop("sort", None)
        self.app.save_project()

    def refresh_rows(self):
        keep = self.selected_hex()
        self._quiet = True
        self.tree.delete(*self.tree.get_children())
        for c in self.project.colors:
            self.tree.insert("", "end", iid=c.hex)
            self._fill_row(c)
        self.color_sort.apply()
        self.size_columns()
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
        self._quiet = False
        self.update_footer()
        self.refresh_plan()

    def update_row(self, hex_, plan=True):
        self._fill_row(self.project.entry(hex_))
        if plan:
            self.size_columns()
        self.update_footer()
        if plan:
            self.refresh_plan()
            self.render_image()

    def _fill_row(self, c):
        yhex = c.yarn["hex"] if c.yarn else None
        key = (c.hex, yhex)
        if key not in self.row_images:
            self.row_images[key] = _pair_image(c.hex, yhex)
        name = yarn_label(c.yarn["name"], c.yarn.get("brand")) if c.yarn \
            else "(no yarns in palette)"
        state = ("carried over" if c.carried else "assigned") if c.confirmed else "suggested"
        if c.candidates:
            state += " \u2605%d" % len(c.candidates)
        self.tree.item(c.hex, text="  " + c.hex, image=self.row_images[key],
                       values=(format(c.count, ","), name, state),
                       tags=() if c.confirmed else ("suggested",))

    def size_columns(self):
        """Color, Count and status fit their contents; Yarn takes the rest (scrolls if long)."""
        t = self.tree
        # Status always has room for its longest text, so marking a candidate (the star)
        # or carrying a color over never resizes the table.
        _fit_columns(t, {"#0": (64, None), "count": (14, None),
                         "yarn": (16, self._italic),
                         "state": (14, self._italic, ["carried over \u26059"])})
        # Yarn takes exactly the leftover width (no stretch), so the total never overshoots
        # the visible area by a few pixels and the horizontal scrollbar only moves when a
        # name really doesn't fit.
        cols = ("#0", "count", "yarn", "state")
        need = sum(int(t.column(c, "minwidth")) for c in cols) + TREE_BORDER
        # The sidebar has a fixed width, but text grows with Windows display scaling; widen
        # the sidebar just enough for the table (up to half the screen) instead of scrolling.
        chrome = self.winfo_width() - t.winfo_width()
        if t.winfo_width() > 1 and chrome > 0:
            want = min(max(IMG_W + 60, need + chrome), self.winfo_screenwidth() // 2)
            if want != int(self.cget("width")):
                self.configure(width=want)
                return   # the resize fires <Configure> again, which sizes the Yarn column
        others = sum(int(t.column(c, "width")) for c in ("#0", "count", "state"))
        avail = t.winfo_width() - TREE_BORDER - others
        t.column("yarn", width=max(int(t.column("yarn", "minwidth")), avail))

    def update_footer(self):
        p = self.project
        if not p:
            return
        self.progress.config(text="%d / %d assigned" % (p.assigned_count, len(p.colors)))
        c = p.entry(self.selected_hex()) if self.selected_hex() else None
        if c is None:
            self.info_swatch.config(image=self._no_pair)
            self.info_title.config(text="No color selected")
            self.info_sub.config(text="Pick a color in the list or click the image, then step "
                                      "through yarns and press Assign (A).")
            return
        yhex = c.yarn["hex"] if c.yarn else None
        key = (c.hex, yhex)
        if key not in self.row_images:
            self.row_images[key] = _pair_image(c.hex, yhex)
        self.info_swatch.config(image=self.row_images[key])
        if c.yarn is None:
            self.info_title.config(text="%s  \u2192  no yarn" % c.hex)
            self.info_sub.config(text="The open palette has no active yarns.")
            return
        y = c.yarn
        self.info_title.config(text="%s  \u2192  %s" % (c.hex, yarn_label(y["name"],
                                                                          y.get("brand"))))
        if c.confirmed:
            sub = "%s \u00B7 %s \u00B7 from %s" % (
                "Carried over from " + c.carried if c.carried else "Assigned", y["hex"],
                y.get("palette") or "?")
            if not self.app.yarn_in_palette(y):
                sub += "\nNot in the open palette."
        else:
            sub = "Suggested (not assigned yet) \u00B7 %s \u00B7 %s" % (
                y["hex"], y.get("palette") or "?")
        self.info_sub.config(text=sub)

    # ---------- plan ----------
    def on_spare(self):
        if not self.project:
            return
        try:
            v = max(0.0, min(100.0, float(self.spare_var.get())))
        except ValueError:
            v = 0.0
        self.spare_var.set("%g" % v)
        if v != float(self.project.settings.get("spare_percent", 0) or 0):
            self.project.settings["spare_percent"] = v
            self.app.save_project()
            self.refresh_plan()

    def refresh_plan(self):
        if not self.project:
            return
        plan = self._plan = pl.Plan(self.project, self.app.resolve)
        cv = plan.canvas
        self.canvas_note.config(text="%g holes/inch · borders: %d each side, %d top, %d bottom"
                                % (cv["holes_per_inch"], cv["border_side"], cv["border_top"],
                                   cv["border_bottom"]))
        fw, fh = plan.finished_in
        cw, ch = plan.canvas_cells
        ciw, cih = plan.canvas_in
        self.size_vals["Finished size"].config(
            text="%.1f × %.1f in   (%d × %d holes)" % (fw, fh, plan.width, plan.height))
        self.size_vals["Canvas to cut"].config(
            text="%.1f × %.1f in   (%d × %d holes)" % (ciw, cih, cw, ch))
        self.plan_tree.delete(*self.plan_tree.get_children())
        for i, l in enumerate(plan.lines):
            img = self.plan_images.get(l.hex)
            if img is None:
                img = self.plan_images[l.hex] = _swatch(l.hex)
            self.plan_tree.insert("", "end", iid=str(i), text="  %s" % l.label, image=img,
                                  values=(format(l.count, ","), l.need(plan.spare)[2],
                                          len(l.colors)),
                                  tags=("merged",) if l.merged else ())
        self.plan_sort.apply()
        _fit_columns(self.plan_tree, {"#0": (42, None), "count": (14, None),
                                      "need": (14, None), "colors": (14, None)})
        parts = ["%s assigned" % format(plan.assigned_count, ",")]
        if plan.total_packs:
            parts.append("%d pack%s" % (plan.total_packs, "" if plan.total_packs == 1 else "s"))
        if plan.total_pieces_to_cut:
            parts.append("%s pieces to cut" % format(plan.total_pieces_to_cut, ","))
        if plan.spare:
            parts.append("incl. %g%% spare" % plan.spare)
        self.totals.config(text="  ·  ".join(parts))
        notes = []
        if plan.unassigned:
            notes.append("Not counted yet: %d unassigned color%s (%s)." % (
                len(plan.unassigned), "" if len(plan.unassigned) == 1 else "s",
                format(plan.unassigned_count, ",")))
        if plan.merged:   # one line, however many: details are in the tooltips
            n = len(plan.merged)
            notes.append("%d yarn%s used for more than one image color (highlighted; point at "
                         "it for the colors)." % (n, " is" if n == 1 else "s are"))
        self.notes.config(text="\n".join(notes))

    # ---------- merged-yarn tooltips ----------
    def _merged_row_tip(self, event):
        row = self.plan_tree.identify_row(event.y)
        if not (row and self._plan) or self.plan_tree.identify_region(event.x, event.y) \
                not in ("tree", "cell"):
            return None
        line = self._plan.lines[int(row)]
        if not line.merged:
            return None
        rows = []
        for hx in line.colors:
            n = self.project.entry(hx).count
            rows.append(([hx], "%s  \u00B7  %s knot%s" % (hx, format(n, ","),
                                                         "" if n == 1 else "s")))
        return "%s is used for %d image colors" % (line.label, len(line.colors)), rows

    def _merged_summary_tip(self, event):
        if not (self._plan and self._plan.merged):
            return None
        return ("Yarns used for more than one image color",
                [([l.hex] + l.colors, "%s:  %s" % (l.label, ", ".join(l.colors)))
                 for l in self._plan.merged])

    def edit_canvas(self):
        if not self.project:
            return
        r = CanvasDialog(self, pl.canvas_settings(self.project.settings)).result
        if r:
            values, as_default = r
            self.app.set_canvas(values, as_default)

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
        self.select_at(event.x, event.y, self.scale, self.offset)

    def select_at(self, px, py, scale, offset):
        """Select the image color under canvas point (px, py) of a view with that scale/offset."""
        if not self.project:
            return
        zoom, sub = scale
        x = (px - offset[0]) * sub // zoom
        y = (py - offset[1]) * sub // zoom
        img = self.project.image
        if 0 <= x < img.width and 0 <= y < img.height:
            hex_ = self.orig_hex[y * img.width + x]
            if hex_:
                self.tabs.select(0)
                self.tree.selection_set(hex_)  # fires on_select -> app
                self.tree.see(hex_)

    # ---------- image ----------
    def on_view(self):
        state = ["!disabled"] if self.view.get() == "preview" else ["disabled"]
        self.mark_cb.state(state)
        self.texture_cb.state(state)
        self.render_image()

    def toggle_texture(self):
        """T: yarn texture on or off. From the original it goes to the textured preview."""
        if not self.project:
            return
        if self.view.get() != "preview":
            self.view.set("preview")
            self.texture.set(True)
            self.on_view()
        else:
            self.texture.set(not self.texture.get())
            self.render_image()

    def toggle_view(self):
        if self.project:
            self.view.set("original" if self.view.get() == "preview" else "preview")
            self.on_view()

    def render_image(self):
        """Redraw the picture once the current event is handled: selecting a color asks for a
        redraw from several places, and they all share one."""
        if not self._render_job:
            self._render_job = self.after_idle(self._render_now)

    def _render_now(self):
        self._render_job = None
        c = self.canvas
        c.delete("all")
        if not self.project:
            return
        self.display = self.build_image(self.scale)
        dw, dh = self.display.width(), self.display.height()
        self.offset = ((IMG_W - dw) // 2, (IMG_H - dh) // 2)
        c.create_image(self.offset[0], self.offset[1], image=self.display, anchor="nw")
        if self.large:
            self.large.schedule()

    def open_large(self):
        if not self.project:
            return
        if self.large:
            self.large.deiconify()
            self.large.lift()
            self.large.focus_set()
            return
        self.large = LargeView(self)

    def build_image(self, scale):
        """PhotoImage of the project image at scale (zoom, subsample), as currently shown:
        original or yarn preview, grayscale, highlight and unassigned stripes."""
        p = self.project
        img = p.image
        w, h = img.width, img.height
        preview = self.view.get() == "preview"
        # assigned colors show their yarn, unassigned ones their suggested yarn
        swap = {e.hex: e.yarn["hex"] for e in p.colors if e.yarn} if preview else {}
        # the color being matched shows the yarn currently on screen (nothing is stored)
        live = self.app.live_preview() if preview else None
        if live:
            swap[live[0]] = live[1]
        unassigned = {e.hex for e in p.colors if not e.confirmed} \
            if preview and self.mark_unassigned.get() else set()
        sel = self.selected_hex() if self.highlight.get() else None
        gray = self.app.gray
        fade_to = 255   # the rest fades toward white, or toward dark gray around a light color
        if sel:
            sel_shown = swap.get(sel, sel)
            if gray:
                sel_shown = _gray(sel_shown)
            if lightness(*parse_hex(sel_shown)) >= LIGHT_SELECTION:
                fade_to = FADE_DARK

        shown, striped = {}, {}

        def look(orig):
            v = shown.get(orig)
            if v is None:
                v = swap.get(orig, orig)
                if gray:
                    v = _gray(v)
                if sel and orig != sel:
                    v = _fade(v, toward=fade_to)
                shown[orig] = v
                striped[orig] = _fade(v, 0.55) if orig in unassigned else v
            return v

        zoom, sub = scale
        dw = w * zoom if sub == 1 else -(-w // sub)
        dh = h * zoom if sub == 1 else -(-h // sub)
        textured = self._textures_for(dw, dh, live, sel, unassigned) \
            if preview and self.texture.get() and not gray else {}
        xs = [min(w - 1, dx * sub // zoom) for dx in range(dw)]
        photo = tk.PhotoImage(width=dw, height=dh)
        if not unassigned and (zoom == 1 or sub == 1):
            # One pixel per knot, then Tk zooms or shrinks it: much less for Tk to read than
            # every screen pixel. (The stripes run across screen pixels, so they can't.)
            orig_hex = self.orig_hex
            art = tk.PhotoImage(width=w, height=h)
            art.put(" ".join(
                "{" + " ".join(TRANSPARENT_SHOW if o is None else look(o)
                               for o in orig_hex[iy * w:(iy + 1) * w]) + "}"
                for iy in range(h)), to=(0, 0))
            if zoom > 1:
                photo.tk.call(photo.name, "copy", art.name, "-zoom", zoom)
            elif sub > 1:
                photo.tk.call(photo.name, "copy", art.name, "-subsample", sub)
            else:
                photo = art
        else:
            rows = []
            for dy in range(dh):
                base = min(h - 1, dy * sub // zoom) * w
                row = []
                for dx, ix in enumerate(xs):
                    orig = self.orig_hex[base + ix]
                    if orig is None:
                        row.append(TRANSPARENT_SHOW)
                        continue
                    look(orig)
                    if unassigned and orig in unassigned and ((dx + dy) // 3) % 2 == 0:
                        row.append(striped[orig])
                    else:
                        row.append(shown[orig])
                rows.append("{" + " ".join(row) + "}")
            photo.put(" ".join(rows), to=(0, 0))
        if textured:
            self._paint_textures(photo, textured, xs, w, h, scale, dw, dh)
        return photo

    # ---------- yarn texture ----------
    def _textures_for(self, dw, dh, live, sel, unassigned):
        """{image color: (texture, x offset, y offset)} for the colors whose yarn has a photo."""
        bank = {y.key: y for y in self.app.bank}
        out, used = {}, set()
        for e in self.project.colors:
            if (sel and e.hex != sel) or e.hex in unassigned:
                continue
            if live and live[0] == e.hex:
                y = self.app.yarns[self.app.index]
            elif e.yarn:
                y = bank.get(pal.yarn_key(e.yarn["name"], e.yarn.get("brand", "")))
            else:
                y = None
            path = pal.photo_file(self.app.palette_path, y) if y else None
            tex = self._texture(path, dw, dh) if path else None
            if tex:
                out[e.hex] = tex
                used.add(path)
        self._trim_textures(used, (dw, dh))
        return out

    def _texture(self, path, w, h):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        cached = self._photos.get(path)
        if not cached or cached[0] != mtime:
            try:
                cached = self._photos[path] = (mtime, photos.load(path, master=self))
            except ValueError:
                return None
        self._photos.move_to_end(path)
        key = (path, mtime, w, h)
        tex = self._textures.get(key)
        if tex is None:
            tex = self._textures[key] = photos.cover_texture(cached[1], w, h)
        return tex

    def _trim_textures(self, used, size):
        """Keep the photos this picture uses plus the SPARE_PHOTOS used most recently, and
        textures only for those photos at the two sizes drawn last (sidebar and larger view)."""
        if size in self._texture_sizes:
            self._texture_sizes.remove(size)
        self._texture_sizes = (self._texture_sizes + [size])[-2:]
        spare = len(self._photos) - len(used) - SPARE_PHOTOS
        for path in list(self._photos):          # least recently used first
            if spare <= 0:
                break
            if path not in used:
                del self._photos[path]
                spare -= 1
        for key in list(self._textures):
            path, mtime, w, h = key
            if (w, h) not in self._texture_sizes or path not in self._photos \
                    or self._photos[path][0] != mtime:
                del self._textures[key]

    def _paint_textures(self, photo, textured, xs, w, h, scale, dw, dh):
        """Copy each textured color's photo into its knots: one rectangle per run of the same
        color along a row of art pixels, painted into a strip of a few rows that then goes into
        the picture in one copy (much faster than many copies straight into a big picture)."""
        zoom, sub = scale
        call = photo.tk.call
        groups = []                      # (screen y0, y1, image row) for each row of knots
        y0 = 0
        while y0 < dh:
            iy = min(h - 1, y0 * sub // zoom)
            y1 = y0 + 1
            while y1 < dh and min(h - 1, y1 * sub // zoom) == iy:
                y1 += 1
            groups.append((y0, y1, iy))
            y0 = y1
        band = tk.PhotoImage(master=self, width=dw,
                             height=min(dh, TEXTURE_BAND + max(g[1] - g[0] for g in groups)))
        start = 0
        while start < len(groups):
            end = start + 1
            while end < len(groups) and groups[end][1] - groups[start][0] <= TEXTURE_BAND:
                end += 1
            top, bottom = groups[start][0], groups[end - 1][1]
            runs = []
            for y0, y1, iy in groups[start:end]:
                base, x0 = iy * w, 0
                while x0 < dw:
                    orig = self.orig_hex[base + xs[x0]]
                    x1 = x0 + 1
                    while x1 < dw and self.orig_hex[base + xs[x1]] == orig:
                        x1 += 1
                    tex = textured.get(orig)
                    if tex:
                        runs.append((tex, x0, x1, y0, y1))
                    x0 = x1
            if runs:
                call(band.name, "copy", photo.name, "-from", 0, top, dw, bottom, "-to", 0, 0)
                for (img, ox, oy), x0, x1, y0, y1 in runs:
                    call(band.name, "copy", img.name, "-from", x0 + ox, y0 + oy, x1 + ox,
                         y1 + oy, "-to", x0, y0 - top)
                call(photo.name, "copy", band.name, "-from", 0, 0, dw, bottom - top,
                     "-to", 0, top)
            start = end


class LargeView(tk.Toplevel):
    """The project image in its own resizable window, as large as fits (whole-number zoom).
    Not modal: it follows the sidebar (view, highlight, selected color, live preview) and a
    click selects a color there too."""

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.configure(bg=BG)
        self.minsize(240, 180)
        p = panel.project.image
        if panel._large_geometry:
            self.geometry(panel._large_geometry)
        elif not panel.app.restore_geometry(self, "larger_view"):
            # start at about 8 screen pixels per art pixel, within most of the screen
            z = max(1, min(8, (self.winfo_screenwidth() * 3 // 4) // p.width,
                           (self.winfo_screenheight() * 3 // 4) // p.height))
            self.geometry("%dx%d" % (max(480, p.width * z + 40), max(320, p.height * z + 40)))
        self.canvas = tk.Canvas(self, bg="#D8D8D8", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.photo, self.scale, self.offset, self._job, self._size = None, (1, 1), (0, 0), None, None
        self.canvas.bind("<Configure>", lambda e: self.schedule())
        self.canvas.bind("<Button-1>", lambda e: panel.select_at(e.x, e.y, self.scale, self.offset))
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.schedule()

    def schedule(self):
        """Redraw soon; several changes in a row (a resize drag, stepping yarns) draw once."""
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(40, self.redraw)

    def redraw(self):
        self._job = None
        p = self.panel.project
        if not p:
            return
        self.title("%s \u00b7 larger view" % p.name)
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 2 or ch < 2:
            return
        img = p.image
        self.scale = fit_scale(img.width, img.height, cw - 16, ch - 16)
        self.photo = self.panel.build_image(self.scale)
        dw, dh = self.photo.width(), self.photo.height()
        self.offset = ((cw - dw) // 2, (ch - dh) // 2)
        self.canvas.delete("all")
        self.canvas.create_image(self.offset[0], self.offset[1], image=self.photo, anchor="nw")

    def destroy(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        if self.panel.large is self:
            self.panel.large = None
            try:
                self.panel._large_geometry = self.geometry()
                if self.state() == "normal":
                    self.panel.app.keep_geometry("larger_view", self.geometry())
            except tk.TclError:
                pass
        super().destroy()


class CanvasDialog(tk.Toplevel):
    """Canvas mesh and border allowances for a project. result = (values, as_default) or None."""

    FIELDS = (("holes_per_inch", "Holes per inch", "mesh count of the canvas"),
              ("border_side", "Border, each side", "holes folded under on the left and right"),
              ("border_top", "Border, top", "holes folded over at the top (e.g. hanging loop)"),
              ("border_bottom", "Border, bottom", "holes folded under + empty rows at the bottom"))

    def __init__(self, parent, values):
        super().__init__(parent)
        self.result = None
        self.title("Canvas")
        self.configure(bg=BG, padx=16, pady=14)
        self.resizable(False, False)
        self.transient(parent)
        self.vars, self.hints, entries = {}, {}, []
        for row, (key, text, hint) in enumerate(self.FIELDS):
            tk.Label(self, text=text, font=UI_FONT, bg=BG).grid(row=row, column=0, sticky="w",
                                                                pady=3)
            v = tk.StringVar(value="%g" % values[key])
            entries.append(ttk.Entry(self, textvariable=v, width=7))
            entries[-1].grid(row=row, column=1, sticky="w", padx=8)
            # the hint doubles as the error line: it turns red with what's wrong
            self.hints[key] = tk.Label(self, text=hint, font=("Segoe UI", 9), bg=BG, fg="#777")
            self.hints[key].grid(row=row, column=2, sticky="w")
            v.trace_add("write", lambda *_: self.update_view())
            self.vars[key] = v
        self.default = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Also use these for new projects", variable=self.default).grid(
            row=len(self.FIELDS), column=0, columnspan=3, sticky="w", pady=(10, 0))
        btns = tk.Frame(self, bg=BG)
        btns.grid(row=len(self.FIELDS) + 2, column=0, columnspan=3, sticky="e", pady=(8, 0))
        self.ok = ttk.Button(btns, text="Save", command=self.accept)
        self.ok.pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda e: self.accept())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_view()
        self.update_idletasks()
        x = parent.winfo_rootx() + 40
        y = parent.winfo_rooty() + 200
        self.geometry("+%d+%d" % (x, y))
        entries[0].focus_set()          # ready to type, like the other dialogs
        entries[0].select_range(0, "end")
        self.grab_set()
        self.wait_window()

    def check(self):
        """(values or None, {field: what's wrong})."""
        out, errs = {}, {}
        for key, text, _ in self.FIELDS:
            try:
                v = float(self.vars[key].get())
            except ValueError:
                errs[key] = "Must be a number"
                continue
            if key == "holes_per_inch":
                if v <= 0:
                    errs[key] = "Must be more than 0"
                out[key] = v
            else:
                if v < 0 or v != int(v):
                    errs[key] = "Must be a whole number, 0 or more"
                out[key] = int(v) if v == int(v) else v
        return (None if errs else out), errs

    def update_view(self):
        _, errs = self.check()
        for key, _, hint in self.FIELDS:
            e = errs.get(key)
            self.hints[key].config(text=e or hint, fg="#C62828" if e else "#777")
        self.ok.state(["disabled"] if errs else ["!disabled"])

    def accept(self):
        values, err = self.check()
        if not err:
            self.result = (values, self.default.get())
            self.destroy()


def _scrolled(body, tree):
    """Grid a tree with vertical and horizontal scrollbars (long yarn names can scroll)."""
    ys = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
    xs = ttk.Scrollbar(body, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
    tree.grid(row=0, column=0, sticky="nsew")
    ys.grid(row=0, column=1, sticky="ns")
    xs.grid(row=1, column=0, sticky="ew")
    body.rowconfigure(0, weight=1)
    body.columnconfigure(0, weight=1)


TREE_BORDER = 4   # px the Treeview's frame takes from its width


def _fit_columns(tree, spec):
    """Size columns to their widest cell or heading. spec: {col: (padding px, font or None[,
    texts to always leave room for])}; the tree column (#0) padding should include the indent
    and row image."""
    base = tkfont.nametofont("TkDefaultFont")
    head = tkfont.nametofont("TkHeadingFont")
    items = tree.get_children()
    for col, (pad, font, *room) in spec.items():
        f = font or base
        texts = [tree.item(i, "text") if col == "#0" else str(tree.set(i, col)) for i in items]
        texts += room[0] if room else []
        widest = max([f.measure(t) + pad for t in texts] +
                     [head.measure(tree.heading(col, "text").rstrip(" \u25b2\u25bc") + " \u25bc") + 14])
        tree.column(col, width=widest, minwidth=widest)
