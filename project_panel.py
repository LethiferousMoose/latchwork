"""Project sidebar: the image (original or yarn preview), its colors and assignments, and the plan."""
import math
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import plan as pl
from colormath import gray_for_lightness, lightness, parse_hex, to_hex

BG = "#ECECEC"
UI_FONT = ("Segoe UI", 10)
IMG_W, IMG_H = 400, 250
TRANSPARENT_SHOW = "#F7F7F7"


def short_path(path, limit=62):
    """Keep the end of a long path (the file name matters most)."""
    return path if len(path) <= limit else "…" + path[-(limit - 1):]


def _fade(hex_, amount=0.78):
    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return to_hex(*(c + (255 - c) * amount for c in (r, g, b)))


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
        self._quiet = False
        italic = tkfont.nametofont("TkDefaultFont").copy()
        italic.configure(slant="italic")
        self._italic = italic

        # ----- shown when no project is open -----
        self.welcome = tk.Frame(self, bg=BG, width=IMG_W + 30)
        tk.Label(self.welcome, text="No project open", font=("Segoe UI", 16, "bold"),
                 bg=BG).pack(anchor="w")
        tk.Label(self.welcome, bg=BG, fg="#555", justify="left", wraplength=IMG_W,
                 font=UI_FONT, text="Start a rug from a pixel-art image (PNG or GIF), or open a "
                                    "saved .latchwork project. You can also match single colors "
                                    "on the right without a project.").pack(anchor="w", pady=(4, 12))
        ttk.Button(self.welcome, text="New project from image...  (Ctrl+N)",
                   command=app.new_project).pack(anchor="w", ipadx=6, pady=2)
        ttk.Button(self.welcome, text="Open project...  (Ctrl+O)",
                   command=app.open_project).pack(anchor="w", ipadx=6, pady=2)

        # ----- shown when a project is open -----
        self.content = tk.Frame(self, bg=BG)
        c = self.content
        self.title = tk.Label(c, font=("Segoe UI", 16, "bold"), bg=BG, anchor="w")
        self.title.pack(fill="x")
        self.subtitle = tk.Label(c, font=("Segoe UI", 9), bg=BG, fg="#555", anchor="w",
                                 justify="left")
        self.subtitle.pack(fill="x")

        views = tk.Frame(c, bg=BG)
        views.pack(fill="x", pady=(8, 4))
        self.view = tk.StringVar(value="original")
        for value, text in (("original", "Original"), ("preview", "Yarn preview")):
            ttk.Radiobutton(views, text=text, value=value, variable=self.view, style="Toolbutton",
                            command=self.on_view).pack(side="left", ipadx=8)
        tk.Label(views, text="  P switches", font=("Segoe UI", 8), bg=BG, fg="#888").pack(
            side="left")
        self.mark_unassigned = tk.BooleanVar(value=False)
        self.mark_cb = ttk.Checkbutton(views, text="Mark unassigned", variable=self.mark_unassigned,
                                       command=self.render_image)
        self.mark_cb.pack(side="right")

        self.canvas = tk.Canvas(c, width=IMG_W, height=IMG_H, bg="#D8D8D8",
                                highlightthickness=1, highlightbackground="#AAA",
                                cursor="crosshair")
        self.canvas.pack(pady=(2, 2))
        self.canvas.bind("<Button-1>", self.on_image_click)
        self.highlight = tk.BooleanVar(value=True)
        ttk.Checkbutton(c, text="Highlight the selected color", variable=self.highlight,
                        command=self.render_image).pack(anchor="w")

        self.tabs = ttk.Notebook(c)
        self.tabs.pack(fill="both", expand=True, pady=(8, 0))
        self._build_colors_tab()
        self._build_plan_tab()
        self.show_welcome()

    # ---------- tabs ----------
    def _build_colors_tab(self):
        tab = tk.Frame(self.tabs, bg=BG, padx=4, pady=6)
        self.tabs.add(tab, text="  Colors  ")
        body = tk.Frame(tab, bg=BG)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("count", "yarn", "state"), selectmode="browse",
                                 height=8)
        for col, text, width, anchor in (("#0", "Color", 130, "w"), ("count", "Count", 55, "e"),
                                         ("yarn", "Yarn", 145, "w"), ("state", "", 70, "w")):
            self.tree.heading(col, text=text, anchor=anchor if col != "#0" else "w")
            self.tree.column(col, width=width, minwidth=40, anchor=anchor, stretch=(col == "yarn"))
        self.tree.tag_configure("suggested", foreground="#7A7A7A", font=self._italic)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())

        self.assigned_info = tk.Label(tab, font=UI_FONT, bg=BG, anchor="w", justify="left",
                                      wraplength=IMG_W)
        self.assigned_info.pack(fill="x", pady=(6, 0))
        btns = tk.Frame(tab, bg=BG)
        btns.pack(fill="x", pady=(6, 0))
        self.assign_btn = ttk.Button(btns, text="Assign current yarn (A)", command=self.app.assign)
        self.assign_btn.pack(side="left")
        self.unassign_btn = ttk.Button(btns, text="Back to suggestion", command=self.app.unassign)
        self.unassign_btn.pack(side="left", padx=6)
        self.progress = tk.Label(btns, font=("Segoe UI", 10, "bold"), bg=BG)
        self.progress.pack(side="right")

    def _build_plan_tab(self):
        tab = tk.Frame(self.tabs, bg=BG, padx=4, pady=6)
        self.tabs.add(tab, text="  Plan  ")
        sizes = tk.Frame(tab, bg=BG)
        sizes.pack(fill="x")
        self.size_vals = {}
        for row, key in enumerate(("Finished size", "Canvas to cut")):
            tk.Label(sizes, text=key, font=UI_FONT, bg=BG, fg="#555").grid(row=row, column=0,
                                                                          sticky="w")
            v = tk.Label(sizes, font=("Segoe UI", 10, "bold"), bg=BG)
            v.grid(row=row, column=1, sticky="w", padx=10)
            self.size_vals[key] = v
        tk.Label(sizes, text="3.75 holes/inch · canvas adds 3 per side, 8 at the top, "
                             "3 + 1 empty row at the bottom", font=("Segoe UI", 8), bg=BG,
                 fg="#888", wraplength=IMG_W, justify="left").grid(row=2, column=0, columnspan=2,
                                                                   sticky="w")
        spare = tk.Frame(sizes, bg=BG)
        spare.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        tk.Label(spare, text="Spare", font=UI_FONT, bg=BG).pack(side="left")
        self.spare_var = tk.StringVar(value="0")
        sp = ttk.Spinbox(spare, from_=0, to=100, increment=5, width=4, textvariable=self.spare_var,
                         command=self.on_spare)
        sp.pack(side="left", padx=4)
        sp.bind("<Return>", lambda e: self.on_spare())
        sp.bind("<FocusOut>", lambda e: self.on_spare())
        tk.Label(spare, text="%   added to every count before bags and pieces",
                 font=("Segoe UI", 9), bg=BG, fg="#666").pack(side="left")

        body = tk.Frame(tab, bg=BG)
        body.pack(fill="both", expand=True, pady=(8, 0))
        self.plan_tree = ttk.Treeview(body, columns=("count", "need", "colors"), selectmode="none",
                                      height=6)
        for col, text, width, anchor in (("#0", "Yarn (assigned)", 190, "w"),
                                         ("count", "Count", 55, "e"), ("need", "Need", 95, "e"),
                                         ("colors", "Colors", 55, "e")):
            self.plan_tree.heading(col, text=text, anchor="w" if col == "#0" else anchor)
            self.plan_tree.column(col, width=width, minwidth=40, anchor=anchor,
                                  stretch=(col == "#0"))
        self.plan_tree.tag_configure("merged", background="#FFF4CC")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.plan_tree.yview)
        self.plan_tree.configure(yscrollcommand=sb.set)
        self.plan_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")

        self.totals = tk.Label(tab, font=("Segoe UI", 10, "bold"), bg=BG, anchor="w",
                               justify="left")
        self.totals.pack(fill="x", pady=(6, 0))
        self.notes = tk.Label(tab, font=("Segoe UI", 9), bg=BG, fg="#555", anchor="w",
                              justify="left", wraplength=IMG_W)
        self.notes.pack(fill="x")
        btns = tk.Frame(tab, bg=BG)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Export yarn list...", command=self.app.export_yarn_list).pack(
            side="left")
        ttk.Button(btns, text="Save preview image...", command=self.app.save_preview).pack(
            side="left", padx=6)

    # ---------- project ----------
    def show_welcome(self):
        self.project = None
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
        if w <= IMG_W and h <= IMG_H:
            self.scale = (max(1, min(IMG_W // w, IMG_H // h)), 1)
        else:
            self.scale = (1, math.ceil(max(w / IMG_W, h / IMG_H)))
        self.title.config(text=project.name)
        sub = "%d × %d px  ·  %d colors  ·  %s total" % (
            w, h, len(project.colors), format(project.knots, ","))
        if project.transparent:
            sub += "  ·  %s transparent (skipped)" % format(project.transparent, ",")
        self.subtitle.config(text=sub + "\n" + short_path(project.path))
        self.spare_var.set("%g" % float(project.settings.get("spare_percent", 0) or 0))
        self.refresh_rows()
        self.refresh_plan()
        self.on_view()

    def refresh_rows(self):
        keep = self.selected_hex()
        self._quiet = True
        self.tree.delete(*self.tree.get_children())
        for c in self.project.colors:
            self.tree.insert("", "end", iid=c.hex)
            self.update_row(c.hex, plan=False)
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
        self._quiet = False
        self.update_footer()
        self.refresh_plan()

    def update_row(self, hex_, plan=True):
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
        if plan:
            self.refresh_plan()
            self.render_image()

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
        plan = pl.Plan(self.project)
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
            self.plan_tree.insert("", "end", iid=str(i), text="  %s" % l.name, image=img,
                                  values=(format(l.count, ","), l.need(plan.spare)[2],
                                          len(l.colors)),
                                  tags=("merged",) if l.merged else ())
        parts = ["%s assigned" % format(plan.assigned_count, ",")]
        if plan.total_bags:
            parts.append("%d Hershner's bag%s" % (plan.total_bags,
                                                  "" if plan.total_bags == 1 else "s"))
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
        for l in plan.merged:
            notes.append("Merged: %s is used for %d image colors (%s)." % (
                l.name, len(l.colors), ", ".join(l.colors)))
        self.notes.config(text="\n".join(notes))

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
            hex_ = self.orig_hex[y * img.width + x]
            if hex_:
                self.tabs.select(0)
                self.tree.selection_set(hex_)  # fires on_select -> app
                self.tree.see(hex_)

    # ---------- image ----------
    def on_view(self):
        self.mark_cb.state(["!disabled"] if self.view.get() == "preview" else ["disabled"])
        self.render_image()

    def toggle_view(self):
        if self.project:
            self.view.set("original" if self.view.get() == "preview" else "preview")
            self.on_view()

    def render_image(self):
        c = self.canvas
        c.delete("all")
        if not self.project:
            return
        p = self.project
        img = p.image
        w, h = img.width, img.height
        preview = self.view.get() == "preview"
        swap = {e.hex: e.yarn["hex"] for e in p.colors if e.confirmed and e.yarn} if preview else {}
        unassigned = {e.hex for e in p.colors if not e.confirmed} \
            if preview and self.mark_unassigned.get() else set()
        sel = self.selected_hex() if self.highlight.get() else None
        gray = self.app.gray

        shown, striped = {}, {}

        def look(orig):
            v = shown.get(orig)
            if v is None:
                v = swap.get(orig, orig)
                if gray:
                    v = _gray(v)
                if sel and orig != sel:
                    v = _fade(v)
                shown[orig] = v
                striped[orig] = _fade(v, 0.55) if orig in unassigned else v
            return v

        zoom, sub = self.scale
        dw = w * zoom if sub == 1 else -(-w // sub)
        dh = h * zoom if sub == 1 else -(-h // sub)
        xs = [min(w - 1, dx * sub // zoom) for dx in range(dw)]
        rows = []
        for dy in range(dh):
            iy = min(h - 1, dy * sub // zoom)
            base = iy * w
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
        self.display = tk.PhotoImage(width=dw, height=dh)
        self.display.put(" ".join(rows), to=(0, 0))
        self.offset = ((IMG_W - dw) // 2, (IMG_H - dh) // 2)
        c.create_image(self.offset[0], self.offset[1], image=self.display, anchor="nw")
