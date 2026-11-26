"""Latchwork main window: the comparison view (target next to a yarn), menus and keys, and what
ties the project sidebar, palettes and exports together. Run:  python latchwork.py
"""
import os
import re
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from . import palette as pal
from . import pattern
from . import pixelart
from . import plan as pl
from .colormath import (DEFAULT_COLOR_WEIGHT, gray_for_lightness, match_order, parse_hex,
                       rgb_to_lab, rgb_to_lch, to_hex)
from .carry_window import CarryDialog
from .shared_window import SharedListDialog
from .help import TOPICS as help_topics, open_help
from .palette_window import PaletteWindow
from .project import EXTENSION, MANY_COLORS, Project
from .project_panel import ProjectPanel
from .settings import DATA_DIR, DEFAULT_PALETTE, ROOT, read_settings, write_settings
from .widgets import (BG, UI_FONT, ColorPanel, FitText, StatCard, Tooltip,
                      describe_delta_L, free_name)

COMPARE_BAR_W = 140   # channel bars in the comparison at least; they grow with the window



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


def _screen_area(root):
    """(x, y, width, height) of the desktop across all monitors."""
    if sys.platform == "win32":
        try:
            import ctypes
            m = ctypes.windll.user32.GetSystemMetrics
            area = (m(76), m(77), m(78), m(79))   # SM_X/YVIRTUALSCREEN, SM_CX/CYVIRTUALSCREEN
            if area[2] > 0 and area[3] > 0:
                return area
        except (AttributeError, OSError):
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def on_screen(geometry, root):
    """The saved 'WxH+X+Y' if its title bar is still on a screen (a monitor may have been
    unplugged since), else None."""
    m = re.match(r"^(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)$", geometry or "")
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    x, y = (int(g.replace("+-", "-").lstrip("+")) for g in (m.group(3), m.group(4)))
    sx, sy, sw, sh = _screen_area(root)
    if (w < 100 or h < 100 or x + w < sx + 100 or x > sx + sw - 100
            or y < sy - 20 or y > sy + sh - 60):
        return None
    return geometry


RECENT_MAX = 8   # File > Open recent
PALETTE_BUTTON_CHROME = 34   # px of the palette dropdown taken by its padding and arrow


def recent_projects():
    """Projects I opened, most recent first (paths, as saved; missing files included)."""
    settings = read_settings()
    paths = settings.get("recent_projects")
    if not isinstance(paths, list):
        paths = [settings.get("project")]   # before the list existed: the last one
    return [q for q in paths if isinstance(q, str)][:RECENT_MAX]


