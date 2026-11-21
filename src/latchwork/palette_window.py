"""Palette manager window: yarns (add, edit, brand, retire, delete), brands, import and export."""
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from . import palette as pal
from .colormath import parse_hex
from .widgets import ColorPanel

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


def pack_text(pack):
    return "%d per pack" % pack if pack else "cut from skein"


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
        self.tree = ttk.Treeview(body, columns=("hex", "L", "brand", "pack", "status"),
                                 selectmode="extended")
        for col, text, width, anchor in (("#0", "Yarn", 190, "w"), ("hex", "Hex", 75, "w"),
                                         ("L", "L", 50, "e"), ("brand", "Brand", 125, "w"),
                                         ("pack", "Pack", 95, "w"), ("status", "Status", 65, "w")):
            self.tree.heading(col, text=text, anchor=anchor if col != "#0" else "w")
            # Only the last column stretches; Yarn is sized to the longest name in refresh().
            self.tree.column(col, width=width, minwidth=40, anchor=anchor,
                             stretch=(col == "status"))
        self.tree.tag_configure("retired", foreground="#999999")
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
            if text in ("Edit...", "Set brand...", "Retire", "Delete..."):
                self.needs_selection.append(b)

        tk.Label(self, font=HINT_FONT, bg=BG, fg="#666", anchor="w", justify="left",
                 text="Changes save immediately. Retired yarns are kept but not used for matching. "
                      "Pack sizes come from the brand unless a yarn has its own.\n"
                      "Select several yarns (Ctrl+A for all shown) to set their brand at once. "
                      "Double-click to edit.").pack(fill="x", padx=12, pady=(6, 10))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()

    # ---------- list ----------
    def selected(self):
        by_id = {iid(y): y for y in self.app.bank}
        return [by_id[i] for i in self.tree.selection() if i in by_id]

    def pack_cell(self, y):
        if y.pack:
            return "%d (own)" % y.pack
        p = pal.effective_pack(y, self.app.brands)
        return str(p) if p else "cut"

    def refresh(self, select=None):
        keep = set(select) if select is not None else set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        needle = pal.name_key(self.find_var.get())
        shown = 0
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
                                     "retired" if y.retired else ""),
                             tags=("retired",) if y.retired else ())
            shown += 1
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
        r = YarnDialog(self, self.app.bank, self.app.brands).result
        if r:
            y = pal.Yarn(r["name"], r["rgb"], brand=r["brand"], pack=r["pack"])
            self.commit(self.app.bank + [y], select=[iid(y)])

    def edit(self):
        sel = self.selected()
        if len(sel) != 1:
            messagebox.showinfo("Edit yarn", "Select one yarn to edit.", parent=self)
            return
        y = sel[0]
        r = YarnDialog(self, self.app.bank, self.app.brands, yarn=y).result
        if r:
            new = [x.copy() for x in self.app.bank]
            target = new[self.app.bank.index(y)]
            target.sku, target.brand, target.pack = r["name"], r["brand"], r["pack"]
            target.set_rgb(r["rgb"])
            self.commit(new, select=[iid(target)])

    def set_brand(self):
        sel = self.selected()
        if not sel:
            return
        r = BrandChoiceDialog(
            self, self.app.brands, "Set brand",
            "Brand for the %d selected yarn%s:" % (len(sel), "" if len(sel) == 1 else "s"),
            current=sel[0].brand if len({y.key[1] for y in sel}) == 1 else "",
            offer_clear=any(y.pack for y in sel)).result
        if not r:
            return
        ids = {id(y) for y in sel}
        new = []
        for x in self.app.bank:
            c = x.copy()
            if id(x) in ids:
                c.brand = r["brand"]
                if r["clear"]:
                    c.pack = None
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
        self.commit([x.copy() for x in self.app.bank if id(x) not in gone])

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

    def export_csv(self):
        path = filedialog.asksaveasfilename(parent=self, title="Export yarns as CSV",
                                            defaultextension=".csv",
                                            initialfile="%s-yarns.csv" % self._export_stem(),
                                            filetypes=[("CSV", "*.csv")])
        if path:
            self._export(lambda: pal.save_bank(path, self.app.bank, self.app.brands), path,
                         "%d yarns (including retired) and their brands\n(%s)"
                         % (len(self.app.bank), os.path.basename(pal.brands_path(path))))

    def export_gpl(self):
        path = filedialog.asksaveasfilename(parent=self, title="Export yarns as GIMP palette",
                                            defaultextension=".gpl", initialfile="%s.gpl" % self._export_stem(),
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
        self.destroy()


class BrandChoiceDialog(tk.Toplevel):
    """Pick an existing brand or type a new one (with its pack size).
    result = {"brand", "new": bool, "pack": int|None (new brands), "clear": bool} or None."""

    def __init__(self, parent, brands, title, message, current="", offer_clear=False):
        super().__init__(parent)
        self.brands, self.result = brands, None
        self.title(title)
        self.configure(bg=BG, padx=16, pady=14)
        self.resizable(False, False)
        self.transient(parent)
        tk.Label(self, text=message, font=UI_FONT, bg=BG, wraplength=380, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        tk.Label(self, text="Brand", font=UI_FONT, bg=BG).grid(row=1, column=0, sticky="w")
        self.brand_var = tk.StringVar(value=current)
        box = ttk.Combobox(self, textvariable=self.brand_var, width=28,
                           values=[b.name for b in brands])
        box.grid(row=1, column=1, sticky="w", padx=8)
        tk.Label(self, text="Pack size", font=UI_FONT, bg=BG).grid(row=2, column=0, sticky="w",
                                                                   pady=(6, 0))
        self.pack_var = tk.StringVar()
        self.pack_entry = ttk.Entry(self, textvariable=self.pack_var, width=8)
        self.pack_entry.grid(row=2, column=1, sticky="w", padx=8, pady=(6, 0))
        self.hint = tk.Label(self, font=HINT_FONT, bg=BG, fg="#666", wraplength=380,
                             justify="left")
        self.hint.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.clear_var = tk.BooleanVar(value=True)
        if offer_clear:
            ttk.Checkbutton(self, text="Use the brand's pack size (clear their own pack sizes)",
                            variable=self.clear_var).grid(row=4, column=0, columnspan=2,
                                                          sticky="w", pady=(8, 0))
        else:
            self.clear_var.set(False)
        self.error = tk.Label(self, font=UI_FONT, bg=BG, fg="#B00020")
        self.error.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        btns = tk.Frame(self, bg=BG)
        btns.grid(row=6, column=0, columnspan=2, sticky="e", pady=(8, 0))
        self.ok = ttk.Button(btns, text="OK", command=self.accept)
        self.ok.pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda e: self.accept())
        self.bind("<Escape>", lambda e: self.destroy())
        self.brand_var.trace_add("write", lambda *_: self.update_view())
        self.pack_var.trace_add("write", lambda *_: self.update_view())
        self.update_view()
        center_on(self, parent)
        box.focus_set()
        self.grab_set()
        self.wait_window()

    def check(self):
        name = pal.clean_name(self.brand_var.get())
        if not name:
            return None, "Choose or type a brand"
        b = pal.brand_by_key(self.brands, name)
        if b:
            return {"brand": b.name, "new": False, "pack": b.pack,
                    "clear": self.clear_var.get()}, None
        try:
            pack = pal.parse_pack(self.pack_var.get())
        except ValueError:
            return None, "Pack size must be a whole number (or blank)"
        return {"brand": name, "new": True, "pack": pack, "clear": self.clear_var.get()}, None

    def update_view(self):
        b = pal.brand_by_key(self.brands, self.brand_var.get())
        if b:
            self.pack_entry.state(["disabled"])
            self.hint.config(text="Existing brand: %s. Change it under Brands..." % pack_text(b.pack))
        else:
            self.pack_entry.state(["!disabled"])
            self.hint.config(text="New brand. Pack size = pieces per pre-cut pack; leave blank "
                                  "if it's cut from skeins.")
        r, err = self.check()
        self.error.config(text=err if pal.clean_name(self.brand_var.get()) else "")
        self.ok.state(["disabled"] if err else ["!disabled"])

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
                            "you cut it from skeins. Yarns use their brand's pack size unless "
                            "they have their own.", font=HINT_FONT, bg=BG, fg="#555",
                 wraplength=440, justify="left").pack(fill="x", pady=(0, 8))
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("pack", "yarns"), selectmode="browse", height=8)
        for col, text, width, anchor in (("#0", "Brand", 190, "w"), ("pack", "Pack size", 110, "w"),
                                         ("yarns", "Yarns", 60, "e")):
            self.tree.heading(col, text=text, anchor="w" if col != "yarns" else "e")
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "#0"))
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
        for b in self.app.brands:
            n = sum(1 for y in self.app.bank if y.key[1] == b.key)
            self.tree.insert("", "end", iid=b.key, text="  " + b.name,
                             values=(str(b.pack) if b.pack else "cut", n))
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
        tk.Label(self, text="Name", font=UI_FONT, bg=BG).grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=brand.name if brand else "")
        e = ttk.Entry(self, textvariable=self.name_var, width=28)
        e.grid(row=0, column=1, sticky="w", padx=8)
        tk.Label(self, text="Pack size", font=UI_FONT, bg=BG).grid(row=1, column=0, sticky="w",
                                                                   pady=(6, 0))
        self.pack_var = tk.StringVar(value=str(brand.pack) if brand and brand.pack else "")
        ttk.Entry(self, textvariable=self.pack_var, width=8).grid(row=1, column=1, sticky="w",
                                                                 padx=8, pady=(6, 0))
        tk.Label(self, text="Pieces per pre-cut pack. Leave blank if you cut this brand from "
                            "skeins.", font=HINT_FONT, bg=BG, fg="#666", wraplength=320,
                 justify="left").grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.error = tk.Label(self, font=UI_FONT, bg=BG, fg="#B00020")
        self.error.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        btns = tk.Frame(self, bg=BG)
        btns.grid(row=4, column=0, columnspan=2, sticky="e", pady=(8, 0))
        self.ok = ttk.Button(btns, text="Save" if brand else "Add", command=self.accept)
        self.ok.pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda ev: self.accept())
        self.bind("<Escape>", lambda ev: self.destroy())
        self.name_var.trace_add("write", lambda *_: self.update_view())
        self.pack_var.trace_add("write", lambda *_: self.update_view())
        self.update_view()
        center_on(self, parent)
        e.focus_set()
        self.grab_set()
        self.wait_window()

    def check(self):
        name = pal.clean_name(self.name_var.get())
        if not name:
            return None, "Name is empty"
        other = pal.brand_by_key(self.brands, name)
        if other and (self.brand is None or other.key != self.brand.key):
            return None, "%s already exists" % other.name
        try:
            pack = pal.parse_pack(self.pack_var.get())
        except ValueError:
            return None, "Pack size must be a whole number (or blank)"
        return {"name": name, "pack": pack}, None

    def update_view(self):
        _, err = self.check()
        self.error.config(text=err or "")
        self.ok.state(["disabled"] if err else ["!disabled"])

    def accept(self):
        r, err = self.check()
        if not err:
            self.result = r
            self.destroy()


