"""Help window: a topic list on the left, the text on the right.

Text markup: "# " starts a heading, "- " a bullet, "  " (two spaces) an indented example line;
blank lines separate paragraphs.
"""
import tkinter as tk
from tkinter import ttk

BG = "#ECECEC"

TOPICS = [
    ("Getting started", """
# Getting started
Latchwork takes a pixel-art image to a finished latch-hook pattern:

- File → New project from image (PNG, GIF or BMP; not JPEG, which blurs pixel art into extra colors). The image is stored inside the .latchwork file, so moving or deleting the original never breaks a project.
- Carry over: a new project can start from earlier rugs' assignments (the open project is offered first). Colors with exactly the same hex get the same yarn, marked "carried over"; every other color is matched as usual. Also under File → Carry over assignments, which only fills colors not assigned yet.
- Colors tab: every image color with its knot count, lightest first. Click a row (or a pixel in the image) to make it the target.
- The main view shows the target next to a yarn. Step through yarns, then press Assign (A).
- Plan tab: packs or pieces per yarn (most knots first), finished size and canvas to cut.
- Click a column heading to sort by it, again to reverse, a third time for the default order. Color sorts by lightness; Status puts suggested colors first. Each project remembers its sort.
- File → Export pattern (Ctrl+E): a single HTML file for your phone or printer.

Projects save automatically on every change.
"""),
    ("How matching works", """
# How matching works
Every color is turned into three numbers (CIE Lab, the same space as GIMP's LCh):

- L: lightness, 0 = black to 100 = white (exactly GIMP's L).
- a: green (negative) ↔ red (positive).
- b: blue (negative) ↔ yellow (positive).

A gray has a and b near 0; the further they are from 0 the more colorful the color. So a and b hold the hue and colorfulness, L holds the lightness.

# The score
Each yarn gets a score against the target; the lowest score is the best match:

  score = ΔL² + weight² × (Δa² + Δb²)

The weight is the Color weight setting (default 0.5). Squaring is ordinary distance (Pythagoras): being 2 off counts four times as much as being 1 off.

# Example: target brown #987050 (L 50.8, a +13.3, b +24.3)
Delft Blue (L 50.4, a −9.1, b −29.6): nearly the same lightness, opposite color.

  ΔL² = 0.4² = 0.2
  color = 0.25 × (22.4² + 53.9²) = 852
  score ≈ 852

Medium Brown (L 45.8, a +21.1, b +27.7): 5 darker, nearly the same color.

  ΔL² = 5² = 25
  color = 0.25 × (7.8² + 3.4²) = 18
  score ≈ 43

Medium Brown wins. With weight 0 only ΔL² counts, and Delft Blue would win (0.2 against 25).

# The ranking
Every active yarn is scored and sorted: that list is the match ranking. The Match rank card shows where the yarn on screen sits in it; Next match (N) and Better match (B) walk down and up it, Home jumps back to #1.

# Already used in this rug
When the yarn on screen is already assigned (or carried over) to another color of this rug, a dark "Already used for" badge on the yarn lists those colors, and its tile in the strip below gets a dot. Two colors on one yarn become one color on the rug: fine for colors you want merged, worth a second look in a gradient. Suggestions don't count, and matching is unchanged.

# Why 0.5
Fitted on four of my finished rugs (48 color choices). Lightness only suggested my actual yarn 5 times out of 48; weight 0.5 suggested it 24 times and almost always had it in the top 3. In my picks lightness stays within about 3 L and hue within about 6°, while colorfulness drops a lot (yarn is duller than pixel art). Half weight tolerates that drop; a weight of 1 chases colorfulness and lets lightness drift.
"""),
    ("Color weight: when to change it", """
# Color weight: when to change it
0.5 is a good default. Anything from about 0.3 to 0.8 worked nearly as well on my rugs, so small changes do little.

# Lower it (toward 0.2, or 0) when lightness matters most
- Shading and gradients, where smooth steps in L matter more than hue.
- Areas I'll fill with a different color family anyway.
- Sign: matches have the right color but the ΔL card shows a big difference.

# Raise it (toward 0.7–0.8) when the color identity matters most
- Recognizable colors: a character's signature red, a logo, skin, grass that must read as green.
- Small accents, where a few wrong-colored knots stand out more than a slight lightness error.
- Sign: #1 keeps coming from the wrong color family and I press N several times to reach the right one.

# Avoid going much above 1
Pixel art is more vivid than any yarn; high weights chase colorfulness and lightness drifts.

# Notes
- It can change mid-project, e.g. higher for a character, lower for a shaded background.
- Changing it re-suggests only colors that aren't assigned yet. Assigned colors never change.
- It is remembered between sessions. 0 gives the original lightness-only matching.
"""),
    ("Keyboard shortcuts", """
# Keyboard shortcuts
- ← →: step one yarn lighter / darker (palette order, lightest to darkest).
- N: next match down the ranking (after stepping with the arrows, starts again at #1).
- B: better match, one step up the ranking.
- Home: best match (#1).
- A: assign the yarn on screen to the selected color; press again to undo.
- G: grayscale (judge lightness alone).
- P: sidebar image: original / yarn preview (assigned yarns, and suggested yarns for unassigned colors; Mark unassigned stripes those). The selected color shows the yarn currently on screen, live as you step, so you can judge it in the whole picture; nothing changes until you Assign. Highlight selected color (off by default) fades everything else, to show where that color is: toward white, or toward dark gray when the selected color is light (so white or pale colors still stand out). View larger (above the image) opens it in its own window, as big as fits, for small, long or wide art; it follows the sidebar and you can click colors in it.
- Enter or Esc: leave the hex field.
- Typing a hex into the yarn's HTML notation box jumps to the yarn with that color; if no yarn matches, the box resets when you leave it.
- Ctrl+N new project, Ctrl+O open project, Ctrl+E export pattern, Ctrl+P manage yarns.
- Ctrl+1 … Ctrl+9: switch to palette 1–9 of the palette list.
- F1: this help.

The hollow markers on the bars (R, G, B, L, C and h) show the other side's value, so the difference between target and yarn is visible at a glance (no hue marker for near-grays, whose hue means little).
"""),
    ("Palettes and brands", """
# Palettes and brands
One palette is active at a time. The Palette dropdown above the comparison view (and the Palette menu) lists every palette I've opened; picking one switches instantly (Ctrl+1…9 for the first nine). Palettes are kept in memory and only re-read if the file changed on disk. "Remove from list" only takes it off the list; the file stays.

Unassigned colors are re-suggested from the active palette when switching; assigned colors never change.

Palette → Manage yarns (Ctrl+P) edits the active palette. Changes save immediately.

- A yarn is identified by name + brand and shown as "Name (Brand)".
- Pack size comes from the brand (Brands…): pieces per pre-cut pack, or blank when the yarn is cut from skeins. A yarn can override it with its own pack size.
- Retire hides a yarn from matching but keeps it (e.g. discontinued). Delete is for mistakes.
- Import (CSV or GIMP .gpl) always merges: nothing is removed, and a summary is shown before anything changes.
- Selecting a yarn in the manager shows it in the main view.

The palette is two files: palette.csv (yarns) and palette.brands.csv (brands and pack sizes). Export CSV writes both.

Projects aren't tied to a palette: each assignment keeps the yarn's name, brand, pack size and hex, so it survives palette edits or switching palettes.
"""),
    ("Planning and canvas", """
# Planning and canvas
The Plan tab counts assigned colors only; unassigned ones are listed as not counted.

- Pre-cut yarn: packs = knots (plus spare) ÷ pack size, rounded up. Colors sharing a yarn are added up first.
- Cut from skeins: the number of pieces to cut.
- Spare: a percentage added to every count.
- Merged colors (two image colors on one yarn) are highlighted. That's often intended. Point at a highlighted row to see its image colors, or at the note below the table for all of them.

# Canvas
Settings are per project (Plan tab → Change…), with "Also use these for new projects".

- Finished size = image width and height ÷ holes per inch.
- Canvas to cut = image + borders: a fold on each side, a fold at the top (hanging loop) and at the bottom including one empty row.

File menu: export the yarn list (CSV) and the yarn-color preview (PNG, one pixel per knot).
"""),
    ("Pattern on the phone", """
# Pattern on the phone
File → Export pattern (Ctrl+E) writes one self-contained HTML file. Copy it to the phone and open it in the browser; it works offline.

- Pinch to zoom; the grid stays sharp. Rows are numbered from the bottom (row 1 = bottom).
- Symbols button cycles Auto / Always / Off. Auto shows symbols once cells are big enough (about 7 px; zoom in if they're hidden). Always draws them even when tiny. Off hides them.
- Tap a yarn in the legend to show only that color (its cells keep their symbols, the rest go grey). Tap it again, or Show all (greyed out until a yarn is picked), to bring the rest back.
- Row tracker: the Row button turns it on, ▼ ▲ move it, and it highlights one row. Column tracker: the Column button, ◀ ▶, one column. With both on, the bar above them reads the cell where they cross: its yarn and symbol (brand underneath), and how many of it run to the right, this cell included ("Green · 6": hook 6).
- With both on, ◀ ▶ step one cell and wrap to the next row up (or back down) at the ends, since you hook bottom to top, left to right. ◀◀ ▶▶ (either side of the readout, only while both are on) jump a whole color run instead. Tapping the grid never moves the trackers, so a stray touch can't lose your place.
- Done (the tall button on the right) marks what's tracked as hooked, then moves on: with both trackers on, the rest of the color run (then to the next run); with only Row on, the whole row (then up a row); with only Column on, the whole column (then right a column). Hooked cells fade and lose their symbol, so what's left stands out. On something already marked, the button reads Undo and clears it instead; for a run that's the whole run, wherever you are in it, and you go back to its first cell.
- Progress: the header (on a phone, the top of the Yarns sheet) shows how many knots are hooked, and each yarn shows how many of its knots are left. A yarn ticks itself done when all of them are hooked; you can still tick yarns by hand.
- Keyboard (computer): ↑ ↓ rows, ← → columns, Shift+← → color runs, Enter Done.
- Remembered on that device, per pattern: hooked cells, done checkmarks, both trackers (on/off and position) and the Symbols mode. Zoom and the tapped yarn are not. Re-exporting keeps them as long as the project name and image size stay the same.
- Printing: an overview plus pages of 50 × 70 holes, labelled A1 (bottom-left), A2…

Re-export after changing assignments; the old file on the phone doesn't update itself.
"""),
]


