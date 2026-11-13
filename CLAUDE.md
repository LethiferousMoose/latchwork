# Latchwork

A personal desktop tool for latch-hook rugs made from pixel art. It takes me from a pixel-art
image to a finished pattern: match each image color to a yarn by lightness, plan quantities and
canvas size, and export a pattern I can read on my phone while hooking.

Keep it simple. This is a personal tool, not a product.

## Ground rules
- Python 3, **Tkinter, standard library only**. Nothing to pip install.
- **Never modify my .xcf files.** If GIMP has to open one, work on a scratch copy and never save.
- Ask instead of guessing on anything that affects L, color math or the yarn order.
- Build in the stages below. Stop after each stage so I can try it before the next one starts.

## Files
- `latchwork.py`: the app (run this).
- `colormath.py`: the verified color math (sRGB → CIE Lab/LCh, GIMP-exact). Tests target it.
- `palette.py`: the yarn bank (load/save, .gpl/CSV import-export, import merge rules). No Tk.
- `palette_window.py`: the palette manager window and its dialogs.
- `widgets.py`: shared widgets (the GIMP-style ColorPanel used in the main view and edit dialog).
- `pixelart.py`: exact PNG decode/encode (stdlib zlib), GIF via Tk, color counting. No Tk for PNG.
- `project.py`: the `.latchwork` project file (embedded image, colors, assignments). No Tk.
- `project_panel.py`: the project sidebar (image/preview, Colors and Plan tabs, Assign).
- `plan.py`: quantities, packs, canvas size, merged colors, yarn-list CSV, preview PNG. No Tk.
- `pattern_template.html`: the phone/print pattern page (HTML/CSS/JS, no external files).
- `pattern.py`: embeds a project into the template as JSON (one cell per knot). No Tk.
- `palette.csv`: the yarn palette (see below).
- `export_palette.py`: GIMP 2.10 Python-Fu script that produced `palette.csv` from `AllColors.xcf`.
- `tests/`: unit tests.
- `AllColors.xcf`: my palette reference in GIMP. Read only.

## Phase 1 results (done, verified)
- **GIMP 2.10.34**, `AllColors.xcf` is 8-bit gamma (perceptual) RGB with **no embedded ICC
  profile**, so GIMP's built-in sRGB.
- Yarn swatches are the layers inside the **Colors** group, 10×100 px each. All are solid and
  opaque. The layer name is the yarn name/SKU.
- Not yarns, so excluded: the **Mask** layer (the target bar, `#88A048`) and **Cafe RH**
  (an old name for the same yarn as Cafe Latte RH; it is the hidden layer). Keep it out of the palette.
- My old sort plug-in (`%APPDATA%\GIMP\2.10\plug-ins\soft-by-brightness.py`) used Rec. 601
  luma, which is why it didn't get the order right. Ignore it.
- **"L" means CIE L\* exactly as shown in GIMP's LCh color selector.** Verified against GIMP:
  - Decode sRGB: `c/255`, then `c/12.92` if `c <= 0.04045`, else `((c+0.055)/1.055)**2.4`.
  - babl's D50-adapted sRGB Y: `Y = 0.2225045*R + 0.7168786*G + 0.0606169*B` (linear values).
  - `L* = 116*cbrt(Y) - 16`, or `Y*24389/27` when `Y <= 216/24389`.
  - Spot-checked in GIMP: Sunny Yellow 97.5, Light Teal 65.3, Dusty Grey RH 64.6, Mask 62.6,
    Bright Red 45.8, Black RH 4.1. All matched.
  - Other formulas fit my hand-tuned layer order much worse (D65 L\* 54 inversions, luma 85,
    HSL 90, HSV 95, versus 1 real inversion for this formula).
