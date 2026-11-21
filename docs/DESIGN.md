# Latchwork design notes

How Latchwork works and why it works that way. For using it, see the [README](../README.md)
and the in-app help (F1).

## Principles

- **Python 3.8+ and Tkinter, standard library only.** Nothing to install. PNG decoding is done
  in pure Python with `zlib`.
- **Lightness first.** A rug is read from a distance, where light and dark structure matters
  more than exact hue. Lightness is exactly GIMP's L\*, so values can be checked in GIMP.
- **Never lose work.** Projects save on every change, embed their image, and keep a snapshot of
  every assigned yarn, so palette edits, retirements or deletions can't break them.
  Save dialogs suggest a name that doesn't exist yet (project or palette name first, then
  "-pattern.html", "-yarns.csv", ...; "name (1).ext", "(2)", ... once taken, as Windows does,
  with a palette's brands file checked too), so a quick Enter never replaces a file.
- **A project is not tied to a palette.** It matches against whichever palette is active.

## Color math (`colormath.py`)

"L" means CIE L\* exactly as GIMP 2.10 shows it in its LCh color selector. GIMP (via babl)
uses D50-adapted sRGB:

1. Decode sRGB: `c/255`, then `c/12.92` if `c <= 0.04045`, else `((c+0.055)/1.055)**2.4`.
2. `Y = 0.2225045*R + 0.7168786*G + 0.0606169*B` (linear values).
3. `L* = 116*cbrt(Y) - 16`, or `Y*24389/27` when `Y <= 216/24389`.

C and h come from Lab using babl's sRGB → XYZ (D50) matrix and the D50 white point.

This was verified against GIMP 2.10.34 by reading values from its LCh selector, L / C / h:

| Color | RGB | L / C / h |
|---|---|---|
| Sunny Yellow | 254, 250, 190 | 97.5 / 29.9 / 100.4 |
| Light Teal | 83, 170, 204 | 65.3 / 32.5 / 232.7 |
| Bright Red | 210, 25, 35 | 45.8 / 82.1 / 34.8 |
| (target bar) | 136, 160, 72 | 62.6 / 46.2 / 114.2 |

Other lightness formulas fit a hand-sorted palette much worse (D65 L\* 54 order inversions,
Rec. 601 luma 85, HSL 90, HSV 95, against 1 for this formula).

**Display conventions** follow GIMP: RGB on a 0–100 scale (254 → 99.6), LCh to one decimal,
hex as `#RRGGBB`. Yarn lists run lightest to darkest.

## Matching

Every yarn is scored against the target color in Lab; the lowest score is the best match:

```
score = ΔL² + w² × (Δa² + Δb²)
```

`a` (green ↔ red) and `b` (blue ↔ yellow) together hold hue and colorfulness. `w` is the
**Color weight** (default 0.5, saved in settings): a color difference of 10 costs the same as
being 5 off in lightness. `w = 0` is pure lightness matching. Ties keep palette order.

Example, target brown `#987050` (L 50.8, a +13.3, b +24.3):

| Yarn | ΔL² | w² × (Δa² + Δb²) | Score |
|---|---|---|---|
| Delft Blue (L 50.4, a −9.1, b −29.6) | 0.2 | 0.25 × (22.4² + 53.9²) = 852 | 852 |
| Medium Brown (L 45.8, a +21.1, b +27.7) | 25 | 0.25 × (7.8² + 3.4²) = 18 | **43** |

**Why 0.5.** Matching started as lightness only. It was then tested against 48 real color
choices from four finished rugs:

| Weight | Pick ranked #1 | Median rank of pick | Mean rank |
|---|---|---|---|
| 0 (lightness only) | 5 / 48 | 9 | 17.8 |
| 0.1 | 24 / 48 | 2 | 10.1 |
| 0.3 | 21 / 48 | 2 | 3.7 |
| **0.5** | **24 / 48** | **2** | **2.6** |
| 1.0 | 17 / 48 | 2 | 2.9 |
| 1.5 | 14 / 48 | 2 | 3.5 |

What the real picks showed: lightness within about 3 L, hue within about 6°, but colorfulness
allowed to drop a lot (yarn is far duller than pixel-art colors); dark, dull colors treated as
neutrals; when no yarn has both, hue is kept and lightness given up. A single weight captures
this; separate chroma and hue weights didn't do measurably better on this data. There is no
brand preference.