class YarnDialog(tk.Toplevel):
    """Add or edit one yarn. result = {"name", "rgb", "brand", "pack"} or None."""

    def __init__(self, parent, bank, brands, yarn=None):
        super().__init__(parent)
        self.bank, self.brands, self.yarn, self.result = bank, brands, yarn, None
        self.title("Edit yarn" if yarn else "Add yarn")
        self.configure(bg=BG, padx=16, pady=14)
        self.resizable(False, False)
        self.transient(parent)

        form = tk.Frame(self, bg=BG)
        form.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        tk.Label(form, text="Name", font=UI_FONT, bg=BG).grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=yarn.sku if yarn else "")
        name_entry = ttk.Entry(form, textvariable=self.name_var, width=34, font=("Segoe UI", 11))
        name_entry.grid(row=0, column=1, columnspan=3, sticky="w", padx=8)
        tk.Label(form, text="Brand", font=UI_FONT, bg=BG).grid(row=1, column=0, sticky="w",
                                                               pady=(6, 0))
        last = yarn.brand if yarn else (brands[0].name if len(brands) == 1 else "")
        self.brand_var = tk.StringVar(value=last)
        ttk.Combobox(form, textvariable=self.brand_var, width=24,
                     values=[b.name for b in brands]).grid(row=1, column=1, sticky="w", padx=8,
                                                           pady=(6, 0))
        tk.Label(form, text="Pack size", font=UI_FONT, bg=BG).grid(row=1, column=2, sticky="w",
                                                                   padx=(8, 0), pady=(6, 0))
        self.pack_var = tk.StringVar(value=str(yarn.pack) if yarn and yarn.pack else "")
        ttk.Entry(form, textvariable=self.pack_var, width=7).grid(row=1, column=3, sticky="w",
                                                                  padx=8, pady=(6, 0))
        self.pack_hint = tk.Label(form, font=HINT_FONT, bg=BG, fg="#666", anchor="w")
        self.pack_hint.grid(row=2, column=1, columnspan=3, sticky="w", padx=8)

        # Neighbor preview: lighter neighbor | this yarn | darker neighbor, names underneath.
        self.swatch = tk.Canvas(self, width=self.SW_W, height=self.SW_H, bg=BG,
                                highlightthickness=0)
        self.swatch.grid(row=1, column=0, columnspan=2, pady=(0, 8))

        self.hex_var = tk.StringVar(value=yarn.hex if yarn else "")
        self.panel = ColorPanel(self, self.hex_var, editable=True)
        self.panel.grid(row=2, column=0, columnspan=2, sticky="ew")

        self.info = tk.Label(self, font=UI_FONT, bg=BG, justify="left", anchor="w",
                             wraplength=self.SW_W)
        self.info.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.error = tk.Label(self, font=UI_FONT, bg=BG, fg="#B00020", anchor="w")
        self.error.grid(row=4, column=0, columnspan=2, sticky="w", pady=(2, 0))

        btns = tk.Frame(self, bg=BG)
        btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self.ok = ttk.Button(btns, text="Save" if yarn else "Add", command=self.accept)
        self.ok.pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda e: self.accept())
        self.bind("<Escape>", lambda e: self.destroy())

        for v in (self.name_var, self.hex_var, self.brand_var, self.pack_var):
            v.trace_add("write", lambda *_: self.update_view())
        self.update_view()
        center_on(self, parent)
        (self.panel.entry if yarn else name_entry).focus_set()
        self.grab_set()
        self.wait_window()

    SW_W, SW_H, SIDE_W, BLOCK_H = 420, 96, 100, 70

    def problems(self):
        rgb = parse_hex(self.hex_var.get())
        brand = pal.clean_name(self.brand_var.get())
        b = pal.brand_by_key(self.brands, brand)
        if b:
            brand = b.name   # use the brand's own spelling
        name_err = pal.name_problem(self.name_var.get(), brand, self.bank, exclude=self.yarn)
        try:
            pack = pal.parse_pack(self.pack_var.get())
        except ValueError:
            return None, "Pack size must be a whole number (or blank)"
        if name_err:
            return None, name_err
        if rgb is None:
            return None, "Enter a hex color in HTML notation, e.g. #88A048"
        return {"name": pal.clean_name(self.name_var.get()), "rgb": rgb, "brand": brand,
                "pack": pack}, None

    def update_view(self):
        r, err = self.problems()
        rgb = parse_hex(self.hex_var.get())
        b = pal.brand_by_key(self.brands, self.brand_var.get())
        if b:
            self.pack_hint.config(text="blank = brand's pack size (%s)" % pack_text(b.pack))
        elif pal.clean_name(self.brand_var.get()):
            self.pack_hint.config(text="new brand (set its pack size under Brands...)")
        else:
            self.pack_hint.config(text="blank = cut from skein")
        c = self.swatch
        c.delete("all")
        self.panel.show(rgb)
        name = pal.clean_name(self.name_var.get()) or "New yarn"
        mid0, mid1 = self.SIDE_W + 8, self.SW_W - self.SIDE_W - 8
        if rgb:
            y = pal.Yarn("preview", rgb)
            pos, total, lighter, darker = pal.placement(self.bank, y.L, exclude=self.yarn)
            for x0, x1, nb in ((0, self.SIDE_W, lighter),
                               (self.SW_W - self.SIDE_W, self.SW_W, darker)):
                if nb:
                    c.create_rectangle(x0, 8, x1, self.BLOCK_H - 8, fill=nb.hex, outline="#999")
                    c.create_text((x0 + x1) / 2, self.BLOCK_H + 2, text=nb.sku, anchor="n",
                                  width=self.SIDE_W + 4, font=("Segoe UI", 8), fill="#555")
            c.create_rectangle(mid0, 0, mid1, self.BLOCK_H, fill=y.hex, outline="#333", width=2)
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
        self.error.config(text=err or "")
        self.ok.state(["disabled"] if err else ["!disabled"])

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

        self.problems = tk.Label(self, font=UI_FONT, bg=BG, fg="#B00020", anchor="w",
                                 justify="left", wraplength=820)
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
        self.problems.config(text="\n".join(problems[:4]) + (
            "\n... and %d more" % (len(problems) - 4) if len(problems) > 4 else ""))
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
