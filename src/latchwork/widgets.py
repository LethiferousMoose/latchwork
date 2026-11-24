"""Shared Tk widgets for Latchwork."""
import math
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from .colormath import lch_to_rgb, rgb_to_lch, to_hex

BAR_W, BAR_H = 240, 14  # channel gradient bars
MARK_H = 7              # marker zone under each bar
C_MAX = 200.0           # GIMP's LCh chroma slider range

PANEL_BG = "#F7F7F7"
UI_FONT = ("Segoe UI", 10)
VALUE_FONT = ("Consolas", 11)
NOTE_FONT = ("Segoe UI", 9)
NOTE_GREY, NOTE_RED = "#777", "#C62828"


def required_label(parent, text, bg, font=UI_FONT):
    """A field label with a red * after it: the field must be filled in."""
    f = tk.Frame(parent, bg=bg)
    tk.Label(f, text=text, font=font, bg=bg).pack(side="left")
    tk.Label(f, text=" *", font=(font[0], font[1], "bold"), bg=bg, fg=NOTE_RED).pack(side="left")
    return f


def required_legend(parent, bg):
    return tk.Label(parent, text="* Required", font=NOTE_FONT, bg=bg, fg=NOTE_GREY)


class FieldNote(tk.Frame):
    """The line under a form field: grey help text, or what's wrong in red. It always takes
    one line and never asks for width (grid it sticky "ew"), so a message coming or going never
    resizes the dialog."""

    def __init__(self, parent, bg, helper=""):
        h = tkfont.Font(font=NOTE_FONT).metrics("linespace") + 2
        super().__init__(parent, bg=bg, height=h, width=1)
        self.helper = helper
        self.label = tk.Label(self, font=NOTE_FONT, bg=bg, bd=0, padx=0, pady=0, anchor="w")
        self.label.place(x=0, y=0)
        self.set()

    def set(self, error=None, helper=None):
        if helper is not None:
            self.helper = helper
        self.label.config(text=error or self.helper, fg=NOTE_RED if error else NOTE_GREY)


def free_name(folder, filename, also=None):
    """A file name for a save dialog's suggestion that doesn't exist yet in folder, the way
    Windows does it: "name.ext", else "name (1).ext", "name (2).ext", ...
    also(path): other paths that file brings along (a palette's brands file); they must be
    free too."""
    stem, ext = os.path.splitext(filename)
    n = 0
    while True:
        name = filename if n == 0 else "%s (%d)%s" % (stem, n, ext)
        path = os.path.join(folder or ".", name)
        if not any(os.path.exists(p) for p in [path] + list(also(path) if also else [])):
            return name
        n += 1


