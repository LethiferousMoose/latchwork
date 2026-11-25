"""Palette manager window: yarns (add, edit, brand, retire, delete, photo), brands, import and
export."""
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from . import palette as pal
from . import photos
from .colormath import SWATCH_L_OFFSET, SWATCH_L_SCALE, lightness, parse_hex, to_hex
from .widgets import (ColorPanel, FieldNote, Tooltip, TreeSort, free_name, required_label,
                      required_legend)

BG = "#ECECEC"
UI_FONT = ("Segoe UI", 10)
HINT_FONT = ("Segoe UI", 9)


def swatch_image(colors, w=30, h=16, slots=None):
    """PhotoImage of colors side by side with a thin border. With slots > len(colors), the
    unused slots stay transparent so rows with one or two swatches line up."""
    slots = slots or len(colors)
    img = tk.PhotoImage(width=w, height=h)
    seg = w / slots
    for i, c in enumerate(colors):
        x0, x1 = int(i * seg), int((i + 1) * seg)
        img.put("#888888", to=(x0, 0, x1, h))
        img.put(c, to=(x0 + 1, 1, x1 - 1, h - 1))
    return img


def _round_rect(c, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)


def center_on(win, parent):
    win.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_height()) // 3
    win.geometry("+%d+%d" % (max(x, 0), max(y, 0)))


def iid(yarn):
    """Tree row id for a yarn (name + brand, so two brands' 'White' are different rows)."""
    return "\x1f".join(yarn.key)


def saved_sort(app, key, sort):
    """A table's sort from last time ([column, descending]), or None for its default order."""
    if not app.remember:
        return None
    from .app import read_settings
    state = read_settings().get(key)
    ok = isinstance(state, list) and len(state) == 2 and state[0] in sort.keys
    return [state[0], bool(state[1])] if ok else None


def keep_sort(app, key, state):
    """A heading was clicked: remember the order for next time (like the window size)."""
    if app.remember:
        from .app import read_settings, write_settings
        settings = read_settings()
        settings[key] = state
        write_settings(settings)


NO_BRAND = "(no brand)"   # the yarn dialog's choice for a yarn without one


def duplicates(yarns):
    seen, dup = set(), []
    for y in yarns:
        if y.key in seen:
            dup.append(y.label)
        seen.add(y.key)
    return dup


class PaletteWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.images = {}
        self.title("Latchwork - Yarn palette")
        self.configure(bg=BG)
        self.minsize(760, 480)
        if not app.restore_geometry(self, "palette_manager"):
            self.geometry("880x620")

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(head, text="Editing:", font=("Segoe UI", 11), bg=BG, fg="#555").pack(side="left")
        self.file_label = tk.Label(head, font=("Segoe UI", 11, "bold"), bg=BG)
        self.file_label.pack(side="left", padx=(4, 8))

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=12, pady=(8, 6))
        tk.Label(top, text="Find", font=UI_FONT, bg=BG).pack(side="left")
        self.find_var = tk.StringVar()
        self.find_var.trace_add("write", lambda *_: self.refresh())
        ttk.Entry(top, textvariable=self.find_var, width=24).pack(side="left", padx=6)
        tk.Label(top, text="name, brand or hex", font=HINT_FONT, bg=BG, fg="#888").pack(side="left")
        self.show_retired = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Show retired", variable=self.show_retired,
                        command=self.refresh).pack(side="left", padx=12)
        self.count = tk.Label(top, font=UI_FONT, bg=BG, fg="#555")
        self.count.pack(side="right")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=12)
        self.tree = ttk.Treeview(body, columns=("hex", "L", "brand", "pack", "photo", "status"),
                                 selectmode="extended")
        for col, text, width, anchor in (("#0", "Yarn", 190, "w"), ("hex", "Hex", 75, "w"),
                                         ("L", "L", 50, "e"), ("brand", "Brand", 125, "w"),
                                         ("pack", "Pack", 95, "w"), ("photo", "Photo", 60, "w"),
                                         ("status", "Status", 65, "w")):
            self.tree.heading(col, text=text, anchor=anchor if col != "#0" else "w")
            # Only the last column stretches; Yarn is sized to the longest name in refresh().
            self.tree.column(col, width=width, minwidth=40, anchor=anchor,
                             stretch=(col == "status"))
        self.tree.tag_configure("retired", foreground="#999999")
        # Clickable headings, as in the project tables. The default order is the palette's,
        # lightest first, so L's first click shows darkest first.
        self._rows = {}     # tree row id -> yarn, refilled by refresh()
        self._order = {}    # tree row id -> place in the default order
        y = lambda i: self._rows[i]
        photo_rank = {"yes": 0, "missing": 1, "": 2}
        self.sort = TreeSort(self.tree, {
            "#0": (lambda i: y(i).key, False),
            "hex": (lambda i: y(i).hex.lower(), False),
            "L": (lambda i: y(i).L, False),
            "brand": (lambda i: (not y(i).brand, y(i).brand.lower()), False),
            "pack": (lambda i: pal.effective_pack(y(i), self.app.brands) or 0, True),
            "photo": (lambda i: photo_rank[self.tree.set(i, "photo")], False),
            "status": (lambda i: y(i).retired, True),
        }, default=lambda i: self._order[i], on_change=lambda st: keep_sort(app, "palette_sort", st))
        self.sort.state = saved_sort(app, "palette_sort", self.sort)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        self.tree.bind("<Double-1>", lambda e: self.edit())
        self.tree.bind("<Delete>", lambda e: self.delete())
        self.tree.bind("<Control-a>", lambda e: (self.tree.selection_set(self.tree.get_children()),
                                                 "break")[1])

        buttons = tk.Frame(body, bg=BG)
        buttons.pack(side="left", fill="y", padx=(10, 0))
        self.retire_btn = None
        self.needs_selection = []
        for text, cmd in (("Add...", self.add), ("Edit...", self.edit),
                          ("Set brand...", self.set_brand), ("Retire", self.retire),
                          ("Delete...", self.delete), (None, None), ("Brands...", self.brands),
                          (None, None), ("Import...", self.import_),
                          ("Export CSV...", self.export_csv), ("Export GPL...", self.export_gpl)):
            if text is None:
                tk.Frame(buttons, height=14, bg=BG).pack()
                continue
            b = ttk.Button(buttons, text=text, width=14, command=cmd)
            b.pack(pady=2)
            if text == "Retire":
                self.retire_btn = b
            if text == "Edit...":
                self.edit_btn = b      # one yarn at a time
            elif text in ("Set brand...", "Retire", "Delete..."):
                self.needs_selection.append(b)

        tk.Label(self, font=HINT_FONT, bg=BG, fg="#666", anchor="w", justify="left",
                 text="Changes save immediately. Retired yarns are kept but not used for matching. "
                      "Pack sizes come from the brand.\n"
                      "Select several yarns (Ctrl+A for all shown) to set their brand at once. "
                      "Double-click to edit.").pack(fill="x", padx=12, pady=(6, 10))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()

    # ---------- list ----------
    def selected(self):
        by_id = {iid(y): y for y in self.app.bank}
        return [by_id[i] for i in self.tree.selection() if i in by_id]

    def pack_cell(self, y):
        p = pal.effective_pack(y, self.app.brands)
        return str(p) if p else "cut"

    def photo_cell(self, y):
        if not y.photo:
            return ""
        return "yes" if pal.has_photo(self.app.palette_path, y) else "missing"

    def refresh(self, select=None):
        keep = set(select) if select is not None else set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        needle = pal.name_key(self.find_var.get())
        shown = 0
        self._rows, self._order = {}, {}
        for y in pal.sort_yarns(self.app.bank):
            if y.retired and not self.show_retired.get():
                continue
            if needle and not any(needle in s for s in (y.key[0], y.key[1], y.hex.lower())):
                continue
            img = self.images.get(y.hex)
            if img is None:
                img = self.images[y.hex] = swatch_image([y.hex])
            self.tree.insert("", "end", iid=iid(y), text="  " + y.sku, image=img,
                             values=(y.hex, "%.1f" % y.L, y.brand or "–", self.pack_cell(y),
                                     self.photo_cell(y), "retired" if y.retired else ""),
                             tags=("retired",) if y.retired else ())
            self._rows[iid(y)] = y
            self._order[iid(y)] = shown
            shown += 1
        self.sort.apply()
        sel = [s for s in keep if self.tree.exists(s)]
        if sel:
            self.tree.selection_set(sel)
            self.tree.see(sel[0])
        font = tkfont.nametofont("TkDefaultFont")
        longest = max((font.measure("  " + y.sku) for y in self.app.bank), default=100)
        self.tree.column("#0", width=longest + 70)  # + tree indent and swatch image
        path = self.app.palette_path or ""
        self.file_label.config(text=os.path.basename(path))
        self.title("Latchwork - Yarn palette - %s" % os.path.basename(path))
        n_act = len(pal.active(self.app.bank))
        self.count.config(text="%d active, %d retired · %d brands   (showing %d)" % (
            n_act, len(self.app.bank) - n_act, len(self.app.brands), shown))
        self.on_select()

    def on_select(self):
        sel = self.selected()
        for b in self.needs_selection:
            b.state(["!disabled"] if sel else ["disabled"])
        self.edit_btn.state(["!disabled"] if len(sel) == 1 else ["disabled"])
        if sel and all(y.retired for y in sel):
            self.retire_btn.config(text="Restore")
        else:
            self.retire_btn.config(text="Retire")
        if len(sel) == 1 and not sel[0].retired:
            self.app.jump_to_yarn(sel[0].key)

    def commit(self, new_bank, select=(), brands=None):
        if self.app.set_bank(new_bank, brands):
            self.refresh(select=list(select))
            return True
        return False

    # ---------- yarn actions ----------
    def add(self):
        r = YarnDialog(self, self.app.bank, self.app.brands, self.app.palette_path).result
        if r:
            self._add(r)

    def _add(self, r):
        y = pal.Yarn(r["name"], r["rgb"], brand=r["brand"])
        if self._take_photo(r, y):
            self.commit(self.app.bank + [y], select=[iid(y)])

    def _take_photo(self, r, y):
        """Apply the dialog's photo change to y: copy a newly chosen photo in (named after the
        yarn as saved) or drop the link. False when the copy failed."""
        if r["photo_src"]:
            try:
                y.photo = photos.copy_in(r["photo_src"], self.app.palette_path, y)
            except (OSError, ValueError, tk.TclError) as e:
                messagebox.showerror("Photo", "Could not copy the photo\n%s\n\n%s"
                                     % (r["photo_src"], e), parent=self)
                return False
        elif r["photo_removed"]:
            y.photo = None
        return True

    def edit(self):
        sel = self.selected()
        if len(sel) != 1:     # the button is disabled then; double-click selects one first
            return
        y = sel[0]
        r = YarnDialog(self, self.app.bank, self.app.brands, self.app.palette_path,
                       yarn=y).result
        if not r:
            return
        new = [x.copy() for x in self.app.bank]
        target = new[self.app.bank.index(y)]
        target.sku, target.brand = r["name"], r["brand"]
        target.set_rgb(r["rgb"])
        if not self._take_photo(r, target):
            return
        if not self.commit(new, select=[iid(target)]):
            return
        if y.photo and target.photo != y.photo:
            discard_photo(self.app.palette_path, y)   # replaced or removed: drop the old copy
            try:
                tidy = r["photo_src"] and pal.tidy_photo_name(self.app.palette_path, target)
            except OSError:
                tidy = None
            if tidy:
                again = [x.copy() for x in self.app.bank]
                again[self.app.bank.index(target)].photo = tidy
                self.commit(again, select=[iid(target)])

    def set_brand(self):
        sel = self.selected()
        if not sel:
            return
        r = BrandChoiceDialog(
            self, self.app.brands, "Set brand",
            "Brand for the %d selected yarn%s:" % (len(sel), "" if len(sel) == 1 else "s"),
            current=sel[0].brand if len({y.key[1] for y in sel}) == 1 else "").result
        if not r:
            return
        ids = {id(y) for y in sel}
        new = []
        for x in self.app.bank:
            c = x.copy()
            if id(x) in ids:
                c.brand = r["brand"]
            new.append(c)
        dup = duplicates(new)
        if dup:
            messagebox.showerror("Set brand", "That would make two yarns with the same name and "
                                 "brand:\n\n  %s\n\nRename one of them first." % "\n  ".join(dup[:8]),
                                 parent=self)
            return
        brands = self.app.brands + ([pal.Brand(r["brand"], r["pack"])] if r["new"] else [])
        self.commit(new, select=[iid(c) for c, x in zip(new, self.app.bank) if id(x) in ids],
                    brands=brands)

    def retire(self):
        sel = self.selected()
        if not sel:
            return
        restore = all(y.retired for y in sel)
        ids = {id(y) for y in sel}
        new = [x.copy() for x in self.app.bank]
        for orig, c in zip(self.app.bank, new):
            if id(orig) in ids:
                c.retired = not restore
        self.commit(new, select=[iid(y) for y in sel])

    def delete(self):
        sel = self.selected()
        if not sel:
            return
        listing = "\n".join("  " + y.label for y in sel[:10]) + ("\n  ..." if len(sel) > 10 else "")
        if not messagebox.askyesno(
                "Delete yarns",
                "Permanently delete %d yarn(s)?\n\n%s\n\nDelete is for typos and mistakes. For a "
                "discontinued yarn, use Retire instead." % (len(sel), listing),
                icon="warning", parent=self):
            return
        gone = {id(y) for y in sel}
        if self.commit([x.copy() for x in self.app.bank if id(x) not in gone]):
            for y in sel:
                discard_photo(self.app.palette_path, y)

    def brands(self):
        BrandsDialog(self)

    # ---------- import / export ----------
    def import_(self):
        path = filedialog.askopenfilename(
            parent=self, title="Import yarns",
            filetypes=[("Palettes", "*.gpl *.csv"), ("GIMP palette", "*.gpl"), ("CSV", "*.csv"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            entries, in_brands = pal.read_import_file(path)
        except (OSError, ValueError, UnicodeDecodeError) as e:
            messagebox.showerror("Import", "Could not read %s\n\n%s" % (path, e), parent=self)
            return
        if not entries:
            messagebox.showinfo("Import", "No colors found in that file.", parent=self)
            return
        if pal.needs_brand(entries):
            r = BrandChoiceDialog(
                self, self.app.brands, "Import: brand",
                "%s has no brand information. Which brand are these %d colors?"
                % (os.path.basename(path), len(entries))).result
            if not r:
                return
            pal.set_brand(entries, r["brand"])
            if r["new"]:
                in_brands = in_brands + [pal.Brand(r["brand"], r["pack"])]
        items = pal.plan_import(self.app.bank, entries)
        if all(it.kind == pal.SAME for it in items):
            messagebox.showinfo(
                "Import", "Everything in %s is already in your palette (%d color%s).\n\n"
                "Nothing to import." % (os.path.basename(path), len(items),
                                        "" if len(items) == 1 else "s"), parent=self)
            return
        if not ImportDialog(self, self.app.bank, items, os.path.basename(path)).confirmed:
            return
        new = pal.apply_import(self.app.bank, items)
        before = {y.key for y in self.app.bank}
        self.commit(new, select=[iid(y) for y in new if y.key not in before],
                    brands=pal.merge_brands(self.app.brands, in_brands))

    def _export_stem(self):
        """The open palette's file name without .csv: exports are named after it."""
        return os.path.splitext(os.path.basename(self.app.palette_path or "palette.csv"))[0]

    def _export_folder(self):
        """Exports start next to the open palette."""
        return os.path.dirname(os.path.abspath(self.app.palette_path or "palette.csv"))

    def export_csv(self):
        folder = self._export_folder()
        path = filedialog.asksaveasfilename(
            parent=self, title="Export yarns as CSV", initialdir=folder, defaultextension=".csv",
            initialfile=free_name(folder, "%s-yarns.csv" % self._export_stem(),
                                  lambda p: [pal.brands_path(p)]),
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        n = sum(1 for y in self.app.bank if pal.has_photo(self.app.palette_path, y))

        def write():
            yarns = pal.copy_photos(self.app.palette_path, path, self.app.bank)
            pal.save_bank(path, yarns, self.app.brands)
        self._export(write, path, "%d yarns (including retired) and their brands\n(%s)%s"
                     % (len(self.app.bank), os.path.basename(pal.brands_path(path)),
                        "\nand %d photos (in %s)" % (n, os.path.basename(pal.swatch_dir(path)))
                        if n else ""))

    def export_gpl(self):
        folder = self._export_folder()
        path = filedialog.asksaveasfilename(
            parent=self, title="Export yarns as GIMP palette", initialdir=folder,
            defaultextension=".gpl", initialfile=free_name(folder, "%s.gpl" % self._export_stem()),
            filetypes=[("GIMP palette", "*.gpl")])
        if path:
            self._export(lambda: pal.write_gpl(path, self.app.bank), path,
                         "%d active yarns (retired ones are left out)" % len(pal.active(self.app.bank)))

    def _export(self, write, path, what):
        try:
            write()
        except OSError as e:
            messagebox.showerror("Export", "Could not write %s\n\n%s" % (path, e), parent=self)
            return
        messagebox.showinfo("Export", "Exported %s to\n%s" % (what, path), parent=self)

    def close(self):
        self.app.palette_window = None
        if self.state() == "normal":
            self.app.keep_geometry("palette_manager", self.geometry())
        self.destroy()


def photo_title(path):
    """A starting name for a yarn added from a photo: the file name without its extension."""
    return pal.clean_name(os.path.splitext(os.path.basename(path))[0].replace("_", " "))


def discard_photo(palette_path, yarn):
    """Delete the yarn's copy in the photo folder (the photo it was chosen from is untouched)."""
    f = pal.photo_file(palette_path, yarn)
    if f and os.path.isfile(f):
        try:
            os.remove(f)
        except OSError:
            pass


class BrandChoiceDialog(tk.Toplevel):
    """Pick an existing brand or type a new one (with its pack size).
    result = {"brand", "new": bool, "pack": int|None (new brands)} or None."""

    def __init__(self, parent, brands, title, message, current=""):
        super().__init__(parent)
        self.brands, self.result = brands, None
        self.title(title)
        self.configure(bg=BG, padx=16, pady=14)
        self.resizable(False, False)
        self.transient(parent)
        tk.Label(self, text=message, font=UI_FONT, bg=BG, wraplength=380, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        required_label(self, "Brand", BG).grid(row=1, column=0, sticky="w")
        self.brand_var = tk.StringVar(value=current)
        box = ttk.Combobox(self, textvariable=self.brand_var, width=28,
                           values=[b.name for b in brands])
        box.grid(row=1, column=1, sticky="w", padx=8)
        self.brand_note = FieldNote(self, BG)
        self.brand_note.grid(row=2, column=1, sticky="ew", padx=8)
        tk.Label(self, text="Pack size", font=UI_FONT, bg=BG).grid(row=3, column=0, sticky="w",
                                                                   pady=(2, 0))
        self.pack_var = tk.StringVar()      # what I type for a new brand
        self.brand_pack = tk.StringVar()    # an existing brand's, shown in the disabled field
        self.pack_entry = ttk.Entry(self, textvariable=self.pack_var, width=8)
        self.pack_entry.grid(row=3, column=1, sticky="w", padx=8, pady=(2, 0))
        self.pack_note = FieldNote(self, BG)
        self.pack_note.grid(row=4, column=1, sticky="ew", padx=8)
        required_legend(self, BG).grid(row=5, column=0, sticky="sw", pady=(10, 0))
        btns = tk.Frame(self, bg=BG)
        btns.grid(row=5, column=1, sticky="e", pady=(10, 0))
        self.touched = False   # "Required" only once I've typed in the brand box
        self.ok = ttk.Button(btns, text="OK", command=self.accept)
        self.ok.pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda e: self.accept())
        self.bind("<Escape>", lambda e: self.destroy())
        self.brand_var.trace_add("write", lambda *_: self.update_view(touched=True))
        self.pack_var.trace_add("write", lambda *_: self.update_view())
        self.update_view()
        center_on(self, parent)
        box.focus_set()
        self.grab_set()
        self.wait_window()

    def check(self):
        """(result or None, {field: what's wrong})."""
        name = pal.clean_name(self.brand_var.get())
        if not name:
            return None, {"brand": "Required"}
        b = pal.brand_by_key(self.brands, name)
        if b:
            return {"brand": b.name, "new": False, "pack": b.pack}, {}
        try:
            pack = pal.parse_pack(self.pack_var.get())
        except ValueError:
            return None, {"pack": "Must be a whole number"}
        return {"brand": name, "new": True, "pack": pack}, {}

    def update_view(self, touched=False):
        self.touched = self.touched or touched
        b = pal.brand_by_key(self.brands, self.brand_var.get())
        if b:
            self.brand_pack.set(str(b.pack) if b.pack else "cut")
            self.pack_entry.config(textvariable=self.brand_pack)
            self.pack_entry.state(["disabled"])
        else:
            self.pack_entry.config(textvariable=self.pack_var)   # back to what I typed
            self.pack_entry.state(["!disabled"])
        r, errs = self.check()
        self.brand_note.set(errs.get("brand") if self.touched else None)
        self.pack_note.set(errs.get("pack"), helper="" if b else PACK_HELP)
        self.ok.state(["disabled"] if errs else ["!disabled"])

    def accept(self):
        r, err = self.check()
        if not err:
            self.result = r
            self.destroy()


class BrandsDialog(tk.Toplevel):
    """The palette's brand list: name and pack size. Changes apply immediately."""

    def __init__(self, win):
        super().__init__(win)
        self.win, self.app = win, win.app
        self.title("Brands")
        self.configure(bg=BG, padx=14, pady=12)
        self.transient(win)
        tk.Label(self, text="Pack size is the number of pre-cut pieces per pack; \"cut\" means "
                            "you cut it from skeins. Every yarn uses its brand's pack size.",
                 font=HINT_FONT, bg=BG, fg="#555",
                 wraplength=440, justify="left").pack(fill="x", pady=(0, 8))
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("pack", "yarns"), selectmode="browse", height=8)
        for col, text, width, anchor in (("#0", "Brand", 190, "w"), ("pack", "Pack size", 110, "w"),
                                         ("yarns", "Yarns", 60, "e")):
            self.tree.heading(col, text=text, anchor="w" if col != "yarns" else "e")
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "#0"))
        # Sortable like the yarn table; the default is the palette's brand order.
        brand = lambda i: pal.brand_by_key(self.app.brands, i)
        self.sort = TreeSort(self.tree, {
            "#0": (lambda i: brand(i).name.lower(), False),
            "pack": (lambda i: brand(i).pack or 0, True),
            "yarns": (lambda i: int(self.tree.set(i, "yarns")), True),
        }, default=lambda i: self._order[i], on_change=lambda st: keep_sort(self.app, "brands_sort", st))
        self.sort.state = saved_sort(self.app, "brands_sort", self.sort)
        self._order = {}
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.edit())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        btns = tk.Frame(body, bg=BG)
        btns.pack(side="left", fill="y", padx=(10, 0))
        ttk.Button(btns, text="Add...", width=10, command=self.add).pack(pady=2)
        self.edit_btn = ttk.Button(btns, text="Edit...", width=10, command=self.edit)
        self.edit_btn.pack(pady=2)
        self.del_btn = ttk.Button(btns, text="Delete", width=10, command=self.delete)
        self.del_btn.pack(pady=2)
        ttk.Button(self, text="Close", command=self.destroy).pack(anchor="e", pady=(10, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        self.refresh()
        center_on(self, win)
        self.grab_set()

    def refresh(self, select=None):
        self.tree.delete(*self.tree.get_children())
        self._order = {}
        for i, b in enumerate(self.app.brands):
            n = sum(1 for y in self.app.bank if y.key[1] == b.key)
            self.tree.insert("", "end", iid=b.key, text="  " + b.name,
                             values=(str(b.pack) if b.pack else "cut", n))
            self._order[b.key] = i
        self.sort.apply()
        if select and self.tree.exists(select):
            self.tree.selection_set(select)
        self.on_select()

    def current(self):
        sel = self.tree.selection()
        return pal.brand_by_key(self.app.brands, sel[0]) if sel else None

    def on_select(self):
        b = self.current()
        self.edit_btn.state(["!disabled"] if b else ["disabled"])
        used = b and any(y.key[1] == b.key for y in self.app.bank)
        self.del_btn.state(["!disabled"] if b and not used else ["disabled"])

    def _save(self, brands, bank=None, select=None):
        if self.win.commit(bank if bank is not None else [y.copy() for y in self.app.bank],
                           brands=brands):
            self.refresh(select)

    def add(self):
        r = BrandEditDialog(self, self.app.brands).result
        if r:
            self._save(self.app.brands + [pal.Brand(r["name"], r["pack"])],
                       select=pal.name_key(r["name"]))

    def edit(self):
        b = self.current()
        if not b:
            return
        r = BrandEditDialog(self, self.app.brands, brand=b).result
        if not r:
            return
        brands = [x.copy() for x in self.app.brands]
        target = pal.brand_by_key(brands, b.name)
        old_key = target.key
        target.name, target.pack = r["name"], r["pack"]
        bank = []
        for y in self.app.bank:      # a rename carries over to every yarn of the brand
            c = y.copy()
            if c.key[1] == old_key:
                c.brand = r["name"]
            bank.append(c)
        self._save(brands, bank, select=target.key)

    def delete(self):
        b = self.current()
        if b and messagebox.askyesno("Delete brand", "Delete the brand %s?" % b.name, parent=self):
            self._save([x.copy() for x in self.app.brands if x.key != b.key])


class BrandEditDialog(tk.Toplevel):
    """Add or edit a brand. result = {"name", "pack"} or None."""

    def __init__(self, parent, brands, brand=None):
        super().__init__(parent)
        self.brands, self.brand, self.result = brands, brand, None
        self.title("Edit brand" if brand else "Add brand")
        self.configure(bg=BG, padx=16, pady=14)
        self.resizable(False, False)
        self.transient(parent)
        required_label(self, "Name", BG).grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=brand.name if brand else "")
        e = ttk.Entry(self, textvariable=self.name_var, width=28)
        e.grid(row=0, column=1, sticky="w", padx=8)
        self.name_note = FieldNote(self, BG)
        self.name_note.grid(row=1, column=1, sticky="ew", padx=8)
        tk.Label(self, text="Pack size", font=UI_FONT, bg=BG).grid(row=2, column=0, sticky="w",
                                                                   pady=(2, 0))
        self.pack_var = tk.StringVar(value=str(brand.pack) if brand and brand.pack else "")
        ttk.Entry(self, textvariable=self.pack_var, width=8).grid(row=2, column=1, sticky="w",
                                                                 padx=8, pady=(2, 0))
        self.pack_note = FieldNote(self, BG, PACK_HELP)
        self.pack_note.grid(row=3, column=1, sticky="ew", padx=8)
        required_legend(self, BG).grid(row=4, column=0, sticky="sw", pady=(10, 0))
        btns = tk.Frame(self, bg=BG)
        btns.grid(row=4, column=1, sticky="e", pady=(10, 0))
        self.touched = False   # "Required" only once I've typed in the name
        self.ok = ttk.Button(btns, text="Save" if brand else "Add", command=self.accept)
        self.ok.pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda ev: self.accept())
        self.bind("<Escape>", lambda ev: self.destroy())
        self.name_var.trace_add("write", lambda *_: self.update_view(touched=True))
        self.pack_var.trace_add("write", lambda *_: self.update_view())
        self.update_view()
        center_on(self, parent)
        e.focus_set()
        self.grab_set()
        self.wait_window()

    def check(self):
        """(result or None, {field: what's wrong})."""
        errs = {}
        name = pal.clean_name(self.name_var.get())
        other = pal.brand_by_key(self.brands, name)
        if not name:
            errs["name"] = "Required"
        elif other and (self.brand is None or other.key != self.brand.key):
            errs["name"] = "Already exists"
        try:
            pack = pal.parse_pack(self.pack_var.get())
        except ValueError:
            errs["pack"] = "Must be a whole number"
        return (None if errs else {"name": name, "pack": pack}), errs

    def update_view(self, touched=False):
        self.touched = self.touched or touched
        _, errs = self.check()
        name_err = errs.get("name")
        self.name_note.set(name_err if self.touched or name_err != "Required" else None)
        self.pack_note.set(errs.get("pack"))
        self.ok.state(["disabled"] if errs else ["!disabled"])

    def accept(self):
        r, err = self.check()
        if not err:
            self.result = r
            self.destroy()


