"""Shared yarn list: the yarns several projects need together, to buy for them at once."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import plan as pl
from .widgets import (BG, SMALL_FONT, UI_FONT, FitColumn, ProjectList, TreeSort, free_name,
                      names, swatch_image, vscroll)

HEADING = "Shared yarn list"


class SharedListDialog(tk.Toplevel):
    """Pick projects; see and export the yarns they need together. Each project's count gets
    its own spare %, then the pieces are pooled per yarn (so packs are shared between rugs).
    Nothing in the projects is changed.

    app gives resolve() (pack sizes from the open palette) and the open project, which starts
    in the list."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.shared = pl.SharedPlan([])
        self.images = {}
        self.title(HEADING)
        self.configure(bg=BG, padx=16, pady=14)
        self.minsize(600, 440)
        self.geometry("720x600")
        self.transient(parent)

        tk.Label(self, bg=BG, font=UI_FONT, justify="left", anchor="w",
                 text="The yarns these projects need together. Each project's own spare % is "
                      "added, then the pieces are pooled, so a pack can go to more than one rug.",
                 wraplength=680).pack(fill="x")
        open_path = app.project.path if app.project else None
        self.projects = ProjectList(
            self, [("assigned", "Assigned", 90), ("spare", "Spare", 70)], self._project_values,
            self.rebuild, HEADING, "Add which projects?",
            initialdir=os.path.dirname(open_path) if open_path else None)
        self.projects.pack(fill="x", pady=(10, 0))
        self.projects.tree.tag_configure("attention", background="#FFF4CC")

        # bottom up, so the table takes whatever height is left
        self.btns = tk.Frame(self, bg=BG)
        self.btns.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Button(self.btns, text="Close", command=self.destroy).pack(side="right")
        self.export_button = ttk.Button(self.btns, text="Export CSV...", command=self.export)
        self.export_button.pack(side="right", padx=4)
        self.export_button.lower()   # Tab reaches Export before Close, as they read
        # one line each (width=1: long text is cut rather than widening the window)
        self.details = tk.Label(self, bg=BG, font=SMALL_FONT, fg="#555", anchor="w", width=1)
        self.details.pack(side="bottom", fill="x")
        self.summary = tk.Label(self, bg=BG, font=("Segoe UI", 10, "bold"), anchor="w", width=1)
        self.summary.pack(side="bottom", fill="x", pady=(8, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, pady=(10, 0))
        self.tree = ttk.Treeview(body, columns=("used", "pieces", "need"), selectmode="browse")
        for col, text, width, stretch, anchor in (
                ("#0", "Yarn", 240, True, "w"), ("used", "Used in", 200, True, "w"),
                ("pieces", "Pieces", 80, False, "center"), ("need", "Need", 110, False, "w")):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, minwidth=60, stretch=stretch, anchor=anchor)
        vscroll(body, self.tree)
        line = lambda i: self.shared.lines[int(i)]
        # many projects: "Used in" is cut with "...", and the hover lists them all
        self.used = FitColumn(self.tree, "used", tip=lambda i: (
            "Used in", [([], self.shared.names[k]) for k in sorted(line(i).per)]))
        self.sort = TreeSort(self.tree, {
            "#0": (lambda i: line(i).label.lower(), False),
            "used": (lambda i: len(line(i).per), True),
            "pieces": (lambda i: line(i).pieces, True),
            "need": (lambda i: (line(i).pack is None, -(line(i).need()[1] or 0),
                                -line(i).pieces), False),
        }, default=int)
        for w in (self.projects, body, self.btns):   # Tab goes top to bottom, as laid out
            w.lift()

        self.bind("<Escape>", lambda e: self.destroy())
        if app.project and open_path:
            self.projects.add_path(open_path, quiet=True, project=app.project)
        self.projects.refresh()
        self.rebuild()
        self.update_idletasks()
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 60, parent.winfo_rooty() + 60))
        self.grab_set()
        (self.tree if self.projects.sources else self.projects.tree).focus_set()
        self.wait_window()

    @staticmethod
    def _project_values(project):
        n = len(project.colors)
        spare = float(project.settings.get("spare_percent", 0) or 0)
        return ("%d of %d" % (sum(1 for c in project.colors if c.confirmed), n), "%g%%" % spare)

    def rebuild(self):
        sources = self.projects.sources
        self.shared = pl.SharedPlan([(name, pl.Plan(p, self.app.resolve))
                                     for _, name, p, _ in sources])
        for (path, _, _, _), plan in zip(sources, self.shared.plans):
            self.projects.tree.item(path, tags=["attention"] if plan.unassigned else [])
        self.tree.delete(*self.tree.get_children())
        for i, l in enumerate(self.shared.lines):
            if l.hex not in self.images:
                self.images[l.hex] = swatch_image([l.hex], w=24)
            used = [self.shared.names[k] for k in sorted(l.per)]
            self.tree.insert("", "end", iid=str(i), text="  " + l.label, image=self.images[l.hex],
                             values=("", format(l.pieces, ","), l.need()[2]))
            self.used.set(str(i), ", ".join(used))
        self.sort.apply()
        self.update_view()

    def update_view(self):
        s = self.shared
        if not s.plans:
            self.summary.config(text="Add the projects to buy yarn for.")
            self.details.config(text="")
        else:
            parts = []
            if s.total_packs:
                parts.append("%d pack%s" % (s.total_packs, "" if s.total_packs == 1 else "s"))
            if s.total_pieces_to_cut:
                parts.append("%s pieces to cut" % format(s.total_pieces_to_cut, ","))
            self.summary.config(text="%d yarn%s for %d project%s%s" % (
                len(s.lines), "" if len(s.lines) == 1 else "s", len(s.plans),
                "" if len(s.plans) == 1 else "s",
                (": " + " and ".join(parts) + ".") if parts else "."))
            missing = s.unassigned
            self.details.config(text="Not counted: %s." % names(
                "%d unassigned color%s in %s" % (n, "" if n == 1 else "s", name)
                for name, n in missing) if missing else "")
        self.export_button.state(["!disabled"] if s.lines else ["disabled"])

    def export(self):
        if not self.shared.lines:
            return
        folder = os.path.dirname(os.path.abspath(self.projects.sources[0][0]))
        path = filedialog.asksaveasfilename(
            parent=self, title="Export shared yarn list", initialdir=folder,
            defaultextension=".csv", initialfile=free_name(folder, "shared-yarns.csv"),
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            pl.write_shared_list(self.shared, path)
        except (OSError, ValueError) as e:
            messagebox.showerror(HEADING, "Could not write %s\n\n%s" % (path, e), parent=self)
            return
        n = len(self.shared.lines)
        messagebox.showinfo(HEADING, "Saved %d yarn%s for %d project%s to\n%s" % (
            n, "" if n == 1 else "s", len(self.shared.plans),
            "" if len(self.shared.plans) == 1 else "s", path), parent=self)