class Tooltip:
    """Hover popup for a widget. content(event) returns None (nothing to show) or
    (title, rows), rows = [(swatch hexes, text)]. Shown after a short pause; it changes when
    the content under the pointer changes (e.g. another table row)."""

    DELAY = 400   # ms
    BG = "#FFFFF0"

    def __init__(self, widget, content):
        self.widget, self.content = widget, content
        self.tip = self.job = self.key = None
        widget.bind("<Motion>", self._motion, add="+")
        widget.bind("<Leave>", lambda e: self.hide(), add="+")
        widget.bind("<ButtonPress>", lambda e: self.hide(), add="+")

    def _motion(self, event):
        c = self.content(event)
        key = repr(c) if c else None
        if key == self.key:
            return
        self.hide()
        self.key = key
        if c:
            x, y = event.x_root, event.y_root
            self.job = self.widget.after(self.DELAY, lambda: self.show(c, x, y))

    def show(self, content, x, y):
        """Open near the pointer, kept inside the app window (which on a maximized window is
        the monitor it's on, minus the taskbar): below the pointer, else above, and when the
        list is taller than the window, as many rows as fit plus '...and N more'."""
        self.job = None
        title, rows = content
        win = self.widget.winfo_toplevel()
        bx0, by0 = win.winfo_rootx(), win.winfo_rooty()
        bx1, by1 = bx0 + win.winfo_width(), by0 + win.winfo_height()
        tip, h = self._build(title, rows)
        if h > by1 - by0 - 8 and len(rows) > 1:
            per_row = (h - self._title_h) / len(rows)
            fit = max(1, int((by1 - by0 - 8 - self._title_h) / per_row) - 1)
            tip.destroy()
            tip, h = self._build(title, rows[:fit] + [
                ([], "\u2026and %d more" % (len(rows) - fit))])
        self.tip = tip
        w = tip.winfo_reqwidth()
        x = max(bx0, min(x + 14, bx1 - w - 4))
        if y + 18 + h <= by1:
            y += 18                      # below the pointer
        elif y - h - 8 >= by0:
            y -= h + 8                   # above it
        else:
            y = max(by0, by1 - h)        # taller than either side: as low as fits
        tip.wm_geometry("+%d+%d" % (x, y))
        tip.deiconify()

    def _build(self, title, rows):
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.withdraw()                   # measured first, shown once placed
        box = tk.Frame(tip, bg=self.BG, padx=8, pady=6, highlightthickness=1,
                       highlightbackground="#999")
        box.pack()
        box.columnconfigure(1, weight=1)   # a long title widens the text, not the swatches
        head = None
        if title:
            head = tk.Label(box, text=title, font=("Segoe UI", 9, "bold"), bg=self.BG,
                            anchor="w", justify="left")
            head.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 3))
        for r, (swatches, text) in enumerate(rows, start=1):
            sw = tk.Frame(box, bg=self.BG)
            sw.grid(row=r, column=0, sticky="w", padx=(0, 6), pady=1)
            for hx in swatches:
                tk.Frame(sw, bg=hx, width=14, height=12, highlightthickness=1,
                         highlightbackground="#888").pack(side="left", padx=(0, 2))
            tk.Label(box, text=text, font=("Segoe UI", 9), bg=self.BG, anchor="w",
                     justify="left").grid(row=r, column=1, sticky="w")
        tip.update_idletasks()
        self._title_h = (head.winfo_reqheight() + 3 if head else 0) + 14   # + box padding
        return tip, tip.winfo_reqheight()

    def hide(self):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None
        self.key = None


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


CLOSE, NEAR, FAR = "#1B5E20", "#8A5A00", "#B71C1C"   # difference within 1, within 3, more
TINT = {CLOSE: "#DCEFDD", NEAR: "#F6E7C8", FAR: "#F9DEDE"}  # pale chip behind that text color


def closeness_color(diff):
    return CLOSE if abs(diff) <= 1 else NEAR if abs(diff) <= 3 else FAR


def describe_delta_L(dL):
    """(value text, note, color) for yarn L minus target L."""
    a = abs(dL)
    value = ("%+.1f" % dL).replace("-", "−")
    if a < 0.05:
        return "0.0", "same lightness", CLOSE
    side = "darker" if dL < 0 else "lighter"
    if a <= 1:
        return value, "very close · yarn is a touch %s" % side, CLOSE
    if a <= 3:
        return value, "close · yarn is a bit %s" % side, NEAR
    return value, "yarn is noticeably %s" % side, FAR


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


def channel_delta(name, value, other):
    """value - other for a channel; for hue the shorter way around (350 vs 10 is -20)."""
    d = value - other
    if name == "h":
        d = (d + 180) % 360 - 180
    return d


