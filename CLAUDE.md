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
- `pattern_template.html`: template for the exported phone/print pattern.
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
  (dead SKU, replaced by Cafe Latte RH; it is the hidden layer).
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
- `palette.csv` columns: `order, sku, r, g, b, hex, L_gimp, color_stddev`. RGB is 0–255.
  198 yarns.
- It is currently in my GIMP layer order. **First task of Stage 1: re-sort it by L\*,
  lightest to darkest. Ties keep the layer order.**
- Brand comes from the name suffix: **`RH` = Red Heart, `L&T` = Loops & Threads, no suffix =
  Hershner's.** Use names exactly as they are in the layers (including any typos).

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
- **Retire** a yarn (like Cafe RH): it stays in the file but is hidden from matching, and can be
  restored. **Delete** is only for typos and mistakes.
- **Import** from CSV (same format as `palette.csv`) or GIMP `.gpl`. Both carry name + hex.
  Flag duplicate names instead of silently overwriting.
- **Export** to CSV and `.gpl`, with name + hex.
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
- **Auto-save** the color map next to the image (e.g. `my_art.latchwork.csv`) and reload it when
  the image is opened again.

## Stage 4: Preview and planning
- **Yarn-color preview:** the image redrawn with the assigned yarn colors, next to the original.
  The grayscale toggle applies here too.
- **Merged-color note** when two image colors share a yarn. Informational only, since sometimes
  that's what I want.
- **Yarn quantities:**
  - Hershner's (no suffix): bags of 320 pre-cut pieces, `ceil(knots / 320)`.
  - Red Heart / Loops & Threads: show the pieces-to-cut count (= knots). No skein estimates;
    I cut from skeins myself.
  - Spare margin setting, default 0%.
- **Size**, for 3.75 holes per inch mesh (I always use this):
  - Finished size = width ÷ 3.75 by height ÷ 3.75 inches.
  - Canvas to cut = (width + 6) × (height + 12) cells, also in inches.
    - Width +6: a 3-cell fold on each side.
    - Height +12: 8 cells at the top that fold over (for the hanging loop), 3 cells at the bottom
      that fold over, plus 1 empty bottom row, because the canvas edge isn't stable enough to
      hook into.
- **Export yarn list** (CSV): yarn name, brand, hex, knots, bags or pieces, which image colors
  use it, totals.
- Optionally save the yarn-color preview as a PNG.

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