**In the UI:** the target jumps to the best match. **N** / **B** walk down / up the ranking
(stopping at the ends), **Home** returns to #1; after stepping with ← → (palette order), N
starts at #1 again. The Match rank card shows the current yarn's rank. A yarn already
assigned to another color of the rug gets an "Already used for" badge listing those colors
and a dot on its strip tile (assignments only, not suggestions; the ranking is unchanged,
since a shared yarn merges two colors on the rug, which is sometimes wanted and sometimes
not). Hollow markers on every bar (R, G, B, L, C, h) show the other side's value, and a
column right of the yarn's values gives yarn − target per channel, in the same scale as the
values (R, G, B 0–100); hue goes the shorter way around, so 350° vs 10° is −20. Each
sits on a pale chip colored like the lightness card: green within 1, amber within 3, red
beyond. Hue is judged by ΔH = 2√(C₁C₂)·sin(Δh/2), how far the color moves in Lab units,
since the same angle is a big change on a vivid color and almost none on a dull one (the
number shown stays in degrees).
No hue marker or difference below chroma 5, where hue means little.

## Palettes (`palette.py`, `palette_window.py`)

**`palette.csv`** columns: `order, sku, brand, r, g, b, hex, L_gimp, pack_size, retired`.
RGB is 0–255, `retired` is `yes` or blank, `L_gimp` is rewritten on every save, `pack_size`
is a per-yarn override (blank = the brand's). The file is kept sorted by L\*, lightest first;
ties keep their order.

**Brands** live in a companion file named after the palette (`palette.csv` →
`palette.brands.csv`): `brand, pack_size`, where pack size is pieces per pre-cut pack and
blank means cut from skeins. A pack size change applies to open projects too.

**A yarn is identified by name + brand** (case-insensitive) and shown as "Name (Brand)".

**Retire** hides a yarn from matching but keeps it (discontinued colors). **Delete** is for
mistakes.

**Import** (CSV in the format above, or GIMP `.gpl`) always merges and never removes
anything. A summary is shown first and nothing changes until confirmed:

- New yarn: added. Same name and hex: skipped.
- Same name, different hex: keep mine, take the file's, or keep both under a new name
  (per yarn or for all).
- Matches a retired yarn: offer to restore it.
- Same hex under another name (maybe a rename): add, skip, or rename the existing yarn.
- Placeholder names ("Index 3", "Untitled") or duplicates within the file: name or skip.

**Export:** CSV (everything, including retired, plus the brands file) and `.gpl` (active
yarns only, `R G B<tab>Name (Brand)`).

**Palette list:** one palette is active at a time; every palette opened stays on a list in the
Palette dropdown and menu (Ctrl+1…9). Palettes are kept in memory and re-read only when the
file changed on disk. Removing one from the list never touches the file.

## Projects (`project.py`)

A `.latchwork` file is readable JSON:

```json
{
  "format": "latchwork-project",
  "version": 1,
  "image": {"filename": "landscape.png", "format": "png", "width": 40, "height": 30,
            "data": "<base64 PNG>"},
  "colors": [
    {"hex": "#AAD2F0", "count": 280, "confirmed": true, "carried_from": "forest rug",
     "yarn": {"name": "Light Blue", "brand": "Hershner's", "pack": 320,
              "hex": "#ACD5F2", "palette": "palette.csv"},
     "candidates": [{"name": "Sky Blue", "brand": "Red Heart", "hex": "#A9C9E4"}]}
  ],
  "settings": {"spare_percent": 0, "holes_per_inch": 3.75,
               "sort": {"colors": ["count", true]}}
}
```

- The **image is embedded**, so the original file can move or disappear.
- **Candidates** (optional, per color) are yarns I marked while deciding (M, or right-click a
  strip tile); C and middle-click rotate through them in palette order, wrapping around, and
  Shift+C goes back. They are bookmarks only: matching and ranking ignore them, and assigning
  keeps them so the shortlist is there if I change my mind. A candidate is identified by name,
  brand and hex, so a recolored yarn no longer counts; ones not among the active yarns are
  kept in the file but skipped. Starred strip tiles, a badge on the yarn swatch ("Candidate 2
  of 3") and a star count in the Colors list's status show them.
- Each image color has either a **suggestion** (`confirmed: false`, the current best match from
  the active palette, refreshed when the palette or weight changes) or an **assignment**
  (`confirmed: true`, never changed automatically).
- The yarn entry is a **snapshot** (name, brand, pack size, hex, source palette). Plans look
  the yarn up in the active palette first, so pack size changes apply, and fall back to the
  snapshot when the yarn is gone.
- **Table order** (Colors and Plan tabs): colors are stored lightest first (by the image
  color's L\*), which is the Colors tab's default order; the Plan tab defaults to most knots
  first, then yarn name. Clicking a heading sorts by it (▲/▼), again flips it, a third time
  returns to the default. Color sorts by L\* (first click darkest first, since the default is
  lightest first); Status orders suggested, carried over, assigned; Need sorts by pieces
  including the spare, so packs and pieces compare. Number columns start largest first, text
  A–Z. The sort is saved per project in `settings.sort` as `[column, descending]` (absent =
  default). A row that changes (e.g. on Assign) stays where it is until the table is next
  refilled, so the selection doesn't jump away.
- **Carry over** (offered when creating a project, and under File): every color not assigned
  yet whose hex exactly matches an assigned color in the chosen earlier projects gets that
  yarn's snapshot as an assignment, with `carried_from` naming the source project (shown as
  "carried over" in the Colors list; cleared once the color is assigned or un-assigned by
  hand). Sprites from one game reuse exact hexes, so there is no near-matching: a different
  hex is a new color and is matched as usual. Rules:
  - Each project stays one rug; earlier projects are only read, so a hooked rug never changes.
  - When sources gave the same hex different yarns, the newest project (last saved) is picked
    and the summary lets you choose another per color.
  - Carried-over yarns missing from the active palette can be kept (snapshot fallback, as
    above) or left to be matched from the active palette.
  - Matching itself is unchanged: yarns used in earlier rugs get no preference.
- **Assign from yarn image** (File): brings in a rug patterned by hand before Latchwork. The
  yarn image is the rug's image recolored so every pixel is a yarn's exact color, at the same
  size (one pixel per knot; enlarged or gridded copies are refused). For each color of the rug,
  the pixels at the same places in the yarn image decide: all one yarn's color assigns that
  yarn (an ordinary assignment, replacing any earlier one; the summary lists replacements).
  Anything else is left as it is and listed: several colors there (e.g. pixels touched up
  later), a color no yarn has (renamed or edited), or transparent. Exact colors only, no
  near-matching. Retired yarns count (an old rug may use one); a color shared with an active
  yarn goes to the active one.
- Transparent pixels are not knots and are skipped. Images with more than 64 colors trigger a
  warning (probably not clean pixel art); more than 1,000 are refused with advice to reduce the
  colors first (each color gets a swatch in the Colors list, and Tk on Windows aborts the whole
  program at around 5,000 of them). PNG (all color types and bit depths), GIF and BMP
  are supported; JPEG is refused (its compression smears pixel art into near-duplicate
  colors).
- BMP: uncompressed 1/2/4/8-bit palette, 16/24/32-bit and bitfields, bottom-up or top-down;
  RLE-compressed BMPs are refused. A 32-bit BMP whose alpha is 0 everywhere is read as opaque
  (many programs leave that byte empty). The project stores a BMP as PNG: same pixels, smaller
  file. Headers asking for more than 4 million pixels are treated as damaged.

## Planning (`plan.py`)

- Only **assigned** colors are counted. Colors sharing a yarn are added up before rounding.
  Such merged yarns are highlighted in the table; the note below it is one line however
  many there are (so the table and sizes never get pushed out), and tooltips on the rows
  and the note list the image colors.
- Pre-cut yarn: `packs = ceil(knots × (1 + spare%) / pack size)`. Cut from skeins: the number of
  pieces. No skein estimates.
- Canvas, per project (defaults: 3.75 holes per inch, borders 3 per side, 8 top, 4 bottom):
  - Finished size = image size ÷ holes per inch.
  - Canvas to cut = (width + 2 × side) × (height + top + bottom) holes. The defaults come from
    folding 3 holes on each side, 8 at the top for the hanging loop, and 3 at the bottom plus
    one empty row, because the cut edge isn't stable enough to hook into.
- **Before/after export** (`before_after_image`): original and yarn preview, each at the largest
  whole-number zoom that fits 500 px (at least 1x, so pixel art stays crisp on social sites), in a
  10 px gray frame (#D8D8D8, the larger view's; transparent knots show it too) with a 20 px white
  gap. Side by side, or stacked with the original on top when the art is wider than tall, to
  stay close to square. It reproduces the screenshot pair I liked, without screenshots.
- Yarn preview (sidebar, and the preview PNG export, one pixel per knot): assigned colors show
  their yarn, unassigned ones their suggested yarn; "Mark unassigned" stripes those in the sidebar.
  In the sidebar, the selected color shows the yarn currently in the comparison view, updating
  live as you step (preview only; nothing is stored until Assign).
- Highlight selected color fades the other colors 78% toward white, or toward dark gray (#3A3A3A)
  when the selected color as shown has L\* of 65 or more, since pale colors vanish against a
  white fade.
- The sidebar image is zoomed by whole numbers only (or shrunk by whole steps for big images), so
  every art pixel is an equal square. That leaves small or oddly shaped art (long, wide) small
  in the 400 x 250 box, so **View larger** opens the same image in its own resizable,
  non-modal window at the largest whole-number zoom that fits. It mirrors the sidebar (view,
  highlight, stripes, selected color, live yarn), redraws once after a burst of changes, and a
  click there selects a color too; P switches original/preview there too (other keys stay
  with the main window); Esc closes it, and it reopens at its last size this session.

## Pattern export (`pattern.py`, `pattern_template.html`)

One self-contained HTML file (no external files, works offline). The project is embedded as
JSON, one cell per knot, safely escaped.

- Canvas-drawn grid that stays sharp at every zoom; pinch to zoom and pan. Bold line every 10
  cells; **rows numbered from the bottom** (row 1 = bottom), since hooking goes bottom to top.
- Each yarn gets a symbol: 20 drawn shapes, then letters and digits (drawn, so phones never
  turn them into emoji), black or white by the yarn's L\*. The Symbols button cycles **Auto**
  (hidden below 7 px cells, where they become an unreadable texture, with a "Zoom in" hint),
  **Always** (drawn down to 3 px) and **Off**.
- Legend with swatch, name, symbol and count; tapping a yarn shows only that color.
- Done checkmarks per yarn, a row tracker and a column tracker. With both trackers on, a
  readout names the yarn in the cell where they cross and how many cells of it run to the
  right; ◀ ▶ step a cell and wrap to the next row up / back down at the row ends (hooking goes
  bottom to top, left to right), ◀◀ ▶▶ jump a color run. Tapping the grid deliberately doesn't
  move the trackers (a stray touch mustn't lose your place). The view pans only when the
  tracked row / column is off screen.
- Hooked cells: a tall Done button beside the tracker lines marks what's tracked (the rest of
  the run with both trackers on, else the row or the column) and moves to the next one; on
  something already fully marked it becomes Undo and clears it (a run: the whole run, from any
  cell of it, returning to its first cell). Hooked cells get a white veil
  and no symbol on screen (print ignores them). Progress shows in the header / yarn sheet,
  knots left per yarn, and a yarn counts as done once all its knots are hooked (or ticked).
  Kept as a bitset (one bit per cell, base64) in the saved state.
- Stored per pattern in the browser's local storage on that device, keyed by project name and
  image size: hooked cells, done marks, both trackers (on/off and position), Symbols mode.
  Zoom and the tapped legend yarn are not stored.
- Unassigned colors appear in their original color with a `?` symbol (export warns first).
- Print: an overview plus pages of 50 × 70 holes on letter paper, labelled A1 (bottom-left), A2…

## Settings

`settings/latchwork_settings.json` (per user, not in git): the active palette, the palette
list, the last project, the color weight and canvas defaults for new projects.

## Future possibilities

Not planned, but noted so the reasoning isn't lost:

- **Yarn inventory:** record which yarns you own, to prefer them in matching or list what to buy.
- **Skein estimates** for cut-from-skein yarn (pieces → skeins). Left out because yarn per piece
  varies too much by brand and cut length.
- **Combined shopping list** across several projects, for buying yarn for a batch of rugs.
- **Brand filter** for matching. Left out because mixing brands is usually needed to have enough
  colors.