class ColorPanel(tk.Frame):
    """GIMP-style channel readout: label, gradient bar with marker, boxed value, per channel,
    plus an HTML notation box (editable or read-only). With deltas=True, a column after the
    values shows this color minus the `other` one passed to show(); delta_space=True keeps that
    column's room empty (so two panels side by side line up). The bars take whatever width the
    panel is given (bar_w is what they ask for)."""

    def __init__(self, parent, hex_var, editable, on_copy=None, deltas=False, bar_w=BAR_W,
                 delta_space=False, note=None):
        """note: helper text for a FieldNote under HTML notation (self.note), which then
        is a required field; None = no note (the main window uses self.status instead)."""
        super().__init__(parent, bg=PANEL_BG, bd=1, relief="solid", padx=12, pady=10)
        self.bar_w = bar_w
        self.bars, self.values, self.images, self.deltas = [], [], [], []
        self._shown = None   # the rgb whose gradients are drawn
        self._last = (None, None)   # what show() was last given, to redraw at a new width
        self._resize_job = None
        self.columnconfigure(1, weight=1)
        for row, name in enumerate("RGBLCh"):
            tk.Label(self, text=name, font=("Segoe UI", 10, "bold"), bg=PANEL_BG, width=2,
                     anchor="w").grid(row=row, column=0, sticky="w")
            bar = tk.Canvas(self, width=bar_w, height=BAR_H + MARK_H, bg=PANEL_BG,
                            highlightthickness=0)
            bar.grid(row=row, column=1, sticky="ew", padx=(4, 8), pady=2)
            val = tk.Label(self, font=VALUE_FONT, bg="white", width=6, anchor="e",
                           relief="sunken", bd=1, padx=4)
            val.grid(row=row, column=2, sticky="e")
            if deltas or delta_space:
                d = tk.Label(self, font=("Consolas", 10), bg=PANEL_BG, width=6, anchor="e",
                             padx=3)
                d.grid(row=row, column=3, sticky="e", padx=(6, 0))
                if deltas:
                    self.deltas.append(d)
            self.bars.append(bar)
            self.values.append(val)
        self.bars[0].bind("<Configure>", self._on_resize)

        html = tk.Frame(self, bg=PANEL_BG)
        html.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        html.columnconfigure(3, weight=1)
        if note is None:
            tk.Label(html, text="HTML notation", font=UI_FONT, bg=PANEL_BG).grid(row=0, column=0)
        else:
            required_label(html, "HTML notation", PANEL_BG).grid(row=0, column=0)
        self.entry = ttk.Entry(html, textvariable=hex_var, font=("Consolas", 12), width=9,
                               state="normal" if editable else "readonly")
        self.entry.grid(row=0, column=1, padx=8)
        if on_copy:
            ttk.Button(html, text="Copy", width=6, command=on_copy).grid(row=0, column=2)
        self.status = tk.Label(html, text="", font=("Segoe UI", 9), bg=PANEL_BG, fg="#B00020")
        self.status.grid(row=0, column=3, sticky="w", padx=4)
        self.note = None
        if note is not None:
            self.note = FieldNote(html, PANEL_BG, note)
            self.note.grid(row=1, column=1, columnspan=3, sticky="ew", padx=8)

    def show(self, rgb, other=None):
        """Draw the channels for rgb (or blank if None). `other` (an rgb) adds hollow markers on
        every bar for comparison; no hue marker when either color is near gray. The gradients
        are kept when rgb is the same as last time (stepping yarns only moves the markers)."""
        self._last = (rgb, other)
        same = rgb is not None and rgb == self._shown and len(self.images) == len(self.bars)
        self._shown = rgb
        if not same:
            self.images = []
        if rgb is None:
            for d in self.deltas:
                d.config(text="", bg=PANEL_BG)
            for bar, val in zip(self.bars, self.values):
                bar.delete("all")
                bar.create_rectangle(0, 0, self.bar_w - 1, BAR_H - 1, fill="#DDD", outline="#BBB")
                val.config(text="")
            return
        lch = rgb_to_lch(*rgb)
        ghost, delta = {}, {}
        if other is not None:
            olch = rgb_to_lch(*other)
            hue_ok = min(lch[1], olch[1]) >= HUE_MIN_C
            ghost = {name: pos for name, _, pos, _ in _channels(other, olch)
                     if name != "h" or hue_ok}
            theirs = {name: v for name, v, _, _ in _channels(other, olch)}
            delta = {name: channel_delta(name, value, theirs[name])
                     for name, value, _, _ in _channels(rgb, lch) if name != "h" or hue_ok}
        for name, d in zip("RGBLCh", self.deltas):
            if name not in delta:
                d.config(text="", bg=PANEL_BG)
                continue
            size = delta[name]
            if name == "h":   # how far the color moves around the hue circle: Lab's delta H
                size = 2 * math.sqrt(lch[1] * olch[1]) * math.sin(math.radians(size) / 2)
            fg = closeness_color(size)
            d.config(text=("%+.1f" % delta[name]).replace("-", "−"), fg=fg, bg=TINT[fg])
        for (name, value, pos, sample), bar, val in zip(_channels(rgb, lch),
                                                        self.bars, self.values):
            w = self.bar_w
            if same:
                bar.delete("marker")
            else:
                bar.delete("all")
                img = tk.PhotoImage(width=w, height=BAR_H)
                row = "{" + " ".join(to_hex(*sample(x / (w - 1))) for x in range(w)) + "}"
                img.put(row, to=(0, 0, w, BAR_H))
                self.images.append(img)  # keep a reference or Tk drops the image
                bar.create_image(0, 0, image=img, anchor="nw")
                bar.create_rectangle(0, 0, w - 1, BAR_H - 1, outline="#999")
            if name in ghost:
                self._marker(bar, ghost[name], fill="", outline="#888")
            self._marker(bar, pos, fill="#111", outline="#111")
            val.config(text="%.1f" % value)

    def _on_resize(self, event):
        """The bars got a new width (window resized): draw them again at that width."""
        if event.width > 20 and event.width != self.bar_w:
            self.bar_w = event.width
            if not self._resize_job:
                self._resize_job = self.after_idle(self._redraw)

    def _redraw(self):
        self._resize_job = None
        self._shown = None   # the gradients are redrawn at the new width
        self.show(*self._last)

    def _marker(self, bar, pos, fill, outline):
        x = 1 + pos * (self.bar_w - 3)
        top = BAR_H + 1
        bar.create_polygon(x, top, x - 5, top + MARK_H - 1, x + 5, top + MARK_H - 1,
                           fill=fill, outline=outline, tags="marker")