PACK_HELP = "Blank = cut from skeins"


def tip(widget, text, title=None):
    """Hover help for a widget; text may be a function returning the text (or None)."""
    def content(_event):
        t = text() if callable(text) else text
        return (title, [([], t)]) if t else None
    return Tooltip(widget, content)


class YarnDialog(tk.Toplevel):
    """Add or edit one yarn, including its photo. Nothing is saved or copied until Add/Save.
    result = {"name", "rgb", "brand", "photo_src", "photo_removed"} or None, where
    photo_src is a newly chosen photo to copy in and photo_removed means drop the yarn's photo.
    Choosing a photo for a new yarn fills in its name and color when those are still empty."""

    PHOTO_SIDE = 150

    def __init__(self, parent, bank, brands, palette_path, yarn=None):
        super().__init__(parent)
        self.bank, self.brands, self.yarn, self.result = bank, brands, yarn, None
        self.palette_path = palette_path
        self.photo_src, self.photo_removed = None, False
        self.thumb = self.avg = self.suggested = None
        self.problem = None
        self.title("Edit yarn" if yarn else "Add yarn")
        self.configure(bg=BG, padx=16, pady=14)
        self.resizable(False, False)
        self.transient(parent)

        # Header, like a profile: the photo on the left, the yarn's details beside it.
        top = tk.Frame(self, bg=BG)
        top.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self._build_photo(top)
        form = tk.Frame(top, bg=BG)
        form.grid(row=0, column=1, sticky="nw", padx=(14, 0))
        required_label(form, "Name", BG).grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=yarn.sku if yarn else "")
        self.name_entry = name_entry = ttk.Entry(form, textvariable=self.name_var, width=21,
                                                 font=("Segoe UI", 11))
        name_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0))
        self.name_note = FieldNote(form, BG)
        self.name_note.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(8, 0))
        tk.Label(form, text="Brand", font=UI_FONT, bg=BG).grid(row=2, column=0, sticky="w")
        # Picked from the palette's brands only: new brands are added under Brands...,
        # where their pack size is set, so a typo can't make a stray brand.
        if yarn:
            b = pal.brand_by_key(brands, yarn.brand)
            last = b.name if b else (yarn.brand or NO_BRAND)
        else:
            last = brands[0].name if len(brands) == 1 else NO_BRAND
        self.brand_var = tk.StringVar(value=last)
        brand_box = ttk.Combobox(form, textvariable=self.brand_var, state="readonly",
                                 values=[b.name for b in brands] + [NO_BRAND])
        brand_box.grid(row=2, column=1, columnspan=3, sticky="ew", padx=(8, 0))
        tip(brand_box, "The yarn's brand, from the palette's brand list.\n"
                       "Add a new brand under Brands... first.")

        # What the photo suggests, as copyable hex codes (like HTML notation below).
        self.photo_rows = []
        self.avg_var, self.sug_var = tk.StringVar(), tk.StringVar()
        helps = ("The average of every pixel in the photo (in linear light,\n"
                 "as mixing light does).",
                 "The average, lightened: L x %.3f + %.2f. An average counts\n"
                 "the shadows between strands, so it reads darker than the\n"
                 "yarn looks; this is how picked yarn colors compare to\n"
                 "their photos. Copy it into HTML notation to use it."
                 % (SWATCH_L_SCALE, SWATCH_L_OFFSET))
        for r, (label, var, help_) in enumerate((("Average", self.avg_var, helps[0]),
                                                 ("Suggested", self.sug_var, helps[1])), 3):
            lab = tk.Label(form, text=label, font=UI_FONT, bg=BG)
            line = tk.Frame(form, bg=BG)
            chip = tk.Frame(line, width=18, height=18, highlightthickness=1,
                            highlightbackground="#888")
            chip.pack(side="left")
            entry = ttk.Entry(line, textvariable=var, font=("Consolas", 10), width=8,
                              state="readonly")
            entry.pack(side="left", padx=(6, 0))
            entry.bind("<FocusIn>", lambda e: e.widget.after_idle(
                lambda w=e.widget: w.select_range(0, "end")))
            Lval = tk.Label(line, font=UI_FONT, bg=BG, fg="#444")
            Lval.pack(side="left", padx=(8, 0))
            lab.grid(row=r, column=0, sticky="w", pady=(8 if r == 3 else 3, 0))
            line.grid(row=r, column=1, columnspan=3, sticky="w", padx=(8, 0),
                      pady=(8 if r == 3 else 3, 0))
            for w in (lab, chip, entry, Lval):
                tip(w, help_)
            self.photo_rows.append((chip, Lval, [lab, line]))

        # Neighbor preview: lighter neighbor | this yarn | darker neighbor, names underneath.
        self.swatch = tk.Canvas(self, width=self.SW_W, height=self.SW_H, bg=BG,
                                highlightthickness=0)
        self.swatch.grid(row=1, column=0, columnspan=2, pady=(0, 8))

        self.hex_var = tk.StringVar(value=yarn.hex if yarn else "")
        self.panel = ColorPanel(self, self.hex_var, editable=True, note="e.g. #88A048")
        self.panel.grid(row=2, column=0, columnspan=2, sticky="ew")

        # Where it would sit: always two lines tall (three for a retired yarn's note), so the
        # dialog doesn't change size as the color becomes valid or invalid.
        self.info = tk.Label(self, font=UI_FONT, bg=BG, justify="left", anchor="nw",
                             wraplength=self.SW_W, height=3 if yarn and yarn.retired else 2)
        self.info.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        required_legend(self, BG).grid(row=6, column=0, sticky="sw", pady=(12, 0))
        btns = tk.Frame(self, bg=BG)
        btns.grid(row=6, column=1, sticky="e", pady=(12, 0))
        self.touched = set()   # fields I've typed in: only those can say "Required"
        self.ok = ttk.Button(btns, text="Save" if yarn else "Add", command=self.accept)
        self.ok.pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda e: self.accept())
        self.bind("<Escape>", lambda e: self.destroy())

        for v, field in ((self.name_var, "name"), (self.hex_var, "hex"), (self.brand_var, None)):
            v.trace_add("write", lambda *_, f=field: self.update_view(touched=f))
        self.show_photo()
        self.update_view()
        center_on(self, parent)
        (self.panel.entry if yarn else name_entry).focus_set()
        self.grab_set()
        self.wait_window()

    SW_W, SW_H, SIDE_W, BLOCK_H = 420, 96, 100, 70

    # ---------- photo ----------
    def _build_photo(self, top):
        side = self.PHOTO_SIDE
        left = tk.Frame(top, bg=BG)
        left.grid(row=0, column=0, sticky="nw")
        # 1 px in from each side: the themed buttons below draw their border 1 px inside
        # their space, so this lines the photo's border up with theirs.
        holder = tk.Frame(left, bg="#DDD", width=side, height=side, highlightthickness=1,
                          highlightbackground="#BBB")
        holder.pack(padx=1)
        holder.pack_propagate(False)
        self.picture = tk.Label(holder, bg="#DDD", font=HINT_FONT, fg="#777", justify="center",
                                wraplength=side - 16, cursor="hand2")
        self.picture.pack(fill="both", expand=True)
        self.picture.bind("<Button-1>", lambda e: self.choose_photo())
        tip(self.picture, self._photo_tip)
        row = tk.Frame(left, bg=BG)
        row.pack(fill="x", pady=(4, 0))
        row.columnconfigure((0, 1), weight=1, uniform="photo")
        # width=1: the buttons take the photo's width between them, not their own
        ttk.Button(row, text="Choose...", width=1, command=self.choose_photo).grid(
            row=0, column=0, sticky="ew")
        self.remove_btn = ttk.Button(row, text="Remove", width=1, command=self.remove_photo)
        self.remove_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        tip(self.remove_btn, "Take the photo off this yarn. Its copy in the photo folder is\n"
                             "deleted when you press Save; the photo you chose it from\n"
                             "is never touched.")

    def _photo_tip(self):
        folder = os.path.basename(pal.swatch_dir(self.palette_path or "palette.csv"))
        if self.problem:
            return "%s\nChoose the photo again, or remove it from this yarn." % self.problem
        if self.thumb:
            return ("Click to choose a different photo (PNG or GIF).\n"
                    "It's copied into %s when you press %s." % (
                        folder, "Save" if self.yarn else "Add"))
        return ("Click to choose a photo of this yarn (PNG or GIF), optional.\n"
                "It's copied into %s when you press %s." % (
                    folder, "Save" if self.yarn else "Add"))

    def photo_path(self):
        """The photo shown: a newly chosen one, else the yarn's own (None when there's none)."""
        if self.photo_src:
            return self.photo_src
        if self.yarn and self.yarn.photo and not self.photo_removed:
            return pal.photo_file(self.palette_path, self.yarn)
        return None

    def show_photo(self, img=None):
        """img: the photo at photo_path(), when it's already loaded."""
        self.thumb = self.avg = self.suggested = self.problem = None
        path = self.photo_path()
        if path and (img or os.path.isfile(path)):
            try:
                img = img or photos.load(path, master=self)
                self.thumb = photos.thumbnail(img, self.PHOTO_SIDE)
                self.avg, self.suggested = photos.colors(img)
            except ValueError as e:
                self.problem = "Can't read the photo: %s" % e
        elif path:
            self.problem = "Photo missing: %s" % self.yarn.photo
        if self.thumb:
            self.picture.config(image=self.thumb, text="")
        elif self.problem:
            self.picture.config(image="", text="Photo missing" if path and not os.path.isfile(
                path) else "Can't read the photo")
        else:
            self.picture.config(image="", text="No photo\n\nclick to choose one")
        for (chip, Lval, cells), rgb, var in zip(self.photo_rows, (self.avg, self.suggested),
                                                 (self.avg_var, self.sug_var)):
            # always shown (empty without a photo) so the dialog keeps its size
            var.set(to_hex(*rgb) if rgb else "")
            chip.config(bg=to_hex(*rgb) if rgb else "#DDD")
            Lval.config(text="L %.1f" % lightness(*rgb) if rgb else "L  –")
        has = bool(self.photo_src or (self.yarn and self.yarn.photo and not self.photo_removed))
        self.remove_btn.state(["!disabled"] if has else ["disabled"])

    def set_photo(self, path, img=None):
        self.photo_src, self.photo_removed = path, False
        self.show_photo(img)
        if not self.yarn:      # a new yarn starts from the photo: its name and suggested color
            if not pal.clean_name(self.name_var.get()):
                self.name_var.set(photo_title(path))
            if self.suggested and not parse_hex(self.hex_var.get()):
                self.hex_var.set(to_hex(*self.suggested))

    def choose_photo(self):
        path = filedialog.askopenfilename(parent=self, title="Photo of this yarn",
                                          filetypes=photos.FILETYPES)
        if not path:
            return
        try:
            img = photos.load(path, master=self)
        except ValueError as e:
            messagebox.showerror("Photo", str(e), parent=self)
            return
        self.set_photo(path, img)

    def remove_photo(self):
        self.photo_src = None
        self.photo_removed = bool(self.yarn and self.yarn.photo)
        self.show_photo()

    # ---------- form ----------
    def brand(self):
        v = self.brand_var.get()
        return "" if v == NO_BRAND else pal.clean_name(v)

    def problems(self):
        rgb = parse_hex(self.hex_var.get())
        brand = self.brand()
        b = pal.brand_by_key(self.brands, brand)
        if b:
            brand = b.name   # use the brand's own spelling
        errs = {}
        if not pal.clean_name(self.name_var.get()):
            errs["name"] = "Required"
        elif pal.name_problem(self.name_var.get(), brand, self.bank, exclude=self.yarn):
            same = next(y for y in self.bank if y is not self.yarn
                        and y.key == pal.yarn_key(self.name_var.get(), brand))
            errs["name"] = ("Already in the palette (retired)" if same.retired
                            else "Already in the palette")
        if not self.hex_var.get().strip():
            errs["hex"] = "Required"
        elif rgb is None:
            errs["hex"] = "Not a valid hex color"
        if errs:
            return None, errs
        return {"name": pal.clean_name(self.name_var.get()), "rgb": rgb, "brand": brand,
                "photo_src": self.photo_src,
                "photo_removed": self.photo_removed}, {}

    def update_view(self, touched=None):
        if touched:
            self.touched.add(touched)
        r, errs = self.problems()
        for field, note in (("name", self.name_note), ("hex", self.panel.note)):
            e = errs.get(field)
            note.set(e if field in self.touched or e != "Required" else None)
        rgb = parse_hex(self.hex_var.get())
        c = self.swatch
        c.delete("all")
        self.panel.show(rgb)
        name = pal.clean_name(self.name_var.get()) or "New yarn"
        mid0, mid1 = self.SIDE_W + 8, self.SW_W - self.SIDE_W - 9
        if rgb:
            y = pal.Yarn("preview", rgb)
            pos, total, lighter, darker = pal.placement(self.bank, y.L, exclude=self.yarn)
            # Canvas outlines straddle their coordinates: keep every edge inside the canvas.
            for x0, x1, nb in ((0, self.SIDE_W, lighter),
                               (self.SW_W - self.SIDE_W - 1, self.SW_W - 1, darker)):
                if nb:
                    c.create_rectangle(x0, 8, x1, self.BLOCK_H - 8, fill=nb.hex, outline="#999")
                    c.create_text((x0 + x1) / 2, self.BLOCK_H + 2, text=nb.sku, anchor="n",
                                  width=self.SIDE_W + 4, font=("Segoe UI", 8), fill="#555")
            c.create_rectangle(mid0, 1, mid1, self.BLOCK_H, fill=y.hex, outline="#333", width=2)
            c.create_text((mid0 + mid1) / 2, self.BLOCK_H + 2, text=name, anchor="n",
                          width=mid1 - mid0, font=("Segoe UI", 9, "bold"))
            where = ("between %s and %s" % (lighter.label, darker.label) if lighter and darker else
                     "lightest, before %s" % darker.label if darker else
                     "darkest, after %s" % lighter.label if lighter else "the only yarn")
            text = "Would sit at %d / %d, %s." % (pos, total, where)
            if self.yarn and self.yarn.retired:
                text += "\n(This yarn is retired, so it isn't used for matching.)"
            self.info.config(text=text)
        else:
            c.create_rectangle(mid0, 0, mid1, self.BLOCK_H, fill="#DDD", outline="#BBB")
            c.create_text((mid0 + mid1) / 2, self.BLOCK_H / 2, text="enter HTML notation below",
                          font=UI_FONT, fill="#777")
            self.info.config(text="")
        self.ok.state(["disabled"] if errs else ["!disabled"])

    def accept(self):
        r, err = self.problems()
        if err:
            return
        self.result = r
        self.destroy()