- **C and h are verified too** (from Lab via babl's sRGB → XYZ D50 matrix and D50 white).
  GIMP spot-checks, L / C / h: Sunny Yellow 97.5 / 29.9 / 100.4, Bright Red 45.8 / 82.1 / 34.8,
  Light Teal 65.3 / 32.5 / 232.7, Mask 62.6 / 46.2 / 114.2.
- My layer order had one real mistake: **Light Teal belongs before Dusty Grey RH.** Everything
  else agrees with L\* at one decimal place.

## Palette
- `palette.csv` columns: `order, sku, brand, r, g, b, hex, L_gimp, pack_size, retired`. RGB is
  0–255. `retired` is `yes` or blank. `L_gimp` is written by `colormath` on every save.
  `pack_size` is a per-yarn override (blank = use the brand's).
- **Brands** live in a companion file named after the palette (`palette.csv` →
  `palette.brands.csv`): `brand, pack_size` (pieces per pre-cut pack; blank = cut from skeins).
  Mine: Hershner's 320, Red Heart and Loops & Threads cut. Edited in Palette → Brands…; a pack
  size change applies to open projects too (projects look the yarn up in the open palette and
  only fall back to their saved snapshot when it's gone).
- **A yarn is identified by name + brand** (case-insensitive), shown as "Name (Brand)". The old
  name suffixes (RH, L&T) were moved into the brand column and dropped from names (2026-11-13);
  projects saved before that are converted on load ("Gold RH" → Gold, Red Heart).
- Kept sorted by L\*, lightest to darkest. Ties keep their existing order.
- Names otherwise as in my GIMP layers (including any typos).

## Display conventions
- **RGB shown on a 0–100 scale**, like GIMP's picker (254,250,190 → 99.6, 98.0, 74.5).
- **LCh shown to one decimal**, like GIMP.
- Hex as HTML notation, `#RRGGBB`.
- The yarn order runs **lightest to darkest, left to right**, like my GIMP canvas. ← → step
  through it.

## Stage 1: Comparison view
- **Split swatch:** one large square split down the middle, target color on one half and the
  current yarn on the other. No inset or surround, because a surround changes how light the
  inner color looks.
- **Yarn name** shown large as a title above the yarn half. It updates as I step.
- **Readouts** side by side for target and yarn: RGB (0–100), LCh, hex. The yarn also shows its
  position (e.g. `87 / 198`) and ΔL from the target.
- **Target input:** one hex field. Accept `#88A048`, `88a048`, stray spaces. Update as soon as
  the value is a valid hex, without needing Enter.
- When the target changes, jump to the yarn with the **nearest L\***. Ties go to the earlier
  yarn in the list.
- **Navigation:** ← → keys and on-screen buttons step one yarn at a time. A key/button jumps
  back to the nearest match.
- **Neighbor strip:** a few yarns on each side of the current one, with names. Clicking one
  jumps to it.
- **Grayscale toggle:** one key shows both halves as gray at their L\*, for judging lightness
  alone.
- **Copy button** next to the yarn's hex.
- Matching is by **L only**. No hue-weighted (ΔE) matching, because I often have to switch
  color families anyway.
- Load `palette.csv` from next to the script by default.

## Stage 2: Palette manager
The yarn bank is editable from the app, not just a static CSV. Built before the image work so
saved color maps never refer to yarns that vanished.
- **Add** a yarn by hand: name + hex, with a live preview of where it lands in the L order.
- **Edit** a yarn: rename it or fix its hex.
- **Retire** a yarn (e.g. a discontinued SKU): it stays in the file but is hidden from matching, and can be
  restored. **Delete** is only for typos and mistakes.
- **Import** from CSV (same format as `palette.csv`) or GIMP `.gpl`. Both carry name + hex.
  Import always **merges** into the one shared bank; it never removes anything. A summary is
  shown first and nothing changes until I confirm. Names match case-insensitively.
  - New name: added.
  - Same name, same hex: skipped.
  - Same name, different hex (a clash): I choose per yarn, or for all at once: keep mine, take
    the file's, or keep both (the imported one gets a name I type, prefilled e.g. "Light Teal 2").
  - Name matches a retired yarn: offer to restore it (with the file's hex if different).
  - Same hex as an existing yarn under another name (maybe a rename): add as new, skip, or rename
    the existing yarn.
  - Placeholder names ("Index 3", "Untitled") or a name repeated within the file: flagged to
    name or skip.
  - Yarns in my bank but not in the file: left alone.
- **Export** to CSV (everything, including retired) and `.gpl` (active yarns only, since .gpl has no retired flag). `.gpl` lines are `R G B<tab>Name`.
- **File → New palette** (starts empty) and **File → Open palette** switch to a different
  palette file. The last one opened is remembered in `latchwork_settings.json` (git-ignored),
  falling back to `palette.csv`. The manager shows which file is being edited.
- `palette.csv` gets a `retired` column. `L_gimp` is computed by `colormath` for new or edited
  yarns, and the file stays sorted lightest to darkest.

## Stage 3: Image and color map
- Open a pixel-art **PNG or GIF** (Tk's PhotoImage). No JPEG. Warn if the image has
  suspiciously many colors (say over 64), as that suggests it isn't clean pixel art.
- Sizes: usually under 500×500. My biggest so far was 13,120 pixels in total. I don't use
  transparency, but if a pixel is transparent, treat it as no knot and skip it.
- List every distinct image color with its swatch, hex, **pixel (= knot) count** and assigned
  yarn. Pre-fill each one with the nearest-L\* yarn as a suggestion.
- Clicking a row, or a pixel in the image, makes that color the target in the comparison view.
  **Assign** records the current yarn for it.
- One yarn can be assigned to several image colors.
- The hex field still works for trying a color that isn't in the image.
- Colors not yet assigned show their **nearest match** (nearest-L yarn, gray italic, state "nearest") from the open palette;
  suggestions follow palette switches. **Assign (A)** is a toggle for the yarn on screen:
  Assign / ✓ Assigned (press again to undo) / Reassign (assigned to a different yarn).
  Selecting an assigned color jumps to its yarn if the open palette has it.
- Clicking the image selects that color; the selected color is highlighted in the image (others
  faded), toggleable. Typing a hex that is in the image selects its row.
- The last open project is reopened on start (`latchwork_settings.json`).
- **Project file** per rug, e.g. `dragon.latchwork` (small readable JSON). File → New project
  starts from an image; File → Open loads a saved one. Auto-saves on every change. It holds:
  - the image itself, embedded, so moving or renaming the PNG can't break the project
  - each assignment as yarn name **plus its hex at the time**, so the project survives later
    edits, retirements or deletions in the bank
  - settings (spare margin etc.) and, later, progress
- A project is **not tied to a palette**. It matches against whichever palette is open, and I
  may switch palettes mid-project (e.g. load a "sky" palette to assign the sky colors). Each
  assignment is self-contained (name + hex) and is **tagged with the palette file it came
  from**, for information only. Opening a project never forces or prompts a palette switch.

## Stage 4: Preview and planning
- **Yarn-color preview:** an Original / Yarn preview switch above the sidebar image (P). Assigned
  colors show their yarn; **unassigned colors stay original** (my process). A "Mark unassigned"
  toggle stripes the unassigned areas. Grayscale and the selected-color highlight apply too.
- Everything lives on the main screen: a **Plan** tab next to **Colors** in the sidebar; with no
  project open the sidebar shows New project / Open project buttons. Only exports are also in
  the File menu.
- **Merged-color note** when two image colors share a yarn. Informational only, since sometimes
  that's what I want.
- **Yarn quantities:**
  - Each yarn's pack size (brand default or its own): `ceil(knots_with_spare / pack_size)`
    packs. Merged colors are added up before rounding.
  - No pack size (cut from skeins): show the pieces-to-cut count. No skein estimates.
  - Spare margin setting, default 0%.
- **Size**: canvas settings are per project (Plan tab → Change…), defaulting to my setup below;
  "Also use these for new projects" saves new defaults. My setup, 3.75 holes per inch:
  - Finished size = width ÷ 3.75 by height ÷ 3.75 inches.
  - Canvas to cut = (width + 6) × (height + 12) cells, also in inches.
    - Width +6: a 3-cell fold on each side.
    - Height +12: 8 cells at the top that fold over (for the hanging loop), 3 cells at the bottom
      that fold over, plus 1 empty bottom row, because the canvas edge isn't stable enough to
      hook into.
- **Export yarn list** (CSV): yarn name, brand, hex, knots, pack size, packs or pieces, which image colors
  use it, totals.
- Save the yarn-color preview as a PNG (1 pixel per knot, unassigned colors original).
- Only **assigned** colors count toward quantities; unassigned ones are listed as not counted.

## Stage 5: Pattern export (phone and print)
- One **self-contained `.html` file** that works offline on my phone and on a computer.
- **Grid:** one cell per knot, filled with its yarn color. Bold line every 10 cells, row and
  column numbers on the edges. **Rows are numbered from the bottom** (Row 1 = bottom), because I
  hook bottom to top.
- **Symbols:** each yarn gets a symbol (●, ▲, ■, ✚…), drawn on top of the cell color. The
  symbol is black or white, picked by the yarn's L\*. A toggle hides the symbols.
- **Legend:** swatch, yarn name, symbol, knot count. **Tapping a yarn** keeps only that color at
  full strength with symbols. Everything else fades to pale gray without symbols.
- **Zoom:** pinch to zoom, with the grid drawn sharp at every zoom level. No screenshots needed.
- **Done checkmarks** per yarn, remembered on that device.
- **Row tracker:** highlights the whole current row, with no assumed direction within the row.
  It moves up and down one row at a time and is remembered on that device.
- **Print:** an overview page plus one page per color. Large patterns are split across pages
  with labels (A1, A2…).
- Built: File → Export pattern (Ctrl+E). Exports live only in the File menu (no Plan-tab buttons). Unassigned colors appear in
  their original color with a ? symbol (export warns first). Symbols are drawn shapes (20),
  then letters and numbers, so phones never swap them for emoji. Pages are 50 × 70 holes on
  letter paper, A1 = bottom-left. Done marks, row and symbol toggle are saved per pattern in
  the browser's local storage on that device.

## UI polish pass (later, after Stage 5)
One pass at the end instead of piecemeal tweaks.
Done (first pass): grayscale toggle state + badge, single Assign button (main row, disabled when
nothing to assign), image options in one row, selected-color info line, sidebar divider,
palette manager shows file name only and disables Edit/Retire/Delete without a selection,
yarn-ball window icon.
Still open:
- The key hints bar at the bottom of the main window: rethink how shortcuts are shown.
- Neighbor strip: long yarn names wrap to two lines while short ones use one.
- Pattern page: maybe make the Symbols button cycle Auto / Always / Off. Symbols are hidden
  below 7 px cells on purpose (tested: under ~6 px they turn into an unreadable texture).

## Not now
- Yarn inventory (what I own). Maybe later, once the rest is in use.
- Brand filter. I mix brands because no single brand has enough colors.
- Skein estimates.
- Making the pixel art itself, and finishing the rug (binding, backing).

## Tests
- `colormath` reproduces `L_gimp` for **every** row of `palette.csv` (within 1e-4, since the CSV
  stores 4 decimals).
- The GIMP spot-check values above, rounded to one decimal.
- Matching: an exact palette color as the target lands on that yarn, and ties resolve in list
  order.
- Hex parsing accepts the forms above and rejects bad input.
- Stage 2+: palette add/edit/retire/import/export round trips.
- Stage 3+: color counting on a small test image, color map save/load round trip.
- Stage 4+: bag math and canvas size math.
- Stage 5+: pattern data (yarn order, cell indexes, unassigned, transparent) and safe HTML embedding.
