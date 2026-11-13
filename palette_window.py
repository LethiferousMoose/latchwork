"""Palette manager window: add, edit, retire/restore, delete, import and export yarns."""
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import palette as pal
from colormath import parse_hex
from widgets import ColorPanel

BG = "#ECECEC"
UI_FONT = ("Segoe UI", 10)


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


class PaletteWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.images = {}
        self.title("Latchwork - Yarn palette")
        self.configure(bg=BG)
        self.minsize(640, 480)
        self.geometry("720x620")

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(head, text="Editing:", font=("Segoe UI", 11), bg=BG, fg="#555").pack(side="left")
        self.file_label = tk.Label(head, font=("Segoe UI", 11, "bold"), bg=BG)
        self.file_label.pack(side="left", padx=(4, 8))
        self.path_label = tk.Label(head, font=("Segoe UI", 8), bg=BG, fg="#888", anchor="w")
        self.path_label.pack(side="left", fill="x", expand=True, pady=(3, 0))

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=12, pady=(8, 6))
        tk.Label(top, text="Find", font=UI_FONT, bg=BG).pack(side="left")
        self.find_var = tk.StringVar()
        self.find_var.trace_add("write", lambda *_: self.refresh())
        ttk.Entry(top, textvariable=self.find_var, width=24).pack(side="left", padx=6)
        self.show_retired = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Show retired", variable=self.show_retired,
                        command=self.refresh).pack(side="left", padx=10)
        self.count = tk.Label(top, font=UI_FONT, bg=BG, fg="#555")
        self.count.pack(side="right")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=12)
        self.tree = ttk.Treeview(body, columns=("hex", "L", "brand", "status"),
                                 selectmode="extended")
        for col, text, width, anchor in (("#0", "Yarn", 200, "w"), ("hex", "Hex", 80, "w"),
                                         ("L", "L", 55, "e"), ("brand", "Brand", 125, "w"),
                                         ("status", "Status", 70, "w")):
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

        buttons = tk.Frame(body, bg=BG)
        buttons.pack(side="left", fill="y", padx=(10, 0))
        self.retire_btn = None
        for text, cmd in (("Add...", self.add), ("Edit...", self.edit), ("Retire", self.retire),
                          ("Delete...", self.delete), (None, None), ("Import...", self.import_),
                          ("Export CSV...", self.export_csv), ("Export GPL...", self.export_gpl)):
            if text is None:
                tk.Frame(buttons, height=16, bg=BG).pack()
                continue
            b = ttk.Button(buttons, text=text, width=14, command=cmd)
            b.pack(pady=2)
            if text == "Retire":
                self.retire_btn = b

        tk.Label(self, font=("Segoe UI", 9), bg=BG, fg="#666", anchor="w", justify="left",
                 text="Changes save to the palette file immediately. Retired yarns are kept but "
                      "not used for matching.\nSelecting a yarn shows it in the main window. "
                      "Double-click to edit.").pack(fill="x", padx=12, pady=(6, 10))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()

    # ---------- list ----------
    def selected(self):
        by_sku = {y.sku: y for y in self.app.bank}
        return [by_sku[i] for i in self.tree.selection() if i in by_sku]

    def refresh(self, select=None):
        keep = set(select) if select is not None else set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        needle = pal.name_key(self.find_var.get())
        shown = 0
        for y in pal.sort_yarns(self.app.bank):
            if y.retired and not self.show_retired.get():
                continue
            if needle and needle not in y.key and needle not in y.hex.lower():
                continue
            img = self.images.get(y.hex)
            if img is None:
                img = self.images[y.hex] = swatch_image([y.hex])
            self.tree.insert("", "end", iid=y.sku, text="  " + y.sku, image=img,
                             values=(y.hex, "%.1f" % y.L, y.brand, "retired" if y.retired else ""),
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
        self.path_label.config(text=os.path.dirname(path))
        self.title("Latchwork - Yarn palette - %s" % os.path.basename(path))
        n_act = len(pal.active(self.app.bank))
        self.count.config(text="%d active, %d retired   (showing %d)" % (
            n_act, len(self.app.bank) - n_act, shown))
        self.on_select()

    def on_select(self):
        sel = self.selected()
        if sel and all(y.retired for y in sel):
            self.retire_btn.config(text="Restore")
        else:
            self.retire_btn.config(text="Retire")
        if len(sel) == 1 and not sel[0].retired:
            self.app.jump_to_sku(sel[0].sku)

    def commit(self, new_bank, select=()):
        if self.app.set_bank(new_bank):
            self.refresh(select=list(select))

    # ---------- actions ----------
    def add(self):
        result = YarnDialog(self, self.app.bank).result
        if result:
            name, rgb = result
            self.commit(self.app.bank + [pal.Yarn(name, rgb)], select=[pal.clean_name(name)])

    def edit(self):
        sel = self.selected()
        if len(sel) != 1:
            messagebox.showinfo("Edit yarn", "Select one yarn to edit.", parent=self)
            return
        y = sel[0]
        result = YarnDialog(self, self.app.bank, yarn=y).result
        if result:
            name, rgb = result
            new = [x.copy() for x in self.app.bank]
            target = new[self.app.bank.index(y)]
            target.sku = pal.clean_name(name)
            target.set_rgb(rgb)
            self.commit(new, select=[target.sku])

    def retire(self):
        sel = self.selected()
        if not sel:
            return
        restore = all(y.retired for y in sel)
        names = {y.sku for y in sel}
        new = [x.copy() for x in self.app.bank]
        for x in new:
            if x.sku in names:
                x.retired = not restore
        self.commit(new, select=names)

    def delete(self):
        sel = self.selected()
        if not sel:
            return
        listing = "\n".join("  " + y.sku for y in sel[:10]) + ("\n  ..." if len(sel) > 10 else "")
        if not messagebox.askyesno(
                "Delete yarns",
                "Permanently delete %d yarn(s)?\n\n%s\n\nDelete is for typos and mistakes. For a "
                "discontinued yarn, use Retire instead." % (len(sel), listing),
                icon="warning", parent=self):
            return
        gone = {id(y) for y in sel}
        self.commit([x.copy() for x in self.app.bank if id(x) not in gone])

    def import_(self):
        path = filedialog.askopenfilename(
            parent=self, title="Import yarns",
            filetypes=[("Palettes", "*.gpl *.csv"), ("GIMP palette", "*.gpl"), ("CSV", "*.csv"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            entries = pal.read_import_file(path)
        except (OSError, ValueError, UnicodeDecodeError) as e:
            messagebox.showerror("Import", "Could not read %s\n\n%s" % (path, e), parent=self)
            return
        if not entries:
            messagebox.showinfo("Import", "No colors found in that file.", parent=self)
            return
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
        self.commit(new, select=[y.sku for y in new if y.key not in before])

    def export_csv(self):
        path = filedialog.asksaveasfilename(parent=self, title="Export yarns as CSV",
                                            defaultextension=".csv", initialfile="yarns.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            self._export(lambda: pal.save_palette(path, self.app.bank), path,
                         "%d yarns (including retired)" % len(self.app.bank))

    def export_gpl(self):
        path = filedialog.asksaveasfilename(parent=self, title="Export yarns as GIMP palette",
                                            defaultextension=".gpl", initialfile="Latchwork.gpl",
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


class YarnDialog(tk.Toplevel):
    """Add or edit one yarn. self.result = (name, rgb) or None."""

    def __init__(self, parent, bank, yarn=None):
        super().__init__(parent)
        self.bank, self.yarn, self.result = bank, yarn, None
        self.title("Edit yarn" if yarn else "Add yarn")
        self.configure(bg=BG, padx=16, pady=14)
        self.resizable(False, False)
        self.transient(parent)

        tk.Label(self, text="Name", font=UI_FONT, bg=BG).grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=yarn.sku if yarn else "")
        name_entry = ttk.Entry(self, textvariable=self.name_var, width=34, font=("Segoe UI", 11))
        name_entry.grid(row=0, column=1, sticky="w", padx=8, pady=(0, 8))

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

        self.name_var.trace_add("write", lambda *_: self.update_view())
        self.hex_var.trace_add("write", lambda *_: self.update_view())
        self.update_view()
        center_on(self, parent)
        (self.panel.entry if yarn else name_entry).focus_set()
        self.grab_set()
        self.wait_window()

    SW_W, SW_H, SIDE_W, BLOCK_H = 420, 96, 100, 70

    def problems(self):
        rgb = parse_hex(self.hex_var.get())
        name_err = pal.name_problem(self.name_var.get(), self.bank, exclude=self.yarn)
        if name_err:
            return rgb, name_err
        if rgb is None:
            return rgb, "Enter a hex color in HTML notation, e.g. #88A048"
        return rgb, None

    def update_view(self):
        rgb, err = self.problems()
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
            where = ("between %s and %s" % (lighter.sku, darker.sku) if lighter and darker else
                     "lightest, before %s" % darker.sku if darker else
                     "darkest, after %s" % lighter.sku if lighter else "the only yarn")
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
        rgb, err = self.problems()
        if err:
            return
        self.result = (pal.clean_name(self.name_var.get()), rgb)
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
        self.geometry("860x560")
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
        tk.Label(self, font=("Segoe UI", 9), bg=BG, fg="#555", anchor="w",
                 text="Swatches: the file's color on the left, your yarn's on the right. Select rows "
                      "and pick an action below. Nothing changes until you press Import.").pack(
            fill="x", pady=(0, 6))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("issue", "file", "mine", "action"),
                                 selectmode="extended")
        for col, text, width in (("#0", "Name in file", 220), ("issue", "What it is", 230),
                                 ("file", "File hex", 75), ("mine", "Your yarn", 150),
                                 ("action", "Action", 230)):
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
                mine = "%s %s%s" % (it.existing.sku, it.existing.hex,
                                    " (retired)" if it.existing.retired else "")
            self.tree.insert("", "end", iid=str(i), text="  " + (it.entry.name or "(no name)"),
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
        taken = {y.key for y in self.bank} | {pal.name_key(it.new_name) for it in self.items
                                              if it.needs_name}
        for it in self.sel_items():
            if action in it.options:
                it.action = action
                if it.needs_name and not it.new_name:
                    if it.kind == pal.PLACEHOLDER:
                        it.new_name = ""
                    else:
                        it.new_name = pal.suggest_name(it.entry.name, taken)
                        taken.add(pal.name_key(it.new_name))
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