class ImportDialog(tk.Toplevel):
    """Shows what an import would do and lets me choose per item. self.confirmed = bool."""

    def __init__(self, parent, bank, items, filename):
        super().__init__(parent)
        self.bank, self.items, self.confirmed = bank, items, False
        self.shown = [it for it in items if it.kind != pal.SAME]
        self.images = []
        self.title("Import from %s" % filename)
        self.configure(bg=BG, padx=12, pady=12)
        self.geometry("880x560")
        self.minsize(700, 420)
        self.transient(parent)

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="Import from %s" % filename, font=("Segoe UI", 15, "bold"),
                 bg=BG).pack(side="left")
        tk.Label(head, text="   %d color%s in the file" % (len(items), "" if len(items) == 1 else "s"),
                 font=("Segoe UI", 11), bg=BG, fg="#555").pack(side="left", pady=(5, 0))
        self.badges = tk.Canvas(self, height=30, bg=BG, highlightthickness=0)
        self.badges.pack(fill="x", pady=(8, 4))
        tk.Label(self, font=HINT_FONT, bg=BG, fg="#555", anchor="w",
                 text="Swatches: the file's color on the left, your yarn's on the right. Select rows "
                      "and pick an action below. Nothing changes until you press Import.").pack(
            fill="x", pady=(0, 6))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("issue", "file", "mine", "action"),
                                 selectmode="extended")
        for col, text, width in (("#0", "Name in file", 230), ("issue", "What it is", 230),
                                 ("file", "File hex", 75), ("mine", "Your yarn", 160),
                                 ("action", "Action", 220)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, stretch=(col in ("#0", "action")))
        self.tree.tag_configure("attention", background="#FFF4CC")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())

        ctl = tk.Frame(self, bg=BG)
        ctl.pack(fill="x", pady=(8, 0))
        tk.Label(ctl, text="Action for selected", font=UI_FONT, bg=BG).pack(side="left")
        self.action_var = tk.StringVar()
        self.action_box = ttk.Combobox(ctl, textvariable=self.action_var, state="readonly",
                                       width=30)
        self.action_box.pack(side="left", padx=6)
        self.action_box.bind("<<ComboboxSelected>>", lambda e: self.set_action())
        ttk.Button(ctl, text="Select all like this", command=self.select_kind).pack(
            side="left", padx=(6, 0), ipadx=8)
        tk.Label(ctl, text="New name", font=UI_FONT, bg=BG).pack(side="left", padx=(24, 4))
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(ctl, textvariable=self.name_var, width=24)
        self.name_entry.pack(side="left")
        self.name_var.trace_add("write", lambda *_: self.set_name())

        # three lines, always: the table and the controls above stay put as problems come and go
        self.problems = tk.Label(self, font=UI_FONT, bg=BG, fg="#B00020", anchor="nw",
                                 justify="left", height=3)
        self.problems.pack(fill="x", pady=(8, 0))
        btns = tk.Frame(self, bg=BG)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        self.ok = ttk.Button(btns, text="Import", command=self.accept)
        self.ok.pack(side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())

        self._updating = False
        for i, it in enumerate(self.shown):
            colors = [it.entry.hex] + ([it.existing.hex] if it.existing else [])
            img = swatch_image(colors, w=48, slots=2)
            self.images.append(img)
            mine = ""
            if it.existing:
                mine = "%s %s%s" % (it.existing.label, it.existing.hex,
                                    " (retired)" if it.existing.retired else "")
            self.tree.insert("", "end", iid=str(i),
                             text="  " + (it.entry.label if it.entry.name else "(no name)"),
                             image=img, values=(it.describe(), it.entry.hex, mine, ""),
                             tags=("attention",) if it.kind != pal.NEW else ())
        self.update_rows()
        self.on_select()
        center_on(self, parent)
        self.grab_set()
        self.wait_window()

    def sel_items(self):
        return [self.shown[int(i)] for i in self.tree.selection()]

    def update_rows(self):
        for i, it in enumerate(self.shown):
            label = pal.ACTION_LABELS[it.action]
            if it.needs_name:
                n = pal.clean_name(it.new_name)
                label = 'Add as "%s"' % n if n else "Add as … (type a name)"
            self.tree.set(str(i), "action", label)
        problems = pal.import_problems(self.bank, self.items)
        self.draw_badges(problems)
        shown = problems if len(problems) <= 3 else problems[:2] + [
            "... and %d more" % (len(problems) - 2)]
        self.problems.config(text="\n".join(shown))
        self.ok.state(["disabled"] if problems else ["!disabled"])

    # (outcome key, label, text/outline color, fill)
    BADGES = (("add", "Add", "#1B5E20", "#DCEFDD"),
              ("update", "Update", "#0D47A1", "#DCE8F7"),
              ("skip", "Skip", "#424242", "#E4E4E4"),
              ("same", "Already there", "#616161", "#F7F7F7"),
              ("problem", "Needs attention", "#B71C1C", "#F9DEDE"))

    @staticmethod
    def outcome_of(it):
        if it.kind == pal.SAME:
            return "same"
        if it.action in ("add", "keep_both", "add_named"):
            return "add"
        if it.action in ("skip", "keep_mine"):
            return "skip"
        return "update"

    def draw_badges(self, problems):
        counts = {}
        for it in self.items:
            o = self.outcome_of(it)
            counts[o] = counts.get(o, 0) + 1
        counts["problem"] = len(problems)
        c = self.badges
        c.delete("all")
        font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        x = 1
        for key, label, fg, fill in self.BADGES:
            n = counts.get(key, 0)
            if not n and key != "add":
                continue
            text = "%s  %d" % (label, n)
            w = font.measure(text) + 26
            _round_rect(c, x, 2, x + w, 28, 12, fill=fill, outline=fg)
            c.create_text(x + w / 2, 15, text=text, font=font, fill=fg)
            x += w + 8

    def on_select(self):
        sel = self.sel_items()
        self._updating = True
        if sel:
            common = [o for o in sel[0].options if all(o in it.options for it in sel)]
            self.action_box.configure(values=[pal.ACTION_LABELS[o] for o in common])
            actions = {it.action for it in sel}
            self.action_var.set(pal.ACTION_LABELS[sel[0].action] if len(actions) == 1 else "")
            self.action_box.state(["!disabled"] if common else ["disabled"])
        else:
            self.action_box.configure(values=[])
            self.action_var.set("")
            self.action_box.state(["disabled"])
        one = sel[0] if len(sel) == 1 else None
        if one and one.needs_name:
            self.name_entry.state(["!disabled"])
            self.name_var.set(one.new_name)
        else:
            self.name_var.set("")
            self.name_entry.state(["disabled"])
        self._updating = False

    def set_action(self):
        label = self.action_var.get()
        action = next((k for k, v in pal.ACTION_LABELS.items() if v == label), None)
        if not action:
            return
        taken = {y.key for y in self.bank} | {pal.yarn_key(it.new_name, it.entry.brand or "")
                                              for it in self.items if it.needs_name}
        for it in self.sel_items():
            if action in it.options:
                it.action = action
                if it.needs_name and not it.new_name:
                    if it.kind == pal.PLACEHOLDER:
                        it.new_name = ""
                    else:
                        brand = it.entry.brand or ""
                        it.new_name = pal.suggest_name(it.entry.name, brand, taken)
                        taken.add(pal.yarn_key(it.new_name, brand))
        self.update_rows()
        self.on_select()
        if len(self.sel_items()) == 1 and self.sel_items()[0].needs_name:
            self.name_entry.focus_set()

    def set_name(self):
        if self._updating:
            return
        sel = self.sel_items()
        if len(sel) == 1 and sel[0].needs_name:
            sel[0].new_name = self.name_var.get()
            self.update_rows()

    def select_kind(self):
        sel = self.sel_items()
        if not sel:
            return
        kinds = {it.kind for it in sel}
        self.tree.selection_set([str(i) for i, it in enumerate(self.shown) if it.kind in kinds])

    def accept(self):
        if pal.import_problems(self.bank, self.items):
            return
        self.confirmed = True
        self.destroy()
