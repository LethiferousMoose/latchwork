"""Latchwork: match pixel-art colors to latch-hook yarns by lightness (CIE L*, as GIMP shows it).

Stages 1-2: comparison view and palette manager. Run:  python latchwork.py
"""
import json
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from . import palette as pal
from . import pattern
from . import plan as pl
from .colormath import (DEFAULT_COLOR_WEIGHT, gray_for_lightness, match_order, parse_hex,
                       rgb_to_lab, rgb_to_lch, to_hex)
from .carry_window import CarryDialog
from .help import TOPICS as help_topics, open_help
from .palette_window import PaletteWindow
from .project import EXTENSION, MANY_COLORS, Project
from .project_panel import ProjectPanel
from .widgets import ColorPanel, StatCard, Tooltip, describe_delta_L

# src/latchwork/app.py -> the repository folder
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
DEFAULT_PALETTE = os.path.join(DATA_DIR, "palette.csv")
SETTINGS = os.path.join(ROOT, "settings", "latchwork_settings.json")  # per-user, not in git
OLD_SETTINGS = os.path.join(ROOT, "latchwork_settings.json")          # before the data/ move


def _migrate_settings():
    """Move settings from the old repo-root location (before data/ and settings/ existed) and
    point the old root palette.csv at data/palette.csv."""
    if os.path.exists(SETTINGS) or not os.path.exists(OLD_SETTINGS):
        return
    try:
        with open(OLD_SETTINGS, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    old = os.path.normcase(os.path.join(ROOT, "palette.csv"))

    def fix(q):
        return DEFAULT_PALETTE if isinstance(q, str) and os.path.normcase(q) == old else q
    if isinstance(data, dict):
        if "palette" in data:
            data["palette"] = fix(data["palette"])
        if isinstance(data.get("palettes"), list):
            data["palettes"] = [fix(q) for q in data["palettes"]]
        write_settings(data)
        if os.path.exists(SETTINGS):
            os.remove(OLD_SETTINGS)


def read_settings():
    _migrate_settings()
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_settings(data):
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
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


def remembered_palettes():
    """The palette list from settings (existing files only)."""
    paths = read_settings().get("palettes")
    if not isinstance(paths, list):
        return []
    return [q for q in paths if isinstance(q, str) and os.path.isfile(q)]


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


def keycap(parent, key):
    """A small bordered key label, like a keyboard key."""
    arrow = key in "←→↑↓"
    return tk.Label(parent, text=key, font=("Segoe UI Symbol", 9) if arrow else ("Segoe UI", 8, "bold"),
                    bg="white", fg="#333", relief="solid", bd=1, padx=3, pady=0,
                    width=2 if len(key) == 1 else 0, highlightthickness=0)


def display_color(rgb, gray):
    if not gray:
        return to_hex(*rgb)
    v = gray_for_lightness(rgb_to_lch(*rgb)[0])
    return to_hex(v, v, v)


class App:
    def __init__(self, root, palette_path, remember=False):
        self.root = root
        self.remember = remember  # save the open palette in settings (off for tests/scripts)
        # Palettes I've opened, for quick switching (paths), and loaded ones kept in memory:
        # normcase(path) -> (file mtime, bank, brands). Reloaded only if the file changed.
        self.palette_list = remembered_palettes() if remember else []
        self._palette_cache = {}
        self.bank = []       # every yarn in the palette file, retired ones included
        self.brands = []     # the palette's brand list (name, pack size)
        self.yarns = []      # active yarns, lightest -> darkest: what matching and stepping use
        self.palette_path = None
        self.palette_window = None
        self.index = 0
        self.target = None  # (r, g, b) or None
        self.gray = False
        self.project = None
        self.selected_hex = None  # the project color being matched, if any

        try:
            self.weight = min(1.0, max(0.0, float(read_settings().get("color_weight",
                                                                      DEFAULT_COLOR_WEIGHT))))
        except (TypeError, ValueError):
            self.weight = DEFAULT_COLOR_WEIGHT
        self._order = None   # cached best-first order for (target, yarn list, weight)
        self._cycle = 0      # position in that order that N last jumped to
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
        file_menu.add_command(label="Carry over assignments...", command=self.carry_over)
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
        self.pal_menu = tk.Menu(bar, tearoff=False)
        bar.add_cascade(label="Palette", menu=self.pal_menu)
        help_menu = tk.Menu(bar, tearoff=False)
        for i, (topic, _) in enumerate(help_topics):
            help_menu.add_command(label=topic, accelerator="F1" if i == 0 else "",
                                  command=lambda t=topic: open_help(self.root, t))
        bar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=bar)
        self.root.bind("<F1>", lambda e: open_help(self.root))
        self.root.bind("<Control-p>", lambda e: self.open_palette_window())
        for n in range(1, 10):
            self.root.bind("<Control-Key-%d>" % n, lambda e, n=n: self.switch_palette(n - 1))
        self.root.bind("<Control-n>", lambda e: self.new_project())
        self.root.bind("<Control-o>", lambda e: self.open_project())
        self.root.bind("<Control-e>", lambda e: self.export_pattern())

    def _build_ui(self):
        bar = tk.Frame(self.main, bg=BG)
        bar.pack(side="top", fill="x", padx=16, pady=(10, 0))
        tk.Label(bar, text="Palette", font=UI_FONT, bg=BG, fg="#555").pack(side="left")
        self.palette_button = ttk.Menubutton(bar, text="", width=26)
        self.palette_button.pack(side="left", padx=(6, 8))
        self.palette_dropdown = tk.Menu(self.palette_button, tearoff=False)
        self.palette_button["menu"] = self.palette_dropdown
        self.palette_info = tk.Label(bar, font=("Segoe UI", 9), bg=BG, fg="#777")
        self.palette_info.pack(side="left")
        manage = tk.Label(bar, text="Manage yarns…", font=("Segoe UI", 9, "underline"),
                          bg=BG, fg="#1565C0", cursor="hand2")
        manage.pack(side="left", padx=(10, 0))
        manage.bind("<Button-1>", lambda e: self.open_palette_window())

        r = tk.Frame(self.main, bg=BG)
        r.pack(side="top", fill="both", expand=True)
        r.columnconfigure(0, weight=1, uniform="half")
        r.columnconfigure(1, weight=1, uniform="half")

        self.target_title = tk.Label(r, text="Target", font=TITLE_FONT, bg=BG, anchor="w")
        self.target_title.grid(row=0, column=0, sticky="ew", padx=16, pady=(6, 0))
        # width=1: a long name never widens its column; it's cut with "..." to fit instead,
        # and the full name shows on hover
        self.yarn_title = tk.Label(r, text="", font=TITLE_FONT, bg=BG, anchor="w", width=1)
        self.yarn_title.grid(row=0, column=1, sticky="ew", padx=16, pady=(6, 0))
        self._title_font = tkfont.Font(font=TITLE_FONT)
        self._title_text, self._title_cut = "", False
        self.yarn_title.bind("<Configure>", lambda e: self._fit_yarn_title())
        Tooltip(self.yarn_title, lambda e: (self._title_text, []) if self._title_cut else None)

        self.swatch = tk.Canvas(r, height=220, bg=BG, highlightthickness=0)
        self.swatch.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=16, pady=6)
        r.rowconfigure(1, weight=1)
        self.swatch.bind("<Configure>", lambda e: self.draw_swatch())
        self.swatch.bind("<Button-1>", lambda e: self.swatch.focus_set())

        self.hex_var = tk.StringVar()
        self.yarn_hex_var = tk.StringVar()
        self.target_panel = ColorPanel(r, self.hex_var, editable=True)
        self.target_panel.grid(row=2, column=0, sticky="n", padx=16, pady=4)
        self.yarn_panel = ColorPanel(r, self.yarn_hex_var, editable=True, on_copy=self.copy_hex)
        self.yarn_entry = self.yarn_panel.entry
        self.yarn_hex_var.trace_add("write", lambda *_: self.on_yarn_hex_changed())
        self.yarn_entry.bind("<FocusOut>", lambda e: self.reset_yarn_hex())
        self.yarn_panel.grid(row=2, column=1, sticky="n", padx=16, pady=4)
        self.entry = self.target_panel.entry
        self.hex_var.trace_add("write", lambda *_: self.on_hex_changed())

        stats = tk.Frame(r, bg=BG)
        stats.grid(row=3, column=0, columnspan=2, pady=(10, 2))
        self.delta_card = StatCard(stats, "Lightness difference (yarn \u2212 target)", width=260)
        self.delta_card.pack(side="left", padx=6)
        self.pos_card = StatCard(stats, "Position in palette", width=190)
        self.pos_card.pack(side="left", padx=6)
        self.match_card = StatCard(stats, "Match rank", width=150)
        self.match_card.pack(side="left", padx=6)
        wbox = tk.Frame(stats, bg=BG)
        wbox.pack(side="left", padx=(10, 0))
        tk.Label(wbox, text="Color weight", font=UI_FONT, bg=BG).pack(anchor="w")
        self.weight_var = tk.StringVar(value="%g" % self.weight)
        sp = ttk.Spinbox(wbox, from_=0, to=1, increment=0.1, width=5,
                         textvariable=self.weight_var, command=self.on_weight)
        sp.pack(anchor="w", pady=2)
        sp.bind("<Return>", lambda e: self.on_weight())
        sp.bind("<FocusOut>", lambda e: self.on_weight())
        tk.Label(wbox, text="0 = lightness only", font=("Segoe UI", 8), bg=BG,
                 fg="#888").pack(anchor="w")

        nav = tk.Frame(r, bg=BG)
        nav.grid(row=4, column=0, columnspan=2, pady=6)
        for text, cmd in (("◀  Lighter", lambda: self.step(-1)),
                          ("Darker  ▶", lambda: self.step(1)),
                          ("▲ Better match", lambda: self.cycle_match(-1)),
                          ("Next match ▼", lambda: self.cycle_match(1))):
            # keys are in the hint bar below, so the buttons stay short and even
            ttk.Button(nav, text=text, width=15, command=cmd).pack(side="left", padx=3)
        self.gray_btn = ttk.Button(nav, text="Grayscale", width=15, command=self.toggle_gray)
        self.gray_btn.pack(side="left", padx=3)
        self.assign_main = ttk.Button(nav, text="Assign", width=15, command=self.assign)
        self.assign_main.pack(side="left", padx=3)

        self.strip = tk.Canvas(r, height=96, bg=BG, highlightthickness=0)
        self.strip.grid(row=5, column=0, columnspan=2, sticky="ew", padx=16, pady=(6, 0))
        self.strip.bind("<Configure>", lambda e: self.draw_strip())

        hints = tk.Frame(r, bg=BG)
        hints.grid(row=6, column=0, columnspan=2, padx=16, pady=(4, 10))
        self.hint_rows = [tk.Frame(hints, bg=BG), tk.Frame(hints, bg=BG)]
        self.hint_items = []
        for keys, text in (("←→", "lighter / darker"), ("N", "next match"), ("B", "better match"),
                           ("Home", "best match"), ("G", "grayscale"), ("A", "assign"),
                           ("P", "original/preview"), ("F1", "help")):
            item = tk.Frame(hints, bg=BG)
            self.hint_items.append(item)
            for k in ([keys] if len(keys) > 2 or keys == "F1" else list(keys)):
                keycap(item, k).pack(side="left", padx=(0, 2))
            tk.Label(item, text=text, font=("Segoe UI", 9), bg=BG, fg="#666").pack(
                side="left", padx=(3, 0))
        self._hint_split = None
        r.bind("<Configure>", lambda e: self.layout_hints(e.width), add="+")

    def layout_hints(self, width):
        """One line of key hints when it fits, otherwise two centered lines."""
        gap = 10
        total = sum(i.winfo_reqwidth() + gap for i in self.hint_items)
        split = len(self.hint_items) if total + 32 <= width else (len(self.hint_items) + 1) // 2
        if split == self._hint_split:
            return
        self._hint_split = split
        for row in self.hint_rows:
            row.pack_forget()
        for n, item in enumerate(self.hint_items):
            item.pack_forget()
            item.pack(in_=self.hint_rows[0 if n < split else 1], side="left", padx=(0, gap))
        self.hint_rows[0].pack()
        if split < len(self.hint_items):
            self.hint_rows[1].pack(pady=(3, 0))

    def _bind_keys(self):
        # Arrows step even while typing in the hex field (it's a paste-and-go field).
        self.root.bind_all("<Left>", lambda e: self._key(e, lambda: self.step(-1), always=True))
        self.root.bind_all("<Right>", lambda e: self._key(e, lambda: self.step(1), always=True))
        for k in ("n", "N"):
            self.root.bind_all(k, lambda e: self._key(e, lambda: self.cycle_match(1)))
        for k in ("b", "B"):
            self.root.bind_all(k, lambda e: self._key(e, lambda: self.cycle_match(-1)))
        self.root.bind_all("<Home>", lambda e: self._key(e, self.jump_nearest))
        for k in ("g", "G"):
            self.root.bind_all(k, lambda e: self._key(e, self.toggle_gray))
        for k in ("a", "A"):
            self.root.bind_all(k, lambda e: self._key(e, self.assign))
        for k in ("p", "P"):
            self.root.bind_all(k, lambda e: self._key(e, self.sidebar.toggle_view))
        for k in ("<Return>", "<Escape>"):
            self.entry.bind(k, lambda e: self.swatch.focus_set())
            self.yarn_entry.bind(k, lambda e: self.swatch.focus_set())   # FocusOut resets it

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
        path = filedialog.askopenfilename(title="Open palette", initialdir=DATA_DIR,
                                          filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if path:
            self.load(path)

    def new_palette(self):
        path = filedialog.asksaveasfilename(
            title="New palette (starts empty)", initialdir=DATA_DIR, defaultextension=".csv",
            initialfile="new_palette.csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            pal.save_bank(path, [], [])
        except OSError as e:
            messagebox.showerror("Latchwork", "Could not create %s\n\n%s" % (path, e))
            return
        if self.load(path):
            self.open_palette_window()

    @staticmethod
    def _mtime(path):
        try:
            return (os.path.getmtime(path),
                    os.path.getmtime(pal.brands_path(path)) if os.path.exists(
                        pal.brands_path(path)) else None)
        except OSError:
            return None

    def load(self, path):
        """Make a palette file the active one (from memory when the file hasn't changed) and add
        it to the palette list. Returns True on success."""
        path = os.path.abspath(path)
        key = os.path.normcase(path)
        cached = self._palette_cache.get(key)
        mtime = self._mtime(path)
        if cached and cached[0] == mtime and mtime is not None:
            bank, brands = [y.copy() for y in cached[1]], [b.copy() for b in cached[2]]
        else:
            try:
                bank, brands = pal.load_bank(path)
            except (OSError, ValueError, UnicodeDecodeError) as e:
                messagebox.showerror("Latchwork", "Could not load palette:\n%s\n\n%s" % (path, e))
                return False
            self._palette_cache[key] = (mtime, bank, brands)
            bank, brands = [y.copy() for y in bank], [b.copy() for b in brands]
        self.palette_path = path
        if key not in [os.path.normcase(q) for q in self.palette_list]:
            self.palette_list.append(path)
        self._save_palette_settings()
        self.index = 0
        self._use_bank(bank, keep_key=None, brands=brands)
        if self.palette_window:
            self.palette_window.refresh()
        self.update_palette_menus()
        return True

    def _save_palette_settings(self):
        if not self.remember:
            return
        settings = read_settings()
        if self.palette_path and os.path.normcase(self.palette_path) != os.path.normcase(
                DEFAULT_PALETTE):
            settings["palette"] = self.palette_path
        else:
            settings.pop("palette", None)
        settings["palettes"] = list(self.palette_list)
        write_settings(settings)

    def switch_palette(self, i):
        """Ctrl+1..9 / the dropdown: make palette number i of the list active."""
        if 0 <= i < len(self.palette_list):
            path = self.palette_list[i]
            if self.palette_path and os.path.normcase(path) == os.path.normcase(
                    self.palette_path):
                return
            if not os.path.isfile(path):
                if messagebox.askyesno("Latchwork", "%s no longer exists.\n\nRemove it from the "
                                       "palette list?" % path):
                    self.remove_palette(path)
                return
            self.load(path)

    def remove_palette(self, path=None):
        """Take a palette off the list (the file stays). The active one can't be removed."""
        path = path or self.palette_path
        if self.palette_path and os.path.normcase(path) == os.path.normcase(self.palette_path):
            messagebox.showinfo("Latchwork", "Switch to another palette first; the active "
                                             "palette stays on the list.")
            return
        self.palette_list = [q for q in self.palette_list
                             if os.path.normcase(q) != os.path.normcase(path)]
        self._palette_cache.pop(os.path.normcase(path), None)
        self._save_palette_settings()
        self.update_palette_menus()

    def _palette_labels(self):
        """Short names for the palette list; the folder is added when two files share a name."""
        names = [os.path.basename(q) for q in self.palette_list]
        return ["%s  (%s)" % (n, os.path.basename(os.path.dirname(q))) if names.count(n) > 1
                else n for n, q in zip(names, self.palette_list)]

    def update_palette_menus(self):
        """Rebuild the palette dropdown and the Palette menu from the palette list."""
        active = os.path.normcase(self.palette_path) if self.palette_path else None
        self._palette_choice = tk.IntVar(value=-1)
        labels = self._palette_labels()
        for menu in (self.palette_dropdown, self.pal_menu):
            menu.delete(0, "end")
            for i, (q, label) in enumerate(zip(self.palette_list, labels)):
                if os.path.normcase(q) == active:
                    self._palette_choice.set(i)
                menu.add_radiobutton(label=label, variable=self._palette_choice, value=i,
                                     accelerator="Ctrl+%d" % (i + 1) if i < 9 else "",
                                     command=lambda i=i: self.switch_palette(i))
            menu.add_separator()
            menu.add_command(label="Open palette...", command=self.open_palette)
            menu.add_command(label="New palette...", command=self.new_palette)
            others = [q for q in self.palette_list if os.path.normcase(q) != active]
            if others:
                remove = tk.Menu(menu, tearoff=False)
                for q, label in zip(self.palette_list, labels):
                    if os.path.normcase(q) != active:
                        remove.add_command(label=label,
                                           command=lambda q=q: self.remove_palette(q))
                menu.add_cascade(label="Remove from list", menu=remove)
            menu.add_separator()
            menu.add_command(label="Manage yarns...", accelerator="Ctrl+P",
                             command=self.open_palette_window)
        name = labels[self._palette_choice.get()] if self._palette_choice.get() >= 0 else ""
        self.palette_button.config(text=name)
        n_ret = len(self.bank) - len(self.yarns)
        self.palette_info.config(text="%d yarns%s" % (
            len(self.yarns), ", %d retired" % n_ret if n_ret else ""))

    def _use_bank(self, bank, keep_key, brands=None):
        if brands is not None:
            self.brands = brands
        self.bank = pal.sort_yarns(bank)
        self.yarns = pal.active(self.bank)
        self._order = None
        if self.project:
            if self.project.suggest(self.yarns, self.palette_name, self.brands, self.weight):
                self.save_project()
            self.sidebar.refresh_rows()   # also refreshes the plan (pack sizes may have changed)
        self.update_title()
        keys = [y.key for y in self.yarns]
        if keep_key in keys:
            self.index = keys.index(keep_key)
            self.refresh()
        elif self.target:
            self.jump_nearest()
        else:
            self.index = max(0, min(self.index, len(self.yarns) - 1))
            self.refresh()

    def set_bank(self, bank, brands=None):
        """Save an edited yarn bank (and brand list) and show it. Returns True on success."""
        brands = pal.ensure_brands(self.brands if brands is None else brands, bank)
        try:
            pal.save_bank(self.palette_path, bank, brands)
        except OSError as e:
            messagebox.showerror("Latchwork", "Could not save %s\n\n%s" % (self.palette_path, e),
                                 parent=self.palette_window or self.root)
            return False
        self._palette_cache[os.path.normcase(self.palette_path)] = (
            self._mtime(self.palette_path), [y.copy() for y in bank], [b.copy() for b in brands])
        current = self.yarns[self.index].key if self.yarns else None
        self._use_bank(bank, keep_key=current, brands=brands)
        self.update_palette_menus()
        return True

    def open_palette_window(self):
        if self.palette_window:
            self.palette_window.lift()
            self.palette_window.focus_set()
        else:
            self.palette_window = PaletteWindow(self)

    def jump_to_yarn(self, key):
        keys = [y.key for y in self.yarns]
        if key in keys:
            self.jump_to(keys.index(key))

    def resolve(self, name, brand):
        """(found, pack size) for a project's yarn in the open palette (retired ones count),
        so pack-size changes in the palette apply to projects."""
        key = pal.yarn_key(name, brand)
        y = next((v for v in self.bank if v.key == key), None)
        return (True, pal.effective_pack(y, self.brands)) if y else (False, None)

    @staticmethod
    def assignment_key(y):
        return pal.yarn_key(y["name"], y.get("brand") or "")

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

    def used_yarns(self):
        """{(yarn key, hex): [image hexes]} for colors assigned (or carried over) in this rug,
        leaving out the selected color itself. Suggestions don't count."""
        used = {}
        if self.project:
            for c in self.project.colors:
                if c.confirmed and c.yarn and c.hex != self.selected_hex:
                    k = (self.assignment_key(c.yarn), c.yarn["hex"].upper())
                    used.setdefault(k, []).append(c.hex)
        return used

    def yarn_in_palette(self, y):
        """Is this assignment's yarn (name + brand + hex) among the active yarns of the palette?"""
        key = self.assignment_key(y)
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
        project.settings.update(read_settings().get("canvas_defaults") or {})
        # optional: start from an earlier rug's assignments (the open project is offered first)
        earlier = [self.project.path] if self.project else []
        self._apply_carry(CarryDialog(self.root, self, project, earlier, skip_text="Skip").result,
                          project)
        project.suggest(self.yarns, self.palette_name, self.brands, self.weight)
        if self.save_project(project):
            self.show_project(project)

    def carry_over(self):
        """File menu: carry assignments from earlier projects into the open one."""
        if not self._need_project("carry over assignments"):
            return
        picks = CarryDialog(self.root, self, self.project).result
        if not picks:
            return
        self._apply_carry(picks, self.project)
        self.save_project()
        self.sidebar.refresh_rows()
        self.sidebar.refresh_plan()
        self.sidebar.render_image()
        if self.selected_hex:
            self._goto_entry(self.project.entry(self.selected_hex))

    @staticmethod
    def _apply_carry(picks, project):
        for hex_, yarn, source in picks or ():
            project.carry(hex_, yarn, source)

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
        if project.suggest(self.yarns, self.palette_name, self.brands, self.weight):
            self.save_project(project)
        self.show_project(project)
        return True

    def show_project(self, project):
        self.project = project
        self.sidebar.set_project(project)
        self.update_title()
        if self.remember:
            remember_setting("project", os.path.abspath(project.path))
        first = self.sidebar.tree.get_children()[0]   # top row, in the project's saved sort
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
            key = self.assignment_key(entry.yarn)
            self.index = next(i for i, y in enumerate(self.yarns) if y.key == key)
            self.refresh()
        else:
            self.jump_nearest()

    def set_canvas(self, values, as_default=False):
        """Canvas mesh/borders for the open project (and optionally for new projects)."""
        if not self.project:
            return
        self.project.settings.update(values)
        self.save_project()
        self.sidebar.refresh_plan()
        if as_default and self.remember:
            remember_setting("canvas_defaults", dict(values))

    def assign_state(self):
        """'none' (not assigned), 'this' (assigned to the yarn on screen) or 'other'."""
        if not (self.project and self.selected_hex and self.yarns):
            return None
        entry = self.project.entry(self.selected_hex)
        if not (entry.confirmed and entry.yarn):
            return "none"
        y = self.yarns[self.index]
        same = self.assignment_key(entry.yarn) == y.key and entry.yarn["hex"].upper() == y.hex
        return "this" if same else "other"

    def assign(self):
        """Toggle: assign the yarn on screen, or un-assign if it's already the assigned one."""
        state = self.assign_state()
        if state is None:
            self.root.bell()
            return
        if state == "this":
            self.unassign()
            return
        self.project.assign(self.selected_hex, self.yarns[self.index], self.palette_name,
                            self.brands)
        self.save_project()
        self.sidebar.update_row(self.selected_hex)
        self.refresh()

    def unassign(self):
        if not (self.project and self.selected_hex):
            return
        self.project.unassign(self.selected_hex)
        self.project.suggest(self.yarns, self.palette_name, self.brands, self.weight)
        self.save_project()
        self.sidebar.update_row(self.selected_hex)
        self.refresh()  # stay on the same yarn; the button flips back to "Assign"

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

    def match_ranking(self):
        """Active yarn indexes, best match for the target first (cached)."""
        if not (self.target and self.yarns):
            return []
        key = (self.target, self.weight)
        if not self._order or self._order[0] != key:
            self._order = (key, match_order(rgb_to_lab(*self.target),
                                            [y.lab for y in self.yarns], self.weight))
        return self._order[1]

    def on_yarn_hex_changed(self):
        """Typing a hex in the yarn's box jumps to the active yarn with that hex (first one if
        several share it). Anything else is left until the box loses focus, then reset."""
        rgb = parse_hex(self.yarn_hex_var.get())
        current = self.yarns[self.index] if self.yarns else None
        if rgb is None or (current and current.rgb == rgb):
            self.yarn_panel.status.config(text="")
            return
        i = next((k for k, y in enumerate(self.yarns) if y.rgb == rgb), None)
        if i is None:
            self.yarn_panel.status.config(text="no yarn with this hex")
            return
        self.yarn_panel.status.config(text="")
        self.jump_to(i)

    def reset_yarn_hex(self):
        self.yarn_panel.status.config(text="")
        if self.yarns:
            self.yarn_hex_var.set(self.yarns[self.index].hex)

    def jump_nearest(self):
        """Go to the best match for the target (used whenever the target or palette changes)."""
        order = self.match_ranking()
        self._cycle = 0
        if order:
            self.index = order[0]
        self.refresh()

    def cycle_match(self, delta):
        """N (+1) / B (-1): move down or up the best-match ranking from the yarn on screen.
        After stepping with the arrows, N starts again at the best match. Stops at the ends."""
        order = self.match_ranking()
        if not order:
            return self.refresh()
        if not (self._cycle < len(order) and order[self._cycle] == self.index):
            self._cycle = 0
        else:
            self._cycle = max(0, min(len(order) - 1, self._cycle + delta))
        self.index = order[self._cycle]
        self.refresh()

    def on_weight(self):
        try:
            w = round(min(1.0, max(0.0, float(self.weight_var.get()))), 2)
        except ValueError:
            w = self.weight
        self.weight_var.set("%g" % w)
        if w == self.weight:
            return
        self.weight = w
        remember_setting("color_weight", w)
        if self.project:
            if self.project.suggest(self.yarns, self.palette_name, self.brands, self.weight):
                self.save_project()
            self.sidebar.refresh_rows()
        if self.target:
            self.jump_nearest()

    def step(self, delta):
        if self.yarns:
            self.index = max(0, min(len(self.yarns) - 1, self.index + delta))
            self.refresh()

    def jump_to(self, i):
        self.index = i
        self.refresh()

    def toggle_gray(self):
        self.gray = not self.gray
        self.gray_btn.config(text="\u2713 Grayscale on" if self.gray else "Grayscale")
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
        plan = pl.Plan(self.project, self.resolve)
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
        n_un = len(pl.Plan(self.project, self.resolve).unassigned)
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
            pattern.export_pattern(self.project, path, self.resolve)
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
        self._refresh_live_preview()

    def live_preview(self):
        """(image color, yarn hex) for the Yarn preview: the selected image color shown with the
        yarn currently in the comparison view, or None."""
        if self.project and self.selected_hex and self.yarns and self.project.entry(
                self.selected_hex):
            return self.selected_hex, self.yarns[self.index].hex
        return None

    def _refresh_live_preview(self):
        """Repaint the sidebar preview when the yarn shown for the selected color changes."""
        key = self.live_preview() if self.sidebar.view.get() == "preview" else None
        if key != getattr(self, "_live_key", None):
            self._live_key = key
            self.sidebar.render_image()

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
        if self.yarns:
            others = self.used_yarns().get((yarn.key, yarn.hex), [])
            if others:
                self._draw_used_badge(c, mid + 8, h - 8, others, w - mid - 16)

    def _draw_used_badge(self, c, x, bottom, hexes, room):
        """'Already used for [#87BEEB] [#5A9646] and 2 more' at the bottom-left of the yarn,
        listing as many colors as fit in `room` px."""
        if not hasattr(self, "_badge_font"):
            self._badge_font = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        font = self._badge_font

        def layout(most):   # [(kind, text, x)], right edge
            parts, cx = [], x + 10
            rest = ["and %d more" % (len(hexes) - most)] if len(hexes) > most else []
            for i, text in enumerate(["Already used for"] + hexes[:most] + rest):
                if 0 < i <= most:
                    parts.append(("box", text, cx))
                    cx += 16
                parts.append(("text", text, cx))
                cx += font.measure(text) + (8 if i == 0 else 10)
            return parts, cx

        for most in range(min(3, len(hexes)), -1, -1):
            parts, right = layout(most)
            if right - x <= room:
                break
        y0, y1 = bottom - 24, bottom
        c.create_rectangle(x, y0, right, y1, fill="#2B2B2B", outline="")
        for kind, text, px in parts:
            if kind == "box":
                c.create_rectangle(px, y0 + 6, px + 12, y1 - 6, outline="white",
                                   fill=display_color(parse_hex(text), self.gray))
            else:
                c.create_text(px, (y0 + y1) / 2, text=text, font=font, fill="white",
                              anchor="w")

    def draw_info(self):
        entry = self.project.entry(self.selected_hex) if (self.project and self.selected_hex) \
            else None
        if entry:
            self.target_title.config(text="Target  \u00B7  Count %s" % format(entry.count, ","))
        else:
            self.target_title.config(text="Target")
        if self.project:
            self.sidebar.update_footer()
        state = self.assign_state()
        self.assign_main.state(["!disabled"] if state else ["disabled"])
        self.assign_main.config(text={"this": "\u2713 Assigned",
                                      "other": "Reassign"}.get(state, "Assign"))
        if not self.yarns:
            self.set_yarn_title("No yarns")
            self.yarn_hex_var.set("")
            self.target_panel.show(self.target)
            self.yarn_panel.show(None)
            self.delta_card.set("\u2013", "no yarns in this palette", "#888")
            self.match_card.set("\u2013", "", "#888")
            self.pos_card.set("\u2013", "", "#888")
            return
        yarn = self.yarns[self.index]
        self.set_yarn_title(yarn.label)
        self.yarn_hex_var.set(yarn.hex)
        t_L = rgb_to_lch(*self.target)[0] if self.target else None
        self.target_panel.show(self.target, other=yarn.rgb)
        self.yarn_panel.show(yarn.rgb, other=self.target)
        order = self.match_ranking()
        if order:
            self.match_card.set("#%d" % (order.index(self.index) + 1),
                                "best match" if order[0] == self.index else "B = better")
        else:
            self.match_card.set("\u2013", "", "#888")
        self.pos_card.set("%d of %d" % (self.index + 1, len(self.yarns)),
                          "lightest \u2192 darkest")
        if t_L is None:
            self.delta_card.set("\u2013", "enter a target color", "#888")
        else:
            self.delta_card.set(*describe_delta_L(yarn.L - t_L))

    def set_yarn_title(self, text):
        self._title_text = text
        self._fit_yarn_title()

    def _fit_yarn_title(self):
        """Show the yarn title, cut with '...' when it's wider than its half of the view."""
        text, f = self._title_text, self._title_font
        room = self.yarn_title.winfo_width() - 6
        self._title_cut = room > 20 and f.measure(text) > room
        if self._title_cut:
            lo, hi = 0, len(text)          # longest prefix that fits with the ellipsis
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if f.measure(text[:mid].rstrip() + "\u2026") <= room:
                    lo = mid
                else:
                    hi = mid - 1
            text = text[:lo].rstrip() + "\u2026"
        if self.yarn_title.cget("text") != text:
            self.yarn_title.config(text=text)

    def draw_strip(self):
        c = self.strip
        c.delete("all")
        w = c.winfo_width()
        if w < 4 or not self.yarns:
            return
        slots = 2 * NEIGHBORS + 1
        sw = w / slots
        used = self.used_yarns()
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
            if (y.key, y.hex) in used:   # already assigned to another color of this rug
                c.create_oval(x1 - 15, 6, x1 - 5, 16, fill="#2B2B2B", outline="white",
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