def remember_recent(path, add=True):
    """Move a project to the top of the recent list (add=False: take it off the list)."""
    key = os.path.normcase(os.path.abspath(path))
    paths = [q for q in recent_projects() if os.path.normcase(os.path.abspath(q)) != key]
    if add:
        paths.insert(0, os.path.abspath(path))
    remember_setting("recent_projects", paths[:RECENT_MAX])


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
        # Assignment history of the open project (this session only): (label, [(hex, before,
        # after)]) per step, each state from Project.state.
        self.undo_stack, self.redo_stack = [], []

        try:
            self.weight = min(1.0, max(0.0, float(read_settings().get("color_weight",
                                                                      DEFAULT_COLOR_WEIGHT))))
        except (TypeError, ValueError):
            self.weight = DEFAULT_COLOR_WEIGHT
        self._live_key = None  # what the sidebar preview last showed live (see live_preview)
        self._order = None   # cached best-first order for (target, yarn list, weight)
        self._cycle = 0      # position in that order that N last jumped to
        root.title("Latchwork")
        root.configure(bg=BG)
        root.minsize(1240, 780)
        self._normal_geometry = None   # the main window's size and place when not maximized
        if remember:
            self._restore_main_window()
        root.bind("<Configure>", self._track_main_window, add="+")
        root.protocol("WM_DELETE_WINDOW", self.quit)
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

    # ---------- window size and place (remembered between sessions) ----------
    def _is_zoomed(self):
        try:
            return self.root.state() == "zoomed"            # Windows, macOS
        except tk.TclError:
            return False

    def _restore_main_window(self):
        saved = read_settings().get("windows", {})
        main = saved.get("main") if isinstance(saved, dict) else None
        if not isinstance(main, dict):
            return
        geometry = on_screen(main.get("geometry"), self.root)
        if geometry:
            self.root.geometry(geometry)
            self._normal_geometry = geometry
        if main.get("zoomed"):
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass

    def _track_main_window(self, event):
        if event.widget is self.root and not self._is_zoomed():
            try:
                if self.root.state() == "normal":
                    self._normal_geometry = self.root.geometry()
            except tk.TclError:
                pass

    def restore_geometry(self, win, key):
        """Give a window its size and place from last time. False when there's none."""
        if not self.remember:
            return False
        saved = read_settings().get("windows", {})
        geometry = on_screen(saved.get(key) if isinstance(saved, dict) else None, self.root)
        if geometry:
            win.geometry(geometry)
        return bool(geometry)

    def keep_geometry(self, key, value):
        if not self.remember:
            return
        settings = read_settings()
        windows = settings.get("windows")
        if not isinstance(windows, dict):
            windows = settings["windows"] = {}
        windows[key] = value
        write_settings(settings)

    def quit(self):
        """Close the app, remembering where its windows were."""
        if self.palette_window:
            self.palette_window.close()
        if self.sidebar.large:
            self.sidebar.large.destroy()
        if self._normal_geometry or self._is_zoomed():
            self.keep_geometry("main", {"geometry": self._normal_geometry or self.root.geometry(),
                                        "zoomed": self._is_zoomed()})
        self.root.destroy()

    # ---------- layout ----------
    def _build_menu(self):
        bar = tk.Menu(self.root)
        file_menu = tk.Menu(bar, tearoff=False)
        file_menu.add_command(label="New project from image...", accelerator="Ctrl+N",
                              command=self.new_project)
        file_menu.add_command(label="Open project...", accelerator="Ctrl+O",
                              command=self.open_project)
        self.recent_menu = tk.Menu(file_menu, tearoff=False, postcommand=self._fill_recent)
        file_menu.add_cascade(label="Open recent", menu=self.recent_menu)
        self.file_menu = file_menu
        file_menu.add_command(label="Carry over assignments...", command=self.carry_over)
        file_menu.add_command(label="Assign from yarn image...", command=self.assign_from_image)
        file_menu.add_command(label="Close project", command=self.close_project)
        file_menu.add_separator()
        file_menu.add_command(label="Export pattern (phone / print)...", accelerator="Ctrl+E",
                              command=self.export_pattern)
        file_menu.add_command(label="Export yarn list...", command=self.export_yarn_list)
        file_menu.add_command(label="Shared yarn list for several projects...",
                              command=self.shared_list)
        file_menu.add_command(label="Save preview image...", command=self.save_preview)
        file_menu.add_command(label="Export before/after...", command=self.save_before_after)
        file_menu.add_separator()
        file_menu.add_command(label="New palette...", command=self.new_palette)
        file_menu.add_command(label="Open palette...", command=self.open_palette)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.quit)
        bar.add_cascade(label="File", menu=file_menu)
        self.update_file_menu()
        self.edit_menu = tk.Menu(bar, tearoff=False)
        self.edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        self.edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        bar.add_cascade(label="Edit", menu=self.edit_menu)
        self.update_edit_menu()
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
        # The vista theme draws a Menubutton grey on grey with no border; a 1 px frame makes
        # it read as a control rather than a disabled label.
        edge = tk.Frame(bar, bg="#7A7A7A", padx=1, pady=1)
        edge.pack(side="left", padx=(6, 8))
        self.palette_button = ttk.Menubutton(edge, text="", width=26)
        self.palette_button.pack()
        self.palette_dropdown = tk.Menu(self.palette_button, tearoff=False)
        self.palette_button["menu"] = self.palette_dropdown
        # a long name is cut with "..." to fit, and shown in full on hover (like the yarn title)
        self.palette_name_text = FitText(self.palette_button, chrome=PALETTE_BUTTON_CHROME)
        # Just the dropdown: its menu has Manage yarns, and the title bar shows the counts.

        r = tk.Frame(self.main, bg=BG)
        r.pack(side="top", fill="both", expand=True)
        r.columnconfigure(0, weight=1, uniform="half")
        r.columnconfigure(1, weight=1, uniform="half")

        self.target_title = tk.Label(r, text="Target", font=TITLE_FONT, bg=BG, anchor="w")
        self.target_title.grid(row=0, column=0, sticky="ew", padx=16, pady=(6, 0))
        # width=1: a long name never widens its column; it's cut with "..." to fit instead,
        # and the full name shows on hover
        self.yarn_title = tk.Label(r, text="", font=TITLE_FONT, bg=BG, anchor="w", width=1)
        self.yarn_title.grid(row=0, column=1, sticky="ew", padx=(8, 16), pady=(6, 0))
        self._badge_font = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.yarn_title_text = FitText(self.yarn_title, chrome=6)

        self.swatch = tk.Canvas(r, height=220, bg=BG, highlightthickness=0)
        self.swatch.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=16, pady=6)
        r.rowconfigure(1, weight=1)
        self.swatch.bind("<Configure>", lambda e: self.draw_swatch())
        self.swatch.bind("<Button-1>", lambda e: self.swatch.focus_set())

        self.hex_var = tk.StringVar()
        self.yarn_hex_var = tk.StringVar()
        # Everything below the swatch lines up with its edges: each panel fills its half, and
        # the rows under them span the whole width.
        self.target_panel = ColorPanel(r, self.hex_var, editable=True, bar_w=COMPARE_BAR_W,
                                       delta_space=True)
        self.target_panel.grid(row=2, column=0, sticky="new", padx=(16, 8), pady=4)
        self.yarn_panel = ColorPanel(r, self.yarn_hex_var, editable=True, on_copy=self.copy_hex,
                                     deltas=True, bar_w=COMPARE_BAR_W)
        self.yarn_entry = self.yarn_panel.entry
        self.yarn_hex_var.trace_add("write", lambda *_: self.on_yarn_hex_changed())
        self.yarn_entry.bind("<FocusOut>", lambda e: self.reset_yarn_hex())
        self.yarn_panel.grid(row=2, column=1, sticky="new", padx=(8, 16), pady=4)
        self.entry = self.target_panel.entry
        self.hex_var.trace_add("write", lambda *_: self.on_hex_changed())

        # Cards share the width in proportion to how much they say; Color weight sits at the end.
        stats = tk.Frame(r, bg=BG)
        stats.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(10, 2))
        self.delta_card = StatCard(stats, "Lightness difference (yarn \u2212 target)", width=240)
        self.pos_card = StatCard(stats, "Position in palette", width=170)
        self.match_card = StatCard(stats, "Match rank", width=140)
        for col, (card, weight) in enumerate(((self.delta_card, 24), (self.pos_card, 17),
                                              (self.match_card, 14))):
            card.grid(row=0, column=col, sticky="ew", padx=(0, 12))
            stats.columnconfigure(col, weight=weight)
        wbox = tk.Frame(stats, bg=BG)
        wbox.grid(row=0, column=3, sticky="e")
        tk.Label(wbox, text="Color weight", font=UI_FONT, bg=BG).pack(anchor="w")
        self.weight_var = tk.StringVar(value="%g" % self.weight)
        sp = ttk.Spinbox(wbox, from_=0, to=1, increment=0.1, width=5,
                         textvariable=self.weight_var, command=self.on_weight)
        sp.pack(anchor="w", pady=2)
        sp.bind("<Return>", lambda e: self.on_weight())
        sp.bind("<FocusOut>", lambda e: self.on_weight())
        tk.Label(wbox, text="0 = lightness only", font=("Segoe UI", 8), bg=BG,
                 fg="#888").pack(anchor="w")

        # Buttons keep one size, centered (keys are in the hint bar below, so they stay short).
        nav = tk.Frame(r, bg=BG)
        nav.grid(row=4, column=0, columnspan=2, pady=6)
        buttons = [ttk.Button(nav, text=text, width=15, command=cmd) for text, cmd in (
            ("◀  Lighter", lambda: self.step(-1)), ("Darker  ▶", lambda: self.step(1)),
            ("▲ Better match", lambda: self.cycle_match(-1)),
            ("Next match ▼", lambda: self.cycle_match(1)),
            ("Grayscale", self.toggle_gray), ("Assign", self.assign))]
        self.gray_btn, self.assign_main = buttons[4], buttons[5]
        for b in buttons:
            b.pack(side="left", padx=3)

        self.strip = tk.Canvas(r, height=96, bg=BG, highlightthickness=0)
        self.strip.grid(row=5, column=0, columnspan=2, sticky="ew", padx=16, pady=(6, 0))
        self.strip.bind("<Configure>", lambda e: self.draw_strip())
        # mouse wheel on the strip: up = lighter, down = darker, one yarn per notch
        self._wheel = 0
        self.strip.bind("<MouseWheel>", self._on_strip_wheel)
        self.strip.bind("<Button-4>", lambda e: self.step(-1))     # X11 wheel up
        self.strip.bind("<Button-5>", lambda e: self.step(1))      # X11 wheel down
        # middle-click: next candidate (macOS numbers the right and middle buttons the other way)
        aqua = self.root.tk.call("tk", "windowingsystem") == "aqua"
        self._right_click = "<Button-2>" if aqua else "<Button-3>"
        self.strip.bind("<Button-3>" if aqua else "<Button-2>",
                        lambda e: self.cycle_candidate(1))
        self._note, self._note_job = None, None

        hints = tk.Frame(r, bg=BG)
        hints.grid(row=6, column=0, columnspan=2, padx=16, pady=(4, 10))
        self._hints = hints
        self.hint_rows = []
        self.hint_items = []
        for keys, text in (("←→", "lighter / darker"), ("N", "next match"), ("B", "better match"),
                           ("Home", "best match"), ("M", "mark candidate"),
                           ("C", "next candidate"), ("G", "grayscale"), ("A", "assign"),
                           ("P", "original/preview"), ("T", "texture"), ("F1", "help")):
            item = tk.Frame(hints, bg=BG)
            self.hint_items.append(item)
            for k in ([keys] if len(keys) > 2 or keys == "F1" else list(keys)):
                keycap(item, k).pack(side="left", padx=(0, 2))
            tk.Label(item, text=text, font=("Segoe UI", 9), bg=BG, fg="#666").pack(
                side="left", padx=(3, 0))
        self._hint_split = None
        r.bind("<Configure>", lambda e: self.layout_hints(e.width), add="+")

    def layout_hints(self, width):
        """Key hints on as few centered lines as fit the width, evened out (2 lines of 6 and
        5 rather than 10 and 1)."""
        gap, room = 10, width - 32
        widths = [i.winfo_reqwidth() + gap for i in self.hint_items]
        n = len(widths)
        for lines in range(1, n + 1):
            per = -(-n // lines)                      # items per line, the same on every line
            if all(sum(widths[k:k + per]) <= room for k in range(0, n, per)):
                break
        split = tuple(range(0, n, per))
        if split == self._hint_split:
            return
        self._hint_split = split
        for row in self.hint_rows:
            row.pack_forget()
        while len(self.hint_rows) < len(split):
            self.hint_rows.append(tk.Frame(self._hints, bg=BG))
        for k, item in enumerate(self.hint_items):
            item.pack_forget()
            last = (k + 1) % per == 0 or k == n - 1          # no gap after a line's last item
            item.pack(in_=self.hint_rows[k // per], side="left", padx=(0, 0 if last else gap))
            item.lift()   # above the line frames, which may have been created after it
        for line in range(len(split)):
            self.hint_rows[line].pack(pady=(0 if line == 0 else 3, 0))

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
            self.root.bind_all(k, lambda e: self._key(e, self.sidebar.toggle_view, large=True))
        for k in ("t", "T"):
            self.root.bind_all(k, lambda e: self._key(e, self.sidebar.toggle_texture,
                                                      large=True))
        for k in ("m", "M"):
            self.root.bind_all(k, lambda e: self._key(e, self.mark_candidate))
        self.root.bind_all("c", lambda e: self._key(e, lambda: self.cycle_candidate(1)))
        self.root.bind_all("C", lambda e: self._key(e, lambda: self.cycle_candidate(-1)))
        for k, action in (("<Control-z>", self.undo), ("<Control-y>", self.redo),
                          ("<Control-Shift-Z>", self.redo)):
            self.root.bind_all(k, lambda e, a=action: self._key(e, a, always=True, large=True))
        for k in ("<Return>", "<Escape>"):
            self.entry.bind(k, lambda e: self.swatch.focus_set())
            self.yarn_entry.bind(k, lambda e: self.swatch.focus_set())   # FocusOut resets it

    def _key(self, event, action, always=False, large=False):
        """large: the key also works while the larger view has the focus."""
        widget = event.widget
        if not isinstance(widget, tk.Misc):
            return None
        top = widget.winfo_toplevel()
        if top is not self.root and not (large and top is self.sidebar.large):
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
            initialfile=free_name(DATA_DIR, "new-palette.csv", lambda p: [pal.brands_path(p)]),
            filetypes=[("CSV", "*.csv")])
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
            return      # the menus only offer the other palettes
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
        self.palette_name_text.set(name)

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
            filetypes=[("Pixel art", "*.png *.gif *.bmp"), ("PNG", "*.png"), ("GIF", "*.gif"),
                       ("BMP", "*.bmp"),
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
            initialfile=free_name(folder, os.path.splitext(name)[0] + EXTENSION),
            defaultextension=EXTENSION,
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
        if not self._need_project():
            return
        picks = CarryDialog(self.root, self, self.project).result
        if not picks:
            return
        self._record("carry over", [h for h, _, _ in picks],
                     lambda: self._apply_carry(picks, self.project))
        self._after_bulk_assign()

    def _after_bulk_assign(self):
        self.save_project()
        self.sidebar.refresh_rows()
        self.sidebar.refresh_plan()
        self.sidebar.render_image()
        if self.selected_hex:
            self._goto_entry(self.project.entry(self.selected_hex))

    def assign_from_image(self):
        """File menu: assign yarns from a hand-made yarn image (the rug's image recolored with
        exact yarn colors, same size)."""
        if not self._need_project():
            return
        title = "Assign from yarn image"
        path = filedialog.askopenfilename(
            title="Choose the yarn image (this rug's image in yarn colors, same size)",
            initialdir=os.path.dirname(os.path.abspath(self.project.path)),
            filetypes=[("Pixel art", "*.png *.gif *.bmp"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                image = pixelart.decode(fh.read())
            results = self.project.read_yarn_image(image, self.bank)
        except (OSError, ValueError) as e:
            messagebox.showerror(title, "Could not use %s\n\n%s" % (path, e))
            return
        by_hex = {y.hex.upper(): y for y in self.bank}

        def name(h):
            if h is None:
                return "transparent"
            y = by_hex.get(h)
            return "%s %s" % (h, y.label) if y else h

        picks, same, replaced, problems = [], 0, [], []
        for c in self.project.colors:
            kind, value = results[c.hex]
            if kind == "yarn":
                old = c.yarn if c.confirmed else None
                if old and self.assignment_key(old) == value.key \
                        and old["hex"].upper() == value.hex:
                    same += 1
                    continue
                picks.append((c.hex, value))
                if old:
                    replaced.append("%s: %s \u2192 %s" % (
                        c.hex, pal.label(old["name"], old.get("brand") or ""), value.label))
            elif kind == "split":
                problems.append("%s: several colors there (%s)" % (c.hex, ", ".join(
                    "%s \u00d7%d" % (name(h), n) for h, n in value)))
            elif kind == "unknown":
                problems.append("%s: %s is not a yarn color in %s" % (
                    c.hex, value, self.palette_name))
            else:
                problems.append("%s: transparent in the yarn image" % c.hex)

        def listing(head, lines, most=12):
            if not lines:
                return ""
            more = len(lines) - most
            return "\n\n%s\n%s%s" % (head, "\n".join(lines[:most]),
                                       "\n\u2026and %d more" % more if more > 0 else "")

        n = len(self.project.colors)
        text = "%d of %d colors match a yarn exactly%s." % (
            len(picks) + same, n, " (%d already assigned to it)" % same if same else "")
        text += listing("Replaces these assignments:", replaced)
        text += listing("Left as they are:", problems)
        if not picks:
            messagebox.showinfo(title, text + "\n\nNothing to assign.")
            return
        if not messagebox.askyesno(title, text + "\n\nAssign %d color%s?" % (
                len(picks), "" if len(picks) == 1 else "s")):
            return
        def apply():
            for hex_, yarn in picks:
                self.project.assign(hex_, yarn, self.palette_name, self.brands)
        self._record("assign from yarn image", [h for h, _ in picks], apply)
        self._after_bulk_assign()

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

    def _fill_recent(self):
        """File > Open recent, filled each time it opens: name and the folder it's in."""
        m = self.recent_menu
        m.delete(0, "end")
        paths = recent_projects() if self.remember else []
        for n, path in enumerate(paths, 1):
            folder = os.path.dirname(path)
            where = os.path.join(os.path.basename(os.path.dirname(folder)),
                                 os.path.basename(folder))
            name = os.path.splitext(os.path.basename(path))[0]
            m.add_command(label="%d  %s   (%s)" % (n, name, where), underline=0,
                          command=lambda p=path: self.open_recent(p))
        if not paths:
            m.add_command(label="No recent projects", state="disabled")
            return
        m.add_separator()
        m.add_command(label="Clear list", command=lambda: remember_setting("recent_projects", []))

    def open_recent(self, path):
        if not os.path.isfile(path):
            if messagebox.askyesno("Open recent", "%s\n\nisn't there any more (moved, renamed, "
                                   "or on a drive that isn't connected).\n\nTake it off the "
                                   "list?" % path):
                remember_recent(path, add=False)
            return
        self.open_project(path)

    def show_project(self, project):
        self.project = project
        self.update_file_menu()
        self.clear_history()
        self.sidebar.set_project(project)
        self.update_title()
        if self.remember:
            remember_setting("project", os.path.abspath(project.path))
            remember_recent(project.path)
        first = self.sidebar.tree.get_children()[0]   # top row, in the project's saved sort
        self.sidebar.select(first)
        self.select_project_color(first)

    PROJECT_ITEMS = ("Carry over assignments...", "Assign from yarn image...", "Close project",
                     "Export pattern (phone / print)...", "Export yarn list...",
                     "Save preview image...", "Export before/after...")

    def update_file_menu(self):
        """The File menu's project items are only enabled while a project is open."""
        for label in self.PROJECT_ITEMS:
            self.file_menu.entryconfig(label, state="normal" if self.project else "disabled")

    def close_project(self):
        self.project = None
        self.update_file_menu()
        self.clear_history()
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
        hex_, yarn = self.selected_hex, self.yarns[self.index]
        self._record("assign", [hex_], lambda: self.project.assign(
            hex_, yarn, self.palette_name, self.brands))
        self.save_project()
        self.sidebar.update_row(self.selected_hex)
        self.refresh()

    def unassign(self):
        if not (self.project and self.selected_hex):
            return
        hex_ = self.selected_hex

        def apply():
            self.project.unassign(hex_)
            self.project.suggest(self.yarns, self.palette_name, self.brands, self.weight)
        self._record("un-assign", [hex_], apply)
        self.save_project()
        self.sidebar.update_row(self.selected_hex)
        self.refresh()  # stay on the same yarn; the button flips back to "Assign"

    # ---------- undo / redo (assignments only, this session) ----------
    UNDO_STEPS = 200

    def _record(self, what, hexes, change):
        """Run change() and remember what it did to these colors as one undo step."""
        before = {h: self.project.state(h) for h in hexes}
        change()
        diff = [(h, b, self.project.state(h)) for h, b in before.items()]
        diff = [d for d in diff if d[1] != d[2]]
        if not diff:
            return
        label = "%s %s" % (what, diff[0][0]) if len(diff) == 1 else \
            "%s (%d colors)" % (what, len(diff))
        self.undo_stack.append((label, diff))
        del self.undo_stack[:-self.UNDO_STEPS]
        self.redo_stack.clear()
        self.update_edit_menu()

    def clear_history(self):
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.update_edit_menu()

    def undo(self):
        self._undo_redo(self.undo_stack, self.redo_stack, 1)

    def redo(self):
        self._undo_redo(self.redo_stack, self.undo_stack, 2)

    def _undo_redo(self, take, put, which):
        """which: 1 puts back the 'before' states (undo), 2 the 'after' ones (redo)."""
        if not (self.project and take):
            self.root.bell()
            return
        label, diff = take.pop()
        put.append((label, diff))
        for d in diff:
            self.project.restore(d[0], d[which])
        # suggestions follow the palette as it is now (nothing else changes)
        self.project.suggest(self.yarns, self.palette_name, self.brands, self.weight)
        self.update_edit_menu()
        self._after_bulk_assign()
        if len(diff) == 1:   # show the color that changed, with its yarn
            self.sidebar.select(diff[0][0])
            self.select_project_color(diff[0][0])

    def update_edit_menu(self):
        for i, (word, stack) in enumerate((("Undo", self.undo_stack), ("Redo", self.redo_stack))):
            self.edit_menu.entryconfig(i, label="%s %s" % (word, stack[-1][0]) if stack else word,
                                       state="normal" if stack else "disabled")

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
            self.yarn_panel.status.config(text="no such yarn")
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

    def _on_strip_wheel(self, event):
        if self.root.tk.call("tk", "windowingsystem") == "aqua":   # macOS: small deltas
            self.step(-1 if event.delta > 0 else 1)
            return
        # Windows: 120 per notch; touchpads send smaller pieces, so add them up
        self._wheel += event.delta
        notches = int(self._wheel / 120)
        if notches:
            self._wheel -= notches * 120
            self.step(-notches)

    def jump_to(self, i):
        self.index = i
        self.refresh()

    # ---------- candidates ----------
    def candidate_indexes(self):
        """Positions in the palette of the selected color's candidates, lightest first
        (candidates no longer among the active yarns are skipped)."""
        if not (self.project and self.selected_hex and self.yarns):
            return []
        return [i for i, y in enumerate(self.yarns)
                if self.project.is_candidate(self.selected_hex, y)]

    def mark_candidate(self, i=None):
        """M / right-click a tile: mark or unmark a yarn (the one on screen, or tile i) as a
        candidate for the selected color."""
        if not (self.project and self.selected_hex and self.yarns):
            self.root.bell()
            return
        if i is not None:
            self.index = i
        on = self.project.toggle_candidate(self.selected_hex, self.yarns[self.index])
        self.save_project()
        self.sidebar.update_row(self.selected_hex, plan=False)
        self.sidebar.size_columns()
        n = len(self.candidate_indexes())
        self.show_note("Marked as a candidate (%d)" % n if on else
                       "Unmarked (%d candidate%s left)" % (n, "" if n == 1 else "s"))
        self.refresh()

    def cycle_candidate(self, delta):
        """C / middle-click: the next candidate darker than the yarn on screen (Shift+C: the
        next lighter one), wrapping around."""
        marks = self.candidate_indexes()
        if not marks:
            self.root.bell()
            self.show_note("No candidates yet: M marks the yarn on screen"
                           if self.project and self.selected_hex else
                           "Pick a color of the project first")
            return
        if delta > 0:
            self.index = next((i for i in marks if i > self.index), marks[0])
        else:
            self.index = next((i for i in reversed(marks) if i < self.index), marks[-1])
        self.refresh()

    def show_note(self, text):
        """A short message at the top right of the yarn swatch, gone after a moment."""
        self._note = text
        if self._note_job:
            self.root.after_cancel(self._note_job)
        self._note_job = self.root.after(2500, self._clear_note)
        self.draw_swatch()

    def _clear_note(self):
        self._note, self._note_job = None, None
        self.draw_swatch()

    def toggle_gray(self):
        self.gray = not self.gray
        self.gray_btn.config(text="\u2713 Grayscale on" if self.gray else "Grayscale")
        self.refresh()
        self.sidebar.render_image()

    # ---------- exports ----------
    def _need_project(self):
        """The project items are disabled without a project; this covers their shortcuts."""
        return self.project is not None

    def _export_file(self, heading, title, suffix, filetypes, write):
        """Ask where to save an export next to the project ('<project><suffix>' suggested) and
        write it there with write(path). Returns the path, or None (cancelled or failed)."""
        folder = os.path.dirname(os.path.abspath(self.project.path))
        path = filedialog.asksaveasfilename(
            title=title, initialdir=folder, defaultextension=os.path.splitext(suffix)[1],
            initialfile=free_name(folder, self.project.name + suffix), filetypes=filetypes)
        if not path:
            return None
        try:
            write(path)
        except (OSError, ValueError) as e:
            messagebox.showerror(heading, "Could not write %s\n\n%s" % (path, e))
            return None
        return path

    def export_yarn_list(self):
        if not self._need_project():
            return
        plan = pl.Plan(self.project, self.resolve)
        if not plan.lines and not messagebox.askyesno(
                "Export yarn list", "No colors are assigned yet, so the list will be empty. "
                                    "Export anyway?"):
            return
        path = self._export_file("Export yarn list", "Export yarn list", "-yarns.csv",
                                 [("CSV", "*.csv")], lambda p: pl.write_yarn_list(plan, p))
        if path:
            messagebox.showinfo("Export yarn list", "Saved %d yarn%s to\n%s" % (
                len(plan.lines), "" if len(plan.lines) == 1 else "s", path))

    def shared_list(self):
        """File menu: the yarns several projects need together (works without a project)."""
        SharedListDialog(self.root, self)

    def export_pattern(self):
        if not self._need_project():
            return
        n_un = len(pl.Plan(self.project, self.resolve).unassigned)
        if n_un and not messagebox.askyesno(
                "Export pattern", "%d color%s not assigned to a yarn yet. They'll appear in the "
                "pattern in their original color, marked with ? and listed as unassigned.\n\n"
                "Export anyway?" % (n_un, " is" if n_un == 1 else "s are"), icon="warning"):
            return
        path = self._export_file(
            "Export pattern", "Export pattern for phone / print", "-pattern.html",
            [("Web page", "*.html")],
            lambda p: pattern.export_pattern(self.project, p, self.resolve))
        if path and messagebox.askyesno(
                "Export pattern", "Saved the pattern to\n%s\n\nCopy it to your phone and open "
                "it in the browser. Open it here now?" % path):
            import webbrowser
            webbrowser.open("file:///" + os.path.abspath(path).replace("\\", "/"))

    def save_preview(self):
        if self._need_project():
            self._export_file("Save preview", "Save yarn-color preview (1 pixel per knot)",
                              "-preview.png", [("PNG", "*.png")],
                              lambda p: pl.write_preview_png(self.project, p))

    def save_before_after(self):
        """File menu: the original next to the yarn preview, as one PNG to share."""
        if self._need_project():
            self._export_file("Export before/after",
                              "Export before/after (original next to the yarn preview)",
                              "-before-after.png", [("PNG", "*.png")],
                              lambda p: pl.write_before_after_png(self.project, p))

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
        if key != self._live_key:
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
            marks = self.candidate_indexes()
            tag = None
            if self.index in marks:
                tag = "\u2605 Candidate %d of %d" % (marks.index(self.index) + 1, len(marks))
            elif marks:
                tag = "%d candidate%s \u00b7 C to see" % (len(marks), "" if len(marks) == 1
                                                          else "s")
            for n, text in enumerate(t for t in (tag, self._note) if t):
                tw = self._badge_font.measure(text)
                y0 = 8 + n * 30
                c.create_rectangle(w - 8 - tw - 20, y0, w - 8, y0 + 24, fill="#2B2B2B",
                                   outline="")
                c.create_text(w - 18, y0 + 12, text=text, font=self._badge_font, fill="white",
                              anchor="e")

    def _draw_used_badge(self, c, x, bottom, hexes, room):
        """'Already used for [#87BEEB] [#5A9646] and 2 more' at the bottom-left of the yarn,
        listing as many colors as fit in `room` px."""
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
            rank = order.index(self.index) + 1
            above = "1 better match" if rank == 2 else "%d better matches" % (rank - 1)
            self.match_card.set("#%d" % rank, "best match" if rank == 1 else above)
        else:
            self.match_card.set("\u2013", "", "#888")
        self.pos_card.set("%d of %d" % (self.index + 1, len(self.yarns)),
                          "lightest \u2192 darkest")
        if t_L is None:
            self.delta_card.set("\u2013", "enter a target color", "#888")
        else:
            self.delta_card.set(*describe_delta_L(yarn.L - t_L))

    def set_yarn_title(self, text):
        self.yarn_title_text.set(text)

    def draw_strip(self):
        c = self.strip
        c.delete("all")
        w = c.winfo_width()
        if w < 4 or not self.yarns:
            return
        slots, gap = 2 * NEIGHBORS + 1, 6
        # tile + gap; the outer tiles meet the swatch's edges (1 px in: the bold frame of the
        # current tile would be cut off at the canvas edge)
        sw = (w - 3 + gap) / slots
        used = self.used_yarns()
        marks = set(self.candidate_indexes())
        for s in range(slots):
            i = self.index - NEIGHBORS + s
            if not 0 <= i < len(self.yarns):
                continue
            y = self.yarns[i]
            x0, x1 = 1 + s * sw, 1 + (s + 1) * sw - gap
            current = i == self.index
            tag = "slot%d" % i
            c.create_rectangle(x0, 2, x1, 52, fill=display_color(y.rgb, self.gray),
                               outline="#000" if current else "#BBB", width=3 if current else 1,
                               tags=tag)
            if (y.key, y.hex) in used:   # already assigned to another color of this rug
                c.create_oval(x1 - 15, 6, x1 - 5, 16, fill="#2B2B2B", outline="white",
                              tags=tag)
            if i in marks:   # a candidate for the selected color
                c.create_rectangle(x0 + 4, 5, x0 + 22, 21, fill="#2B2B2B", outline="", tags=tag)
                c.create_text(x0 + 13, 13, text="\u2605", fill="#FFD54F",
                              font=("Segoe UI", 9, "bold"), tags=tag)
            c.create_text((x0 + x1) / 2, 58, text=y.sku, width=sw - 6, anchor="n",
                          font=("Segoe UI", 8, "bold" if current else "normal"), tags=tag)
            c.tag_bind(tag, "<Button-1>", lambda e, i=i: self.jump_to(i))
            c.tag_bind(tag, self._right_click, lambda e, i=i: self.mark_candidate(i))


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