class TreeSort:
    """Sortable column headings for a flat Treeview.

    Click a heading to sort by it, click again to flip the direction, a third time to go back to
    the default order. The heading of the sorted column shows ▲ (ascending) or ▼
    (descending).

    keys:    {column: (key(iid) -> value, first click descending?)}
    default: key(iid) -> value giving the default order (ties in a sort keep this order).
    on_change(state): called after a click; state is [column, descending] or None (default).
    Call apply() after refilling the tree, since rows are inserted in the default order."""

    ARROW = {False: " \u25b2", True: " \u25bc"}

    def __init__(self, tree, keys, default, on_change=None):
        self.tree, self.keys, self.default, self.on_change = tree, keys, default, on_change
        self.state = None
        self.titles = {c: tree.heading(c, "text") for c in keys}
        for c in keys:
            tree.heading(c, command=lambda c=c: self.click(c))

    def set(self, state):
        """Restore a saved state ([column, descending] or None); unknown columns are ignored."""
        ok = isinstance(state, (list, tuple)) and len(state) == 2 and state[0] in self.keys
        self.state = [state[0], bool(state[1])] if ok else None
        self.apply()

    def click(self, col):
        first = self.keys[col][1]
        if not self.state or self.state[0] != col:
            self.state = [col, first]
        elif self.state[1] == first:
            self.state = [col, not first]
        else:
            self.state = None
        self.apply()
        if self.on_change:
            self.on_change(self.state)

    def apply(self):
        for c, title in self.titles.items():
            on = self.state and self.state[0] == c
            self.tree.heading(c, text=title + (self.ARROW[self.state[1]] if on else ""))
        rows = sorted(self.tree.get_children(), key=self.default)
        if self.state:
            rows.sort(key=self.keys[self.state[0]][0], reverse=self.state[1])   # stable
        for i, iid in enumerate(rows):
            self.tree.move(iid, "", i)
        sel = self.tree.selection()
        if sel:
            self.tree.see(sel[0])
