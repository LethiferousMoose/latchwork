"""Latchwork: match pixel-art colors to latch-hook yarns by lightness (CIE L*, as GIMP shows it).

Stage 1: comparison view. Run:  python latchwork.py
"""
import csv
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from colormath import (gray_for_lightness, lch_to_rgb, nearest_index, parse_hex, rgb_to_lch,
                       to_hex)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PALETTE = os.path.join(HERE, "palette.csv")

NEIGHBORS = 4          # yarns shown on each side of the current one in the strip
BAR_W, BAR_H = 240, 14  # channel gradient bars
MARK_H = 7             # marker zone under each bar
C_MAX = 200.0          # GIMP's LCh chroma slider range

BG = "#ECECEC"
PANEL_BG = "#F7F7F7"
UI_FONT = ("Segoe UI", 10)
VALUE_FONT = ("Consolas", 11)
TITLE_FONT = ("Segoe UI", 18, "bold")


class Yarn:
    def __init__(self, sku, r, g, b, L):
        self.sku, self.rgb, self.L = sku, (r, g, b), L
        self.hex = to_hex(r, g, b)
        self.lch = rgb_to_lch(r, g, b)


def load_palette(path):
    """Read palette.csv and return yarns lightest -> darkest (stable: ties keep file order)."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = {"sku", "r", "g", "b", "L_gimp"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError("palette is missing column(s): " + ", ".join(sorted(missing)))
        yarns = [Yarn(row["sku"], int(row["r"]), int(row["g"]), int(row["b"]), float(row["L_gimp"]))
                 for row in reader]
    if not yarns:
        raise ValueError("palette has no rows")
    yarns.sort(key=lambda y: -y.L)
    return yarns


def display_color(rgb, gray):
    if not gray:
        return to_hex(*rgb)
    v = gray_for_lightness(rgb_to_lch(*rgb)[0])
    return to_hex(v, v, v)


# Each channel: label, value formatter, position 0..1, gradient sampler t(0..1) -> rgb.
def _channels(rgb, lch):
    r, g, b = rgb
    L, C, h = lch
    return [
        ("R", r / 2.55, r / 255, lambda t: (t * 255, g, b)),
        ("G", g / 2.55, g / 255, lambda t: (r, t * 255, b)),
        ("B", b / 2.55, b / 255, lambda t: (r, g, t * 255)),
        ("L", L, L / 100, lambda t: lch_to_rgb(t * 100, C, h)),
        ("C", C, min(C / C_MAX, 1.0), lambda t: lch_to_rgb(L, t * C_MAX, h)),
        ("h", h, h / 360, lambda t: lch_to_rgb(L, C, t * 360)),
    ]


class ColorPanel(tk.Frame):
    """GIMP-style channel readout: label, gradient bar with marker, boxed value, per channel."""

    def __init__(self, parent, hex_var, editable, on_copy=None):
        super().__init__(parent, bg=PANEL_BG, bd=1, relief="solid", padx=12, pady=10)
        self.bars, self.values, self.images = [], [], []
        for row, name in enumerate("RGBLCh"):
            tk.Label(self, text=name, font=("Segoe UI", 10, "bold"), bg=PANEL_BG, width=2,
                     anchor="w").grid(row=row, column=0, sticky="w")
            bar = tk.Canvas(self, width=BAR_W, height=BAR_H + MARK_H, bg=PANEL_BG,
                            highlightthickness=0)
            bar.grid(row=row, column=1, padx=(4, 8), pady=2)
            val = tk.Label(self, font=VALUE_FONT, bg="white", width=6, anchor="e",
                           relief="sunken", bd=1, padx=4)
            val.grid(row=row, column=2, sticky="e")
            self.bars.append(bar)
            self.values.append(val)

        html = tk.Frame(self, bg=PANEL_BG)
        html.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        tk.Label(html, text="HTML notation", font=UI_FONT, bg=PANEL_BG).pack(side="left")
        self.entry = ttk.Entry(html, textvariable=hex_var, font=("Consolas", 12), width=9,
                               state="normal" if editable else "readonly")
        self.entry.pack(side="left", padx=8)
        if on_copy:
            ttk.Button(html, text="Copy", width=6, command=on_copy).pack(side="left")
        self.status = tk.Label(html, text="", font=("Segoe UI", 9), bg=PANEL_BG, fg="#B00020")
        self.status.pack(side="left", padx=4)

    def show(self, rgb, other_L=None):
        """Draw the channels for rgb (or blank if None). other_L adds a faint marker on L."""
        self.images = []
        if rgb is None:
            for bar, val in zip(self.bars, self.values):
                bar.delete("all")
                bar.create_rectangle(0, 0, BAR_W - 1, BAR_H - 1, fill="#DDD", outline="#BBB")
                val.config(text="")
            return
        for (name, value, pos, sample), bar, val in zip(_channels(rgb, rgb_to_lch(*rgb)),
                                                        self.bars, self.values):
            bar.delete("all")
            img = tk.PhotoImage(width=BAR_W, height=BAR_H)
            row = "{" + " ".join(to_hex(*sample(x / (BAR_W - 1))) for x in range(BAR_W)) + "}"
            img.put(row, to=(0, 0, BAR_W, BAR_H))
            self.images.append(img)  # keep a reference or Tk drops the image
            bar.create_image(0, 0, image=img, anchor="nw")
            bar.create_rectangle(0, 0, BAR_W - 1, BAR_H - 1, outline="#999")
            if name == "L" and other_L is not None:
                self._marker(bar, other_L / 100, fill="", outline="#888")
            self._marker(bar, pos, fill="#111", outline="#111")
            val.config(text="%.1f" % value)

    @staticmethod
    def _marker(bar, pos, fill, outline):
        x = 1 + pos * (BAR_W - 3)
        top = BAR_H + 1
        bar.create_polygon(x, top, x - 5, top + MARK_H - 1, x + 5, top + MARK_H - 1,
                           fill=fill, outline=outline)


class App:
    def __init__(self, root, palette_path):
        self.root = root
        self.yarns = []
        self.index = 0
        self.target = None  # (r, g, b) or None
        self.gray = False

        root.title("Latchwork")
        root.configure(bg=BG)
        root.minsize(780, 720)
        self._build_menu()
        self._build_ui()
        self._bind_keys()
        self.load(palette_path)

    # ---------- layout ----------
    def _build_menu(self):
        bar = tk.Menu(self.root)
        file_menu = tk.Menu(bar, tearoff=False)
        file_menu.add_command(label="Open palette...", command=self.open_palette)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.root.destroy)
        bar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=bar)

    def _build_ui(self):
        r = self.root
        r.columnconfigure(0, weight=1, uniform="half")
        r.columnconfigure(1, weight=1, uniform="half")

        tk.Label(r, text="Target", font=TITLE_FONT, bg=BG, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
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

        self.summary = tk.Label(r, text="", font=("Segoe UI", 12), bg=BG)
        self.summary.grid(row=3, column=0, columnspan=2, pady=(8, 2))

        nav = tk.Frame(r, bg=BG)
        nav.grid(row=4, column=0, columnspan=2, pady=6)
        buttons = [("◀  Lighter", lambda: self.step(-1)),
                   ("Nearest match (N)", self.jump_nearest),
                   ("Darker  ▶", lambda: self.step(1)),
                   ("Grayscale (G)", self.toggle_gray)]
        for text, cmd in buttons:
            ttk.Button(nav, text=text, width=18, command=cmd).pack(side="left", padx=4)

        self.strip = tk.Canvas(r, height=96, bg=BG, highlightthickness=0)
        self.strip.grid(row=5, column=0, columnspan=2, sticky="ew", padx=16, pady=(6, 0))
        self.strip.bind("<Configure>", lambda e: self.draw_strip())

        tk.Label(r, font=("Segoe UI", 9), bg=BG, fg="#666",
                 text="← → step lighter / darker    N nearest match    G grayscale    "
                      "Enter or Esc leaves the hex field    click a neighbor to jump").grid(
            row=6, column=0, columnspan=2, pady=(4, 10))

    def _bind_keys(self):
        # Arrows step even while typing in the hex field (it's a paste-and-go field).
        self.root.bind_all("<Left>", lambda e: self._key(lambda: self.step(-1), always=True))
        self.root.bind_all("<Right>", lambda e: self._key(lambda: self.step(1), always=True))
        for k in ("n", "N", "<Home>"):
            self.root.bind_all(k, lambda e: self._key(self.jump_nearest))
        for k in ("g", "G"):
            self.root.bind_all(k, lambda e: self._key(self.toggle_gray))
        for k in ("<Return>", "<Escape>"):
            self.entry.bind(k, lambda e: self.swatch.focus_set())

    def _key(self, action, always=False):
        if not always and isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry)):
            return None  # let the letter be typed
        action()
        return "break"

    # ---------- data ----------
    def open_palette(self):
        path = filedialog.askopenfilename(title="Open palette", initialdir=HERE,
                                          filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if path:
            self.load(path)

    def load(self, path):
        try:
            yarns = load_palette(path)
        except (OSError, ValueError, KeyError) as e:
            messagebox.showerror("Latchwork", "Could not load palette:\n%s\n\n%s" % (path, e))
            return
        self.yarns, self.index = yarns, 0
        self.root.title("Latchwork - %s (%d yarns)" % (os.path.basename(path), len(yarns)))
        if self.target:
            self.jump_nearest()
        else:
            self.refresh()

    # ---------- actions ----------
    def on_hex_changed(self):
        text = self.hex_var.get()
        rgb = parse_hex(text)
        if rgb is None:
            self.target_panel.status.config(text="" if not text.strip() else "not a valid hex")
            return
        self.target_panel.status.config(text="")
        self.target = rgb
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
        self.refresh()

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
        if w < 4 or not self.yarns:
            return
        mid = w // 2
        if self.target:
            c.create_rectangle(0, 0, mid, h, fill=display_color(self.target, self.gray), width=0)
        else:
            c.create_rectangle(0, 0, mid, h, fill="#DDDDDD", width=0)
            c.create_text(mid // 2, h // 2, text="Paste a hex color into HTML notation below",
                          font=UI_FONT, fill="#666")
        yarn = self.yarns[self.index]
        c.create_rectangle(mid, 0, w, h, fill=display_color(yarn.rgb, self.gray), width=0)
        if self.gray:
            c.create_text(8, 8, text="GRAYSCALE", anchor="nw", font=("Segoe UI", 9, "bold"),
                          fill="#FF3366")

    def draw_info(self):
        if not self.yarns:
            return
        yarn = self.yarns[self.index]
        self.yarn_title.config(text=yarn.sku)
        self.yarn_hex_var.set(yarn.hex)
        t_L = rgb_to_lch(*self.target)[0] if self.target else None
        self.target_panel.show(self.target, other_L=yarn.L)
        self.yarn_panel.show(yarn.rgb, other_L=t_L)
        pos = "%d / %d" % (self.index + 1, len(self.yarns))
        if t_L is None:
            self.summary.config(text=pos)
        else:
            self.summary.config(text="ΔL  %+.1f        ·        %s" % (yarn.L - t_L, pos))

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
    App(root, DEFAULT_PALETTE)
    root.mainloop()


if __name__ == "__main__":
    main()
