"""Carry over assignments: give a project the yarns earlier projects used for the same hex."""
import os
import tkinter as tk
from tkinter import ttk

from .palette import label as yarn_label
from .widgets import (BG, SMALL_FONT, UI_FONT, ProjectList, TreeSort, names, swatch_image,
                      value_tip, vscroll)

FROM = "From "   # "Yarn for selected" choice that takes every selected color's yarn from a project


def _names(items, most=4):
    """'a', 'a and b', 'a, b and c', 'a, b, c, d and 2 more'."""
    items = list(items)
    if len(items) > most:
        return "%s and %d more" % (", ".join(items[:most]), len(items) - most)
    return " and ".join(filter(None, [", ".join(items[:-1]), items[-1] if items else ""]))


def _thumbnail(img, box_w=64, box_h=40):
    """A rug's image at a whole-number scale (so pixel art stays crisp), centered in a fixed
    box_w x box_h image so every row's name starts at the same place. Transparent pixels and
    the rest of the box stay transparent."""
    w, h = img.width, img.height
    photo = tk.PhotoImage(width=w, height=h)
    rows = []
    for y in range(h):
        rows.append("{" + " ".join("#%02x%02x%02x" % (r, g, b)
                                   for r, g, b, _ in img.pixels[y * w:(y + 1) * w]) + "}")
    photo.put(" ".join(rows))
    for i, (_, _, _, a) in enumerate(img.pixels):
        if a < 128:
            photo.transparency_set(i % w, i // w, True)
    zoom = min(box_w // w, box_h // h)
    if zoom > 1:
        photo = photo.zoom(zoom)
    elif zoom < 1:
        photo = photo.subsample(max(-(-w // box_w), -(-h // box_h)))
    box = tk.PhotoImage(width=box_w, height=box_h)
    box.tk.call(box, "copy", photo, "-to", (box_w - photo.width()) // 2,
                (box_h - photo.height()) // 2)
    return box


def _option_label(option):
    name, y = option
    return "%s  –  %s" % (yarn_label(y["name"], y.get("brand")), name)


class CarryDialog(tk.Toplevel):
    """result: [(hex, yarn snapshot, source name)] to carry over, or None (skipped/cancelled).

    One table lists every color that would be carried over. A color that earlier projects gave
    different yarns (a conflict) starts with the newest project's yarn; select rows and pick
    another under "Yarn for selected". Yarns that aren't in the active palette are kept, or
    left to be matched, with one checkbox.

    app gives yarn_in_palette(); initial: project paths to start with."""

    def __init__(self, parent, app, project, initial=(), skip_text="Cancel"):
        super().__init__(parent)
        self.app, self.project = app, project
        self.result = None
        self.final = []
        self.options = {}          # hex -> [(source name, yarn snapshot)], newest first
        self.pick = {}             # hex -> index into its options
        self.images = {}
        self.title("Carry over assignments")
        self.configure(bg=BG, padx=16, pady=14)
        self.minsize(600, 440)
        self.geometry("720x600")
        self.transient(parent)

        tk.Label(self, bg=BG, font=UI_FONT, justify="left", anchor="w",
                 text="Colors with exactly the same hex as an assigned color in these projects get "
                      "the same yarn. Other colors are matched as usual.",
                 wraplength=680).pack(fill="x")
        # earlier projects, newest first (the newest one's yarn is picked in a conflict)
        src = self.projects = ProjectList(
            self, [("assigned", "Assigned", 80), ("carried", "Carried over", 100)],
            lambda p: (sum(1 for c in p.colors if c.confirmed), 0), self.rebuild,
            "Carry over", "Carry over from which projects?",
            initialdir=os.path.dirname(project.path or "") or None, exclude=project.path,
            exclude_note="That's the project itself.")
        src.pack(fill="x", pady=(10, 0))
        self.sources = src.sources
        self.project_tree = src.tree

        # bottom up, so the table takes whatever height is left
        self.btns = tk.Frame(self, bg=BG)
        self.btns.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Button(self.btns, text=skip_text, command=self.destroy).pack(side="right")
        self.ok = ttk.Button(self.btns, text="Carry over", command=self.accept)
        self.ok.pack(side="right", padx=4)
        self.ok.lower()   # Tab reaches Carry over before Skip/Cancel, as they read
        # one line each (width=1: long text is cut rather than widening the window)
        self.details = tk.Label(self, bg=BG, font=SMALL_FONT, fg="#555", anchor="w", width=1)
        self.details.pack(side="bottom", fill="x")
        self.summary = tk.Label(self, bg=BG, font=("Segoe UI", 10, "bold"), anchor="w",
                                width=1)
        self.summary.pack(side="bottom", fill="x", pady=(8, 0))
        self.keep_missing = tk.BooleanVar(value=True)
        keep = ttk.Checkbutton(self, text="Keep yarns that aren't in the active palette "
                                          "(otherwise those colors are matched as usual)",
                               variable=self.keep_missing, command=self.update_view)
        keep.pack(side="bottom", anchor="w", pady=(6, 0))
        ctl = tk.Frame(self, bg=BG)
        ctl.pack(side="bottom", fill="x", pady=(8, 0))
        tk.Label(ctl, text="Yarn for selected", font=UI_FONT, bg=BG).pack(side="left")
        self.choice_var = tk.StringVar()
        self.choice_box = ttk.Combobox(ctl, textvariable=self.choice_var, state="readonly",
                                       width=52)
        self.choice_box.pack(side="left", padx=6)
        self.choice_box.bind("<<ComboboxSelected>>", lambda e: self.set_choice())
        value_tip(self.choice_box)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, pady=(10, 0))
        self.tree = ttk.Treeview(body, columns=("yarn", "from", "note"), selectmode="extended")
        for col, text, width, stretch in (("#0", "Color", 130, False), ("yarn", "Yarn", 230, True),
                                          ("from", "From", 120, False),
                                          ("note", "Note", 170, False)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=width, minwidth=60, stretch=stretch)
        self.tree.tag_configure("attention", background="#FFF4CC")
        self.tree.tag_configure("dropped", foreground="#999999")
        vscroll(body, self.tree)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        self.tree.bind("<Control-a>", lambda e: (self.tree.selection_set(self.tree.get_children()),
                                                 "break")[1])
        order = {c.hex: i for i, c in enumerate(project.colors)}   # lightest first
        yarn = lambda i: self.options[i][self.pick[i]][1]
        self.sort = TreeSort(self.tree, {
            "#0": (lambda i: project.entry(i).L, False),
            "yarn": (lambda i: yarn_label(yarn(i)["name"], yarn(i).get("brand")).lower(), False),
            "from": (lambda i: self.options[i][self.pick[i]][0].lower(), False),
            "note": (lambda i: (len(self.options[i]) > 1, not self.app.yarn_in_palette(yarn(i))),
                     True),
        }, default=lambda i: order[i])
        for w in (src, body, ctl, keep, self.btns):   # Tab goes top to bottom, as laid out
            w.lift()

        self.bind("<Return>", lambda e: self.accept())
        self.bind("<Escape>", lambda e: self.destroy())
        for path in initial:
            src.add_path(path, quiet=True)
        src.refresh()
        self.rebuild()
        self.update_idletasks()
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 60, parent.winfo_rooty() + 60))
        self.grab_set()
        self.tree.focus_set()
        self.wait_window()

    # ---------- table ----------
    def rebuild(self):
        """Sources changed: recompute the options and refill the table (choices made for a
        color are kept while that yarn is still offered)."""
        self.sources = self.projects.sources
        old = {h: _option_label(self.options[h][i]) for h, i in self.pick.items()
               if h in self.options}
        self.options = self.project.carry_options([(n, s) for _, n, s, _ in self.sources])
        self.pick = {}
        for hex_, opts in self.options.items():
            labels = [_option_label(o) for o in opts]
            self.pick[hex_] = labels.index(old[hex_]) if old.get(hex_) in labels else 0
        keep = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for c in self.project.colors:
            if c.hex in self.options:
                self.tree.insert("", "end", iid=c.hex, text="  " + c.hex)
        self.fill_rows()
        self.sort.apply()
        sel = [h for h in keep if self.tree.exists(h)]
        if sel:
            self.tree.selection_set(sel)
        self.on_select()
        self.update_view()

    def fill_rows(self):
        keep = self.keep_missing.get()
        for hex_, opts in self.options.items():
            name, y = opts[self.pick[hex_]]
            notes = []
            if len(opts) > 1:
                notes.append("choice of %d" % len(opts))
            missing = not self.app.yarn_in_palette(y)
            if missing:
                notes.append("not in palette" if keep else "to be matched")
            key = (hex_, y["hex"])
            if key not in self.images:
                self.images[key] = swatch_image([hex_, y["hex"]], w=40, slots=2)
            tags = []
            if notes:
                tags.append("attention")
            if missing and not keep:
                tags.append("dropped")
            self.tree.item(hex_, image=self.images[key], tags=tags,
                           values=(yarn_label(y["name"], y.get("brand")), name,
                                   ", ".join(notes)))

    def selected(self):
        return [h for h in self.tree.selection() if h in self.options]

    def on_select(self):
        """Fill "Yarn for selected": one color lists its yarns; several list the projects."""
        sel = self.selected()
        if len(sel) == 1:
            opts = self.options[sel[0]]
            self.choice_box.config(values=[_option_label(o) for o in opts])
            self.choice_var.set(_option_label(opts[self.pick[sel[0]]]))
            many = len(opts) > 1
        elif sel:
            offered = [n for _, n, _, _ in self.sources
                       if any(n == o[0] for h in sel for o in self.options[h])]
            self.choice_box.config(values=[FROM + n for n in offered])
            picked = {self.options[h][self.pick[h]][0] for h in sel}
            self.choice_var.set(FROM + picked.pop() if len(picked) == 1 else "")
            many = any(len(self.options[h]) > 1 for h in sel)
        else:
            self.choice_box.config(values=[])
            self.choice_var.set("")
            many = False
        self.choice_box.state(["!disabled"] if many else ["disabled"])

    def set_choice(self):
        value, sel = self.choice_var.get(), self.selected()
        for hex_ in sel:
            opts = self.options[hex_]
            if len(sel) == 1:
                labels = [_option_label(o) for o in opts]
                if value in labels:
                    self.pick[hex_] = labels.index(value)
            elif value.startswith(FROM):
                name = value[len(FROM):]
                i = next((k for k, o in enumerate(opts) if o[0] == name), None)
                if i is not None:
                    self.pick[hex_] = i
        self.fill_rows()
        self.on_select()
        self.update_view()

    # ---------- summary ----------
    def chosen(self):
        """[(hex, yarn, source name)] after the choices, before the palette check."""
        out = []
        for hex_, opts in self.options.items():
            name, y = opts[self.pick[hex_]]
            out.append((hex_, y, name))
        return out

    def update_view(self):
        self.fill_rows()
        p = self.project
        if not self.sources:
            self.summary.config(text="Add one or more earlier projects.")
            self.details.config(text="")
            self.final = []
            self.ok.state(["disabled"])
            return
        picks = self.chosen()
        missing = [h for h, y, _ in picks if not self.app.yarn_in_palette(y)]
        if missing and not self.keep_missing.get():
            picks = [t for t in picks if t[0] not in set(missing)]
        self.final = picks
        for path, name, _, _ in self.sources:   # how many colors each project gives
            self.project_tree.set(path, "carried", sum(1 for t in picks if t[2] == name))
        total = len(p.colors)
        already = sum(1 for c in p.colors if c.confirmed)
        new = total - already - len(self.options)
        self.summary.config(text="%d of %d colors carried over from %s, %d new." % (
            len(picks), total, names(n for _, n, _, _ in self.sources), new))
        parts = []
        if already:
            parts.append("%d already assigned here, left as they are" % already)
        conflicts = sum(1 for o in self.options.values() if len(o) > 1)
        if conflicts:
            parts.append("%d with a choice of yarns" % conflicts)
        if missing:
            parts.append("%d with a yarn that isn't in the active palette%s" % (
                len(missing), "" if self.keep_missing.get() else " (left to be matched)"))
        self.details.config(text="; ".join(parts) + ("." if parts else ""))
        self.ok.state(["!disabled"] if picks else ["disabled"])

    def accept(self):
        if self.sources and self.final:
            self.result = self.final
            self.destroy()
