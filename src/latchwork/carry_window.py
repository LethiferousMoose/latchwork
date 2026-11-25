"""Carry over assignments: give a project the yarns earlier projects used for the same hex."""
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from .palette import label as yarn_label
from .project import EXTENSION, Project
from .widgets import BG, SMALL_FONT, UI_FONT, swatch_image, value_tip

CONFLICT_ROWS = 6   # conflict rows shown before the list scrolls


def _names(items, most=4):
    """'a', 'a and b', 'a, b and c', 'a, b, c, d and 2 more'."""
    items = list(items)
    if len(items) > most:
        return "%s and %d more" % (", ".join(items[:most]), len(items) - most)
    return " and ".join(filter(None, [", ".join(items[:-1]), items[-1] if items else ""]))


class CarryDialog(tk.Toplevel):
    """result: [(hex, yarn snapshot, source name)] to carry over, or None (skipped/cancelled).

    app gives yarn_in_palette(); initial: project paths to start with."""

    def __init__(self, parent, app, project, initial=(), skip_text="Cancel"):
        super().__init__(parent)
        self.app, self.project = app, project
        self.result = None
        self.sources = []          # [(path, name, Project)], newest first
        self.choice = {}           # hex -> StringVar holding the chosen option's index
        self.options = {}
        self.images = []
        self.title("Carry over assignments")
        self.configure(bg=BG, padx=16, pady=14)
        self.resizable(False, False)
        self.transient(parent)

        tk.Label(self, bg=BG, font=UI_FONT, justify="left", wraplength=520, anchor="w",
                 text="Colors with exactly the same hex as an assigned color in these projects get "
                      "the same yarn. Other colors are matched as usual.").pack(fill="x")
        src = tk.Frame(self, bg=BG)
        src.pack(fill="x", pady=(10, 0))
        self.listbox = tk.Listbox(src, height=4, width=52, font=UI_FONT, activestyle="none",
                                  exportselection=False)
        self.listbox.pack(side="left", fill="x", expand=True)
        side = tk.Frame(src, bg=BG)
        side.pack(side="left", anchor="n", padx=(8, 0))
        ttk.Button(side, text="Add project...", width=14, command=self.add).pack(pady=(0, 4))
        ttk.Button(side, text="Remove", width=14, command=self.remove).pack()

        # Everything below has a fixed size, so the dialog and its buttons stay put as
        # projects are added: two lines each for the summary and details, and room for the
        # conflict and missing-yarn sections even while they're empty.
        bold, small = tkfont.Font(font=("Segoe UI", 10, "bold")), tkfont.Font(font=SMALL_FONT)
        text = tk.Frame(self, bg=BG, height=2 * bold.metrics("linespace")
                        + 2 * small.metrics("linespace") + 4)
        text.pack(fill="x", pady=(10, 0))
        text.pack_propagate(False)
        self.summary = tk.Label(text, bg=BG, font=("Segoe UI", 10, "bold"), justify="left",
                                anchor="w", wraplength=520)
        self.summary.pack(fill="x")
        self.details = tk.Label(text, bg=BG, font=SMALL_FONT, fg="#555", justify="left", anchor="w",
                                wraplength=520)
        self.details.pack(fill="x")
        self.area = tk.Frame(self, bg=BG, width=520)
        self.area.pack(fill="x")
        self.area.pack_propagate(False)

        # conflicts: the same hex got different yarns in different projects
        self.conflict_box = tk.Frame(self.area, bg=BG)
        tk.Label(self.conflict_box, bg=BG, font=UI_FONT, anchor="w", justify="left",
                 wraplength=520, text="Different yarns for the same color. The newest project is "
                                      "picked; choose another if you like:").pack(fill="x")
        wrap = tk.Frame(self.conflict_box, bg=BG)
        wrap.pack(fill="x", pady=(4, 0))
        self.conflict_canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, width=520)
        self.conflict_canvas.pack(side="left", fill="x", expand=True)
        self.conflict_scroll = ttk.Scrollbar(wrap, orient="vertical",
                                             command=self.conflict_canvas.yview)
        self.conflict_canvas.configure(yscrollcommand=self.conflict_scroll.set)
        self.conflict_rows = tk.Frame(self.conflict_canvas, bg=BG)
        self.conflict_canvas.create_window(0, 0, window=self.conflict_rows, anchor="nw")

        # yarns that aren't in the active palette
        self.missing_box = tk.Frame(self.area, bg=BG)
        # three lines: up to four yarn names with brands, then "and N more"
        self.missing_text = tk.Label(self.missing_box, bg=BG, font=UI_FONT, anchor="nw",
                                     justify="left", wraplength=520, height=3)
        self.missing_text.pack(fill="x")
        self.keep_missing = tk.BooleanVar(value=True)
        for value, text in ((True, "Keep them (assigned, as in the earlier project)"),
                            (False, "Leave those colors to be matched from the active palette")):
            ttk.Radiobutton(self.missing_box, text=text, value=value, variable=self.keep_missing,
                            command=self.update_view).pack(anchor="w", padx=(8, 0))

        self.btns = tk.Frame(self, bg=BG)
        self.btns.pack(fill="x", pady=(12, 0))
        ttk.Button(self.btns, text=skip_text, command=self.destroy).pack(side="right")
        self.ok = ttk.Button(self.btns, text="Carry over", command=self.accept)
        self.ok.pack(side="right", padx=4)
        self.ok.lower()   # Tab reaches Carry over before Skip/Cancel, as they read
        self.bind("<Return>", lambda e: self.accept())
        self.bind("<Escape>", lambda e: self.destroy())

        self.area.configure(height=self._area_height())
        for path in initial:
            self._add_path(path, quiet=True)
        self.rebuild()
        self.update_idletasks()
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 60, parent.winfo_rooty() + 80))
        self.grab_set()
        self.focus_set()
        self.wait_window()

    def _area_height(self):
        """Room for the most conflict rows shown at once plus the missing-yarn section."""
        probe = ttk.Combobox(self.conflict_rows, state="readonly", width=46)
        probe.grid(row=0, column=2, pady=2)
        self.update_idletasks()
        row_h = probe.winfo_reqheight() + 4
        probe.destroy()
        heading = self.conflict_box.winfo_children()[0].winfo_reqheight()
        return (10 + heading + 4 + CONFLICT_ROWS * row_h
                + 10 + self.missing_box.winfo_reqheight())

    # ---------- sources ----------
    def _add_path(self, path, quiet=False):
        norm = os.path.normcase(os.path.abspath(path))
        if self.project.path and norm == os.path.normcase(os.path.abspath(self.project.path)):
            if not quiet:
                messagebox.showinfo("Carry over", "That's the project itself.", parent=self)
            return
        if any(os.path.normcase(os.path.abspath(p)) == norm for p, _, _, _ in self.sources):
            return
        try:
            src = Project.load(path)
            mtime = os.path.getmtime(path)
        except (OSError, ValueError, KeyError, TypeError) as e:
            if not quiet:
                messagebox.showerror("Carry over", "Could not open %s\n\n%s" % (path, e),
                                     parent=self)
            return
        self.sources.append((path, src.name, src, mtime))

    def add(self):
        paths = filedialog.askopenfilenames(
            parent=self, title="Carry over from which projects?",
            initialdir=os.path.dirname(self.project.path or "") or None,
            filetypes=[("Latchwork project", "*" + EXTENSION), ("All files", "*.*")])
        for path in paths:
            self._add_path(path)
        self.rebuild()

    def remove(self):
        sel = self.listbox.curselection()
        if sel:
            del self.sources[sel[0]]
            self.rebuild()

    # ---------- view ----------
    def rebuild(self):
        """Sources changed: recompute the options and the conflict rows."""
        self.sources.sort(key=lambda s: -s[3])    # newest (last saved) first
        self.listbox.delete(0, "end")
        for _, name, src, _ in self.sources:
            n = sum(1 for c in src.colors if c.confirmed)
            self.listbox.insert("end", "%s   (%d assigned)" % (name, n))
        self.options = self.project.carry_options([(n, s) for _, n, s, _ in self.sources])
        old = {h: v.get() for h, v in self.choice.items()}
        self.choice = {}
        for w in self.conflict_rows.winfo_children():
            w.destroy()
        self.images = []
        conflicts = [h for h, opts in self.options.items() if len(opts) > 1]
        for row, hex_ in enumerate(conflicts):
            opts = self.options[hex_]
            img = swatch_image([hex_], w=18, h=14)
            self.images.append(img)
            tk.Label(self.conflict_rows, image=img, bg=BG).grid(row=row, column=0, padx=(0, 6),
                                                                pady=2)
            tk.Label(self.conflict_rows, text=hex_, font=UI_FONT, bg=BG).grid(
                row=row, column=1, sticky="w", padx=(0, 8))
            labels = ["%s  –  %s" % (yarn_label(y["name"], y.get("brand")), name)
                      for name, y in opts]
            var = tk.StringVar()
            keep = old.get(hex_)
            var.set(keep if keep in labels else labels[0])
            box = ttk.Combobox(self.conflict_rows, textvariable=var, values=labels,
                               state="readonly", width=46)
            box.grid(row=row, column=2, sticky="w")
            value_tip(box)
            box.bind("<<ComboboxSelected>>", lambda e: self.update_view())
            self.choice[hex_] = var
        if conflicts:
            self.conflict_rows.update_idletasks()
            row_h = self.conflict_rows.winfo_reqheight() / len(conflicts)
            shown = min(len(conflicts), CONFLICT_ROWS)
            self.conflict_canvas.configure(height=int(row_h * shown),
                                           scrollregion=(0, 0, 0,
                                                         self.conflict_rows.winfo_reqheight()))
            if len(conflicts) > CONFLICT_ROWS:
                self.conflict_scroll.pack(side="left", fill="y")
            else:
                self.conflict_scroll.pack_forget()
            if self.missing_box.winfo_manager():
                self.conflict_box.pack(fill="x", pady=(10, 0), before=self.missing_box)
            else:
                self.conflict_box.pack(fill="x", pady=(10, 0))
        else:
            self.conflict_box.pack_forget()
        self.update_view()

    def chosen(self):
        """[(hex, yarn, source name)] after conflict choices, before the palette check."""
        out = []
        for hex_, opts in self.options.items():
            i = 0
            if hex_ in self.choice:
                labels = ["%s  –  %s" % (yarn_label(y["name"], y.get("brand")), name)
                          for name, y in opts]
                text = self.choice[hex_].get()
                i = labels.index(text) if text in labels else 0
            name, y = opts[i]
            out.append((hex_, y, name))
        return out

    def update_view(self):
        p = self.project
        total = len(p.colors)
        already = sum(1 for c in p.colors if c.confirmed)
        picks = self.chosen()
        missing = [(h, y, n) for h, y, n in picks if not self.app.yarn_in_palette(y)]
        if missing:
            names = sorted({yarn_label(y["name"], y.get("brand")) for _, y, _ in missing})
            self.missing_text.config(text="%d carried-over yarn%s %s in the active palette: %s."
                                     % (len(names), "" if len(names) == 1 else "s",
                                        "isn't" if len(names) == 1 else "aren't", _names(names)))
            self.missing_box.pack(fill="x", pady=(10, 0))
        else:
            self.missing_box.pack_forget()
        if not self.sources:
            self.summary.config(text="Add one or more earlier projects.")
            self.details.config(text="")
            self.ok.state(["disabled"])
            return
        if missing and not self.keep_missing.get():
            drop = {h for h, _, _ in missing}
            picks = [t for t in picks if t[0] not in drop]
        self.final = picks
        from_names = _names(n for _, n, _, _ in self.sources)
        new = total - already - len(self.options)
        self.summary.config(text="%d of %d colors carried over from %s, %d new." % (
            len(picks), total, from_names, new))
        parts = []
        if already:
            parts.append("%d already assigned here, left as they are" % already)
        conflicts = sum(1 for o in self.options.values() if len(o) > 1)
        if conflicts:
            parts.append("%d with different yarns in different projects" % conflicts)
        if missing and not self.keep_missing.get():
            parts.append("%d left to be matched (yarn not in the active palette)" % len(missing))
        self.details.config(text="; ".join(parts) + ("." if parts else ""))
        self.ok.state(["!disabled"] if picks else ["disabled"])

    def accept(self):
        if self.sources and getattr(self, "final", None):
            self.result = self.final
            self.destroy()
