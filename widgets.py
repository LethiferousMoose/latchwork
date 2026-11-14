"""Shared Tk widgets for Latchwork."""
import tkinter as tk
from tkinter import ttk

from colormath import lch_to_rgb, rgb_to_lch, to_hex

BAR_W, BAR_H = 240, 14  # channel gradient bars
MARK_H = 7              # marker zone under each bar
C_MAX = 200.0           # GIMP's LCh chroma slider range

PANEL_BG = "#F7F7F7"
UI_FONT = ("Segoe UI", 10)
VALUE_FONT = ("Consolas", 11)


class StatCard(tk.Frame):
    """A small boxed readout: caption, big value, short explanatory note."""

    def __init__(self, parent, caption, width=210):
        super().__init__(parent, bg=PANEL_BG, bd=1, relief="solid", padx=14, pady=5,
                         width=width, height=92)
        self.pack_propagate(False)
        tk.Label(self, text=caption, font=("Segoe UI", 9), bg=PANEL_BG, fg="#666",
                 anchor="w").pack(fill="x")
        self.value = tk.Label(self, font=("Segoe UI", 18, "bold"), bg=PANEL_BG, anchor="w")
        self.value.pack(fill="x")
        self.note = tk.Label(self, font=("Segoe UI", 9), bg=PANEL_BG, fg="#555", anchor="w")
        self.note.pack(fill="x")

    def set(self, value, note="", color="#222222"):
        self.value.config(text=value, fg=color)
        self.note.config(text=note)


def describe_delta_L(dL):
    """(value text, note, color) for yarn L minus target L."""
    a = abs(dL)
    value = ("%+.1f" % dL).replace("-", "−")
    if a < 0.05:
        return "0.0", "same lightness", "#1B5E20"
    side = "darker" if dL < 0 else "lighter"
    if a <= 1:
        return value, "very close · yarn is a touch %s" % side, "#1B5E20"
    if a <= 3:
        return value, "close · yarn is a bit %s" % side, "#8A5A00"
    return value, "yarn is noticeably %s" % side, "#B71C1C"


# Each channel: label, displayed value, position 0..1, gradient sampler t(0..1) -> rgb.
HUE_MIN_C = 5.0   # below this chroma a color is grayish and its hue means little


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
    """GIMP-style channel readout: label, gradient bar with marker, boxed value, per channel,
    plus an HTML notation box (editable or read-only)."""

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

    def show(self, rgb, other=None):
        """Draw the channels for rgb (or blank if None). `other` (an rgb) adds faint markers on
        L, C and h for comparison; no hue marker when either color is near gray."""
        self.images = []
        if rgb is None:
            for bar, val in zip(self.bars, self.values):
                bar.delete("all")
                bar.create_rectangle(0, 0, BAR_W - 1, BAR_H - 1, fill="#DDD", outline="#BBB")
                val.config(text="")
            return
        lch = rgb_to_lch(*rgb)
        ghost = {}
        if other is not None:
            olch = rgb_to_lch(*other)
            ghost = {name: pos for name, _, pos, _ in _channels(other, olch)
                     if name in "LC" or (name == "h" and min(lch[1], olch[1]) >= HUE_MIN_C)}
        for (name, value, pos, sample), bar, val in zip(_channels(rgb, lch),
                                                        self.bars, self.values):
            bar.delete("all")
            img = tk.PhotoImage(width=BAR_W, height=BAR_H)
            row = "{" + " ".join(to_hex(*sample(x / (BAR_W - 1))) for x in range(BAR_W)) + "}"
            img.put(row, to=(0, 0, BAR_W, BAR_H))
            self.images.append(img)  # keep a reference or Tk drops the image
            bar.create_image(0, 0, image=img, anchor="nw")
            bar.create_rectangle(0, 0, BAR_W - 1, BAR_H - 1, outline="#999")
            if name in ghost:
                self._marker(bar, ghost[name], fill="", outline="#888")
            self._marker(bar, pos, fill="#111", outline="#111")
            val.config(text="%.1f" % value)

    @staticmethod
    def _marker(bar, pos, fill, outline):
        x = 1 + pos * (BAR_W - 3)
        top = BAR_H + 1
        bar.create_polygon(x, top, x - 5, top + MARK_H - 1, x + 5, top + MARK_H - 1,
                           fill=fill, outline=outline)