class HelpWindow(tk.Toplevel):
    def __init__(self, root, topic=None):
        super().__init__(root)
        self.title("Latchwork - Help")
        self.configure(bg=BG)
        self.geometry("900x620")
        self.minsize(640, 400)

        left = tk.Frame(self, bg=BG)
        left.pack(side="left", fill="y", padx=(12, 6), pady=12)
        self.topics = tk.Listbox(left, width=31, activestyle="none", exportselection=False,
                                 font=("Segoe UI", 10), relief="solid", bd=1,
                                 highlightthickness=0, selectbackground="#0078D7")
        for name, _ in TOPICS:
            self.topics.insert("end", "  " + name)
        self.topics.pack(fill="y", expand=True)
        self.topics.bind("<<ListboxSelect>>", lambda e: self._show_selected())

        right = tk.Frame(self, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(6, 12), pady=12)
        self.text = tk.Text(right, wrap="word", font=("Segoe UI", 10), relief="solid", bd=1,
                            padx=16, pady=12, spacing1=2, spacing3=2, cursor="arrow")
        sb = ttk.Scrollbar(right, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.text.tag_configure("h", font=("Segoe UI", 13, "bold"), spacing1=12, spacing3=4)
        self.text.tag_configure("first", spacing1=0)
        self.text.tag_configure("bullet", lmargin1=8, lmargin2=24)
        self.text.tag_configure("code", font=("Consolas", 10), lmargin1=24, lmargin2=24,
                                background="#F3F3F3")
        self.text.tag_configure("p", spacing3=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.show(topic)

    def show(self, topic=None):
        names = [n for n, _ in TOPICS]
        i = names.index(topic) if topic in names else 0
        self.topics.selection_clear(0, "end")
        self.topics.selection_set(i)
        self._render(TOPICS[i][1])

    def _show_selected(self):
        sel = self.topics.curselection()
        if sel:
            self._render(TOPICS[sel[0]][1])

    def _render(self, body):
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        first = True
        for line in body.strip("\n").splitlines():
            if not line.strip():
                continue
            if line.startswith("# "):
                t.insert("end", line[2:] + "\n", ("h", "first") if first else ("h",))
            elif line.startswith("- "):
                t.insert("end", "•  " + line[2:] + "\n", ("bullet",))
            elif line.startswith("  "):
                t.insert("end", line.strip() + "\n", ("code",))
            else:
                t.insert("end", line + "\n", ("p",))
            first = False
        t.configure(state="disabled")
        t.yview_moveto(0)


_window = None


def open_help(root, topic=None):
    """Open the help window (or bring it forward) at `topic`."""
    global _window
    if _window is not None and _window.winfo_exists():
        _window.show(topic)
        _window.deiconify()
        _window.lift()
        _window.focus_set()
    else:
        _window = HelpWindow(root, topic)
    return _window
