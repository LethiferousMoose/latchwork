"""Latchwork: match pixel-art colors to latch-hook yarns by lightness (CIE L*, as GIMP shows it).

Stages 1-2: comparison view and palette manager. Run:  python latchwork.py
"""
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import palette as pal
import pattern
import plan as pl
from colormath import gray_for_lightness, nearest_index, parse_hex, rgb_to_lch, to_hex
from palette import load_palette  # noqa: F401  (re-exported for tests and scripts)
from palette_window import PaletteWindow
from project import EXTENSION, MANY_COLORS, Project
from project_panel import ProjectPanel
from widgets import ColorPanel, StatCard, describe_delta_L

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PALETTE = os.path.join(HERE, "palette.csv")
SETTINGS = os.path.join(HERE, "latchwork_settings.json")  # per-user, not in git


def read_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_settings(data):
    try:
        with open(SETTINGS, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass  # remembering is a convenience; never fail over it


def remembered_project():
    path = read_settings().get("project")
    return path if isinstance(path, str) and os.path.isfile(path) else None


def remember_setting(key, value):
    settings = read_settings()
    if value is None:
        settings.pop(key, None)
    else:
        settings[key] = value
    write_settings(settings)


def remembered_palette():
    path = read_settings().get("palette")
    return path if isinstance(path, str) and os.path.isfile(path) else DEFAULT_PALETTE

NEIGHBORS = 4          # yarns shown on each side of the current one in the strip

BG = "#ECECEC"
UI_FONT = ("Segoe UI", 10)
TITLE_FONT = ("Segoe UI", 18, "bold")


def app_icon(size=32):
    """A small yarn ball, drawn in code (no image file)."""
    import math
    img = tk.PhotoImage(width=size, height=size)
    c = (size - 1) / 2.0
    r = size * 0.40
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            dx, dy = x - c, y - c
            d = math.hypot(dx, dy)
            if d > r + 0.5:
                # loose strand trailing off to the bottom right
                on = abs((x - y * 0.35) - size * 0.83) < 1.2 and y > size * 0.62
                row.append("#B0305C" if on else "{}")
                continue
            band = math.sin((dx * 0.8 + dy * 0.6 + 0.05 * d * d) * 0.9)
            shade = 1 - 0.35 * max(0.0, (dx + dy) / (2 * r))
            base = (214, 76, 120) if band > 0.15 else (176, 48, 92)
            if d > r - 0.8:
                base = (120, 30, 60)
            row.append("#%02X%02X%02X" % tuple(int(v * shade) for v in base))
        rows.append("{" + " ".join(row) + "}")
    for y, row in enumerate(rows):
        for x, col in enumerate(row[1:-1].split(" ")):
            if col != "{}":
                img.put(col, to=(x, y, x + 1, y + 1))
    return img


def display_color(rgb, gray):
    if not gray:
        return to_hex(*rgb)
    v = gray_for_lightness(rgb_to_lch(*rgb)[0])
    return to_hex(v, v, v)


class App:
    def __init__(self, root, palette_path, remember=False):
        self.root = root
        self.remember = remember  # save the open palette in settings (off for tests/scripts)
        self.bank = []       # every yarn in the palette file, retired ones included
        self.yarns = []      # active yarns, lightest -> darkest: what matching and stepping use
        self.palette_path = None
        self.palette_window = None
        self.index = 0
        self.target = None  # (r, g, b) or None
        self.gray = False
        self.project = None
        self.selected_hex = None  # the project color being matched, if any

        root.title("Latchwork")
        root.configure(bg=BG)
        root.minsize(1240, 780)
        root.columnconfigure(2, weight=1)
        root.rowconfigure(0, weight=1)
        self.sidebar = ProjectPanel(root, self)
        self.sidebar.grid(row=0, column=0, sticky="ns")
        tk.Frame(root, bg="#C4C4C4", width=1).grid(row=0, column=1, sticky="ns")
        self.main = tk.Frame(root, bg=BG)
        self.main.grid(row=0, column=2, sticky="nsew")
        try:
            self.icon = app_icon()
            root.iconphoto(True, self.icon)
        except tk.TclError:
            pass
        self._build_menu()
        self._build_ui()
        self._bind_keys()
        self.load(palette_path)

    # ---------- layout ----------
    def _build_menu(self):
        bar = tk.Menu(self.root)
        file_menu = tk.Menu(bar, tearoff=False)
        file_menu.add_command(label="New project from image...", accelerator="Ctrl+N",
                              command=self.new_project)
        file_menu.add_command(label="Open project...", accelerator="Ctrl+O",
                              command=self.open_project)
        file_menu.add_command(label="Close project", command=self.close_project)
        file_menu.add_separator()
        file_menu.add_command(label="Export pattern (phone / print)...", accelerator="Ctrl+E",
                              command=self.export_pattern)
        file_menu.add_command(label="Export yarn list...", command=self.export_yarn_list)
        file_menu.add_command(label="Save preview image...", command=self.save_preview)
        file_menu.add_separator()
        file_menu.add_command(label="New palette...", command=self.new_palette)
        file_menu.add_command(label="Open palette...", command=self.open_palette)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.root.destroy)
        bar.add_cascade(label="File", menu=file_menu)
        pal_menu = tk.Menu(bar, tearoff=False)
        pal_menu.add_command(label="Manage yarns...", accelerator="Ctrl+P",
                             command=self.open_palette_window)
        bar.add_cascade(label="Palette", menu=pal_menu)
        self.root.config(menu=bar)
        self.root.bind("<Control-p>", lambda e: self.open_palette_window())
        self.root.bind("<Control-n>", lambda e: self.new_project())
        self.root.bind("<Control-o>", lambda e: self.open_project())
        self.root.bind("<Control-e>", lambda e: self.export_pattern())

    def _build_ui(self):
        r = self.main
        r.columnconfigure(0, weight=1, uniform="half")
        r.columnconfigure(1, weight=1, uniform="half")

        self.target_title = tk.Label(r, text="Target", font=TITLE_FONT, bg=BG, anchor="w")
        self.target_title.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        self.yarn_title = tk.Label(r, text="", font=TITLE_FONT, bg=BG, anchor="w")
        self.yarn_title.grid(row=0, column=1, sticky="ew", padx=16, pady=(12, 0))

        self.swatch = tk.Canvas(r, height=220, bg=BG, highlightthickness=0)
        self.swatch.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=16, pady=6)
        r.rowconfigure(1, weight=1)
        self.swatch.bind("<Configure>", lambda e: self.draw_swatch())
        self.swatch.bind("<Button-1>", lambda e: self.swatch.focus_set())

        self.hex_var = tk.StringVar()
        self.yarn_hex_var = tk.StringVar()
        self.target_panel = ColorPanel(r, self.hex_var, editable=True)
        self.target_panel.grid(row=2, column=0, sticky="n", padx=16, pady=4)
        self.yarn_panel = ColorPanel(r, self.yarn_hex_var, editable=False, on_copy=self.copy_hex)
        self.yarn_panel.grid(row=2, column=1, sticky="n", padx=16, pady=4)
        self.entry = self.target_panel.entry
        self.hex_var.trace_add("write", lambda *_: self.on_hex_changed())

        stats = tk.Frame(r, bg=BG)
        stats.grid(row=3, column=0, columnspan=2, pady=(10, 2))
        self.delta_card = StatCard(stats, "Lightness difference (yarn \u2212 target)", width=260)
        self.delta_card.pack(side="left", padx=6)
        self.pos_card = StatCard(stats, "Position in palette", width=190)
        self.pos_card.pack(side="left", padx=6)

        nav = tk.Frame(r, bg=BG)
        nav.grid(row=4, column=0, columnspan=2, pady=6)
        for text, cmd in (("◀  Lighter", lambda: self.step(-1)),
                          ("Nearest match (N)", self.jump_nearest),
                          ("Darker  ▶", lambda: self.step(1))):
            ttk.Button(nav, text=text, width=18, command=cmd).pack(side="left", padx=4)
        self.gray_btn = ttk.Button(nav, text="Grayscale (G)", width=18, command=self.toggle_gray)
        self.gray_btn.pack(side="left", padx=4)
        self.assign_main = ttk.Button(nav, text="Assign (A)", width=18, command=self.assign)
        self.assign_main.pack(side="left", padx=4)

        self.strip = tk.Canvas(r, height=96, bg=BG, highlightthickness=0)
        self.strip.grid(row=5, column=0, columnspan=2, sticky="ew", padx=16, pady=(6, 0))
        self.strip.bind("<Configure>", lambda e: self.draw_strip())

        tk.Label(r, font=("Segoe UI", 9), bg=BG, fg="#666",
                 text="← → step lighter / darker    N nearest match    G grayscale    "
                      "A assign    P original/preview    Enter/Esc leaves the hex field"
                 ).grid(
            row=6, column=0, columnspan=2, pady=(4, 10))

    def _bind_keys(self):
        # Arrows step even while typing in the hex field (it's a paste-and-go field).
        self.root.bind_all("<Left>", lambda e: self._key(e, lambda: self.step(-1), always=True))
        self.root.bind_all("<Right>", lambda e: self._key(e, lambda: self.step(1), always=True))
        for k in ("n", "N", "<Home>"):
            self.root.bind_all(k, lambda e: self._key(e, self.jump_nearest))
        for k in ("g", "G"):
            self.root.bind_all(k, lambda e: self._key(e, self.toggle_gray))
        for k in ("a", "A"):
            self.root.bind_all(k, lambda e: self._key(e, self.assign))
        for k in ("p", "P"):
            self.root.bind_all(k, lambda e: self._key(e, self.sidebar.toggle_view))
        for k in ("<Return>", "<Escape>"):
            self.entry.bind(k, lambda e: self.swatch.focus_set())

    def _key(self, event, action, always=False):
        widget = event.widget
        if not isinstance(widget, tk.Misc) or widget.winfo_toplevel() is not self.root:
            return None  # keys in other windows (palette manager, dialogs) behave normally
        if not always and isinstance(widget, (tk.Entry, ttk.Entry)):
            return None  # let the letter be typed
        action()
        return "break"

    # ---------- data ----------
    def open_palette(self):
        path = filedialog.askopenfilename(title="Open palette", initialdir=HERE,
                                          filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if path:
            self.load(path)

    def new_palette(self):
        path = filedialog.asksaveasfilename(
            title="New palette (starts empty)", initialdir=HERE, defaultextension=".csv",
            initialfile="new_palette.csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            pal.save_palette(path, [])
        except OSError as e:
            messagebox.showerror("Latchwork", "Could not create %s\n\n%s" % (path, e))
            return
        if self.load(path):
            self.open_palette_window()

    def load(self, path):
        """Load a palette file. Returns True on success."""
        try:
            bank = pal.load_palette(path)
        except (OSError, ValueError, UnicodeDecodeError) as e:
            messagebox.showerror("Latchwork", "Could not load palette:\n%s\n\n%s" % (path, e))
            return False
        self.palette_path = os.path.abspath(path)
        if self.remember:
            settings = read_settings()
            if os.path.normcase(self.palette_path) == os.path.normcase(DEFAULT_PALETTE):
                settings.pop("palette", None)
            else:
                settings["palette"] = self.palette_path
            write_settings(settings)
        self.index = 0
        self._use_bank(bank, keep_sku=None)
        if self.palette_window:
            self.palette_window.refresh()
        return True

    def _use_bank(self, bank, keep_sku):
        self.bank = pal.sort_yarns(bank)
        self.yarns = pal.active(self.bank)
        if self.project and self.project.suggest(self.yarns, self.palette_name):
            self.save_project()
            self.sidebar.refresh_rows()
        self.update_title()
        names = [y.sku for y in self.yarns]
        if keep_sku in names:
            self.index = names.index(keep_sku)
            self.refresh()
        elif self.target:
            self.jump_nearest()
        else:
            self.index = max(0, min(self.index, len(self.yarns) - 1))
            self.refresh()

    def set_bank(self, bank):
        """Save an edited yarn bank to the palette file and show it. Returns True on success."""
        try:
            pal.save_palette(self.palette_path, bank)
        except OSError as e:
            messagebox.showerror("Latchwork", "Could not save %s\n\n%s" % (self.palette_path, e),
                                 parent=self.palette_window or self.root)
            return False
        current = self.yarns[self.index].sku if self.yarns else None
        self._use_bank(bank, keep_sku=current)
        return True

    def open_palette_window(self):
        if self.palette_window:
            self.palette_window.lift()
            self.palette_window.focus_set()
        else:
            self.palette_window = PaletteWindow(self)

    def jump_to_sku(self, sku):
        names = [y.sku for y in self.yarns]
        if sku in names:
            self.jump_to(names.index(sku))

    def update_title(self):
        """Window title: project name first (when open), then the palette in use."""
        n_ret = len(self.bank) - len(self.yarns)
        pal_text = "%s (%d yarns%s)" % (self.palette_name, len(self.yarns),
                                        ", %d retired" % n_ret if n_ret else "")
        parts = ([self.project.name] if self.project else []) + ["Latchwork", pal_text]
        self.root.title("  \u2013  ".join(parts))

    @property
    def palette_name(self):
        return os.path.basename(self.palette_path) if self.palette_path else ""

    def yarn_in_palette(self, y):
        """Is this assignment's yarn (name + hex) among the active yarns of the open palette?"""
        key = pal.name_key(y["name"])
        return any(v.key == key and v.hex == y["hex"].upper() for v in self.yarns)

    # ---------- projects ----------
    def new_project(self):
        img_path = filedialog.askopenfilename(
            title="New project: choose the pixel-art image",
            filetypes=[("Pixel art", "*.png *.gif"), ("PNG", "*.png"), ("GIF", "*.gif"),
                       ("All files", "*.*")])
        if not img_path:
            return
        try:
            project = Project.from_image_file(img_path, "")
        except (OSError, ValueError) as e:
            messagebox.showerror("New project", "Could not use %s\n\n%s" % (img_path, e))
            return
        n = len(project.colors)
        if n > MANY_COLORS and not messagebox.askyesno(
                "New project",
                "This image has %d different colors, which is a lot for pixel art. It may be a "
                "photo, scaled with smoothing, or saved as JPEG at some point.\n\n"
                "Continue anyway?" % n, icon="warning"):
            return
        folder, name = os.path.split(img_path)
        path = filedialog.asksaveasfilename(
            title="Save the new project as", initialdir=folder,
            initialfile=os.path.splitext(name)[0] + EXTENSION, defaultextension=EXTENSION,
            filetypes=[("Latchwork project", "*" + EXTENSION)])
        if not path:
            return
        project.path = path
        project.suggest(self.yarns, self.palette_name)
        if self.save_project(project):
            self.show_project(project)

    def open_project(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(
                title="Open project", filetypes=[("Latchwork project", "*" + EXTENSION),
                                                 ("All files", "*.*")])
            if not path:
                return
        try:
            project = Project.load(path)
        except (OSError, ValueError, KeyError, TypeError) as e:
            messagebox.showerror("Open project", "Could not open %s\n\n%s" % (path, e))
            return False
        if project.suggest(self.yarns, self.palette_name):
            self.save_project(project)
        self.show_project(project)
        return True

    def show_project(self, project):
        self.project = project
        self.sidebar.set_project(project)
        self.update_title()
        if self.remember:
            remember_setting("project", os.path.abspath(project.path))
        first = project.colors[0].hex
        self.sidebar.select(first)
        self.select_project_color(first)

    def close_project(self):
        self.project = None
        self.selected_hex = None
        self.sidebar.show_welcome()
        self.update_title()
        if self.remember:
            remember_setting("project", None)
        self.draw_info()

    def save_project(self, project=None):
        project = project or self.project
        try:
            project.save()
            return True
        except OSError as e:
            messagebox.showerror("Latchwork", "Could not save the project to\n%s\n\n%s"
                                 % (project.path, e))
            return False

    def select_project_color(self, hex_):
        """A color was picked in the project sidebar: make it the target."""
        entry = self.project.entry(hex_)
        if parse_hex(self.hex_var.get()) == entry.rgb:
            self._goto_entry(entry)
        else:
            self.hex_var.set(entry.hex)  # -> on_hex_changed -> _goto_entry

    def _goto_entry(self, entry):
        self.selected_hex = entry.hex
        if entry.confirmed and entry.yarn and self.yarn_in_palette(entry.yarn):
            key = pal.name_key(entry.yarn["name"])
            self.index = next(i for i, y in enumerate(self.yarns) if y.key == key)
            self.refresh()
        else:
            self.jump_nearest()

    def assign(self):
        if not (self.project and self.selected_hex and self.yarns):
            self.root.bell()
            return
        self.project.assign(self.selected_hex, self.yarns[self.index], self.palette_name)
        self.save_project()
        self.sidebar.update_row(self.selected_hex)
        self.draw_info()

    def unassign(self):
        if not (self.project and self.selected_hex):
            return
        self.project.unassign(self.selected_hex)
        self.project.suggest(self.yarns, self.palette_name)
        self.save_project()
        self.sidebar.update_row(self.selected_hex)
        self._goto_entry(self.project.entry(self.selected_hex))

    # ---------- actions ----------
    def on_hex_changed(self):
        text = self.hex_var.get()
        rgb = parse_hex(text)
        if rgb is None:
            self.target_panel.status.config(text="" if not text.strip() else "not a valid hex")
            return
        self.target_panel.status.config(text="")
        self.target = rgb
        entry = self.project.entry(to_hex(*rgb)) if self.project else None
        if entry:
            self.sidebar.select(entry.hex)
            self._goto_entry(entry)
        else:
            if self.project:
                self.sidebar.select(None)
            self.selected_hex = None
            self.jump_nearest()

    def jump_nearest(self):
        if self.target and self.yarns:
            L = rgb_to_lch(*self.target)[0]
            self.index = nearest_index(L, [y.L for y in self.yarns])
        self.refresh()

    def step(self, delta):
        if self.yarns:
            self.index = max(0, min(len(self.yarns) - 1, self.index + delta))
            self.refresh()

    def jump_to(self, i):
        self.index = i
        self.refresh()

    def toggle_gray(self):
        self.gray = not self.gray
        self.gray_btn.config(text="\u2713 Grayscale on (G)" if self.gray else "Grayscale (G)")
        self.refresh()
        self.sidebar.render_image()

    # ---------- exports ----------
    def _need_project(self, what):
        if not self.project:
            messagebox.showinfo("Latchwork", "Open a project first to %s." % what)
            return False
        return True

    def export_yarn_list(self):
        if not self._need_project("export its yarn list"):
            return
        plan = pl.Plan(self.project)
        if not plan.lines and not messagebox.askyesno(
                "Export yarn list", "No colors are assigned yet, so the list will be empty. "
                                    "Export anyway?"):
            return
        folder, _ = os.path.split(os.path.abspath(self.project.path))
        path = filedialog.asksaveasfilename(
            title="Export yarn list", initialdir=folder, defaultextension=".csv",
            initialfile="%s yarn list.csv" % self.project.name, filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            pl.write_yarn_list(plan, path)
        except OSError as e:
            messagebox.showerror("Export yarn list", "Could not write %s\n\n%s" % (path, e))
            return
        messagebox.showinfo("Export yarn list", "Saved %d yarn%s to\n%s" % (
            len(plan.lines), "" if len(plan.lines) == 1 else "s", path))

    def export_pattern(self):
        if not self._need_project("export its pattern"):
            return
        n_un = len(pl.Plan(self.project).unassigned)
        if n_un and not messagebox.askyesno(
                "Export pattern", "%d color%s not assigned to a yarn yet. They'll appear in the "
                "pattern in their original color, marked with ? and listed as unassigned.\n\n"
                "Export anyway?" % (n_un, " is" if n_un == 1 else "s are"), icon="warning"):
            return
        folder, _ = os.path.split(os.path.abspath(self.project.path))
        path = filedialog.asksaveasfilename(
            title="Export pattern for phone / print", initialdir=folder, defaultextension=".html",
            initialfile="%s pattern.html" % self.project.name, filetypes=[("Web page", "*.html")])
        if not path:
            return
        try:
            pattern.export_pattern(self.project, path)
        except (OSError, ValueError) as e:
            messagebox.showerror("Export pattern", "Could not write %s\n\n%s" % (path, e))
            return
        if messagebox.askyesno("Export pattern", "Saved the pattern to\n%s\n\nCopy it to your "
                               "phone and open it in the browser. Open it here now?" % path):
            import webbrowser
            webbrowser.open("file:///" + os.path.abspath(path).replace("\\", "/"))

    def save_preview(self):
        if not self._need_project("save its preview"):
            return
        folder, _ = os.path.split(os.path.abspath(self.project.path))
        path = filedialog.asksaveasfilename(
            title="Save yarn-color preview (1 pixel per knot)", initialdir=folder,
            defaultextension=".png", initialfile="%s preview.png" % self.project.name,
            filetypes=[("PNG", "*.png")])
        if not path:
            return
        try:
            pl.write_preview_png(self.project, path)
        except OSError as e:
            messagebox.showerror("Save preview", "Could not write %s\n\n%s" % (path, e))

    def copy_hex(self):
        if self.yarns:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.yarns[self.index].hex)

    # ---------- drawing ----------
    def refresh(self):
        self.draw_swatch()
        self.draw_strip()
        self.draw_info()

    def draw_swatch(self):
        c = self.swatch
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 4:
            return
        mid = w // 2
        if self.target:
            c.create_rectangle(0, 0, mid, h, fill=display_color(self.target, self.gray), width=0)
        else:
            c.create_rectangle(0, 0, mid, h, fill="#DDDDDD", width=0)
            c.create_text(mid // 2, h // 2, text="Paste a hex color into HTML notation below",
                          font=UI_FONT, fill="#666")
        if self.yarns:
            self.index = max(0, min(self.index, len(self.yarns) - 1))
            yarn = self.yarns[self.index]
            c.create_rectangle(mid, 0, w, h, fill=display_color(yarn.rgb, self.gray), width=0)
        else:
            c.create_rectangle(mid, 0, w, h, fill="#E4E4E4", width=0)
            c.create_text((mid + w) // 2, h // 2, font=UI_FONT, fill="#666", justify="center",
                          text="This palette has no active yarns yet.\n"
                               "Add some in Palette \u2192 Manage yarns... (Ctrl+P)")
        if self.gray:
            c.create_rectangle(8, 8, 104, 30, fill="#2B2B2B", outline="")
            c.create_text(56, 19, text="Grayscale", font=("Segoe UI", 9, "bold"), fill="white")

    def draw_info(self):
        entry = self.project.entry(self.selected_hex) if (self.project and self.selected_hex) \
            else None
        if entry:
            self.target_title.config(text="Target  \u00B7  Count %s" % format(entry.count, ","))
        else:
            self.target_title.config(text="Target")
        if self.project:
            self.sidebar.update_footer()
        can_assign = bool(self.project and self.selected_hex and self.yarns)
        self.assign_main.state(["!disabled"] if can_assign else ["disabled"])
        if not self.yarns:
            self.yarn_title.config(text="No yarns")
            self.yarn_hex_var.set("")
            self.target_panel.show(self.target)
            self.yarn_panel.show(None)
            self.delta_card.set("\u2013", "no yarns in this palette", "#888")
            self.pos_card.set("\u2013", "", "#888")
            return
        yarn = self.yarns[self.index]
        self.yarn_title.config(text=yarn.sku)
        self.yarn_hex_var.set(yarn.hex)
        t_L = rgb_to_lch(*self.target)[0] if self.target else None
        self.target_panel.show(self.target, other_L=yarn.L)
        self.yarn_panel.show(yarn.rgb, other_L=t_L)
        self.pos_card.set("%d of %d" % (self.index + 1, len(self.yarns)),
                          "lightest \u2192 darkest")
        if t_L is None:
            self.delta_card.set("\u2013", "enter a target color", "#888")
        else:
            self.delta_card.set(*describe_delta_L(yarn.L - t_L))

    def draw_strip(self):
        c = self.strip
        c.delete("all")
        w = c.winfo_width()
        if w < 4 or not self.yarns:
            return
        slots = 2 * NEIGHBORS + 1
        sw = w / slots
        for s in range(slots):
            i = self.index - NEIGHBORS + s
            if not 0 <= i < len(self.yarns):
                continue
            y = self.yarns[i]
            x0, x1 = s * sw + 3, (s + 1) * sw - 3
            current = i == self.index
            tag = "slot%d" % i
            c.create_rectangle(x0, 2, x1, 52, fill=display_color(y.rgb, self.gray),
                               outline="#000" if current else "#BBB", width=3 if current else 1,
                               tags=tag)
            c.create_text((x0 + x1) / 2, 58, text=y.sku, width=sw - 6, anchor="n",
                          font=("Segoe UI", 8, "bold" if current else "normal"), tags=tag)
            c.tag_bind(tag, "<Button-1>", lambda e, i=i: self.jump_to(i))


def main():
    root = tk.Tk()
    path = remembered_palette()
    app = App(root, path, remember=True)
    if app.palette_path is None and path != DEFAULT_PALETTE:
        app.load(DEFAULT_PALETTE)  # remembered palette failed to load: fall back
    project = remembered_project()
    if project and not app.open_project(project):
        remember_setting("project", None)
    root.mainloop()


if __name__ == "__main__":
    main()
