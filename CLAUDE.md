# Latchwork: working notes for Claude

A desktop tool for latch-hook rugs from pixel art. It started as my personal tool and is now
tidied so others can use it too. Keep it simple.

- **[README.md](README.md):** what it does, how to run and use it.
- **[docs/DESIGN.md](docs/DESIGN.md):** color math, matching, file formats, decisions. Keep it up
  to date when behavior changes.
- **In-app help:** `src/latchwork/help.py` (plain-text topics). Keep it in step with features.

## Ground rules
- Python 3.8+ with **Tkinter, standard library only**. Nothing to pip install.
- **Never modify my .xcf files.** If GIMP has to open one, use a scratch copy and never save.
- **Ask instead of guessing** on anything that affects L, the color math, matching or the yarn
  order. L must stay exactly GIMP's L\* (see DESIGN.md); the tests check every palette row.
- Ask before big changes, and stop after each step so I can try it.
- Commit, but don't push; I push myself.

## Layout
- `latchwork.py`: launcher (checks Python/Tkinter, adds `src/` to the path).
  `latchwork.bat` / `.command` / `.sh` wrap it per OS (`.gitattributes` keeps their line endings).
- `src/latchwork/`: the package, relative imports. `app.py` is the main window; `colormath`,
  `palette`, `project`, `plan`, `pattern`, `pixelart`, `settings`, `version` have no Tk (`photos` is the Tk image side);
  `palette_window`, `project_panel`, `carry_window`, `shared_window`, `about_window`, `widgets`, `help` are Tk UI (shared widgets, colors and
  fonts live in `widgets`). `pattern_template.html` is the phone pattern.
- `data/`: palettes (`palette.csv` + `palette.brands.csv`, my real yarns). Yarn photos go in
  `palette.swatches/` next to a palette (git-ignored: shop swatch photos aren't ours to share).
- `settings/`: per-user settings (git-ignored).
- `tests/`: `python -m unittest discover -s tests` (adds `src/` to the path).
- `tools/export_palette.py`: the GIMP 2.10 script that exported the original palette.
- `docs/images/`: README screenshots, made from a neutral demo image (not my rug samples).
  When a change visibly alters a screen shown there (main window, Plan tab, palette manager,
  help, carry-over dialog, larger view, phone and desktop pattern), retake that screenshot the
  same way: same demo image, the real palette, 1300×820 main window (the big green selected,
  with Tea Leaf, Green and Rainforest marked as candidates), larger view at 720×560 with the sun
  highlighted, phone pattern at 390 px wide, desktop pattern at 1280×800 (rows 1–8 hooked, both
  trackers on). Main window and palette manager use a palette copy without photos (what a new
  user gets); the texture shot (larger view, 720×560, Yarn preview + Texture, nothing
  highlighted) and the yarn dialog (editing Light Blue, Loops & Threads) use my photos.
  The carry-over dialog uses two
  earlier rugs from the demo image and the demo with a small house added (two new colors).

## My setup (the defaults)
- Herrschners is pre-cut, 320 pieces per pack; Red Heart and Loops & Threads are cut from skeins.
- Canvas 3.75 holes per inch; borders 3 per side, 8 top (hanging loop), 3 bottom + 1 empty row.
- I hook bottom to top, generally left to right, reading the pattern on an Android phone.
- Color weight 0.5 was fitted on my own rugs (see DESIGN.md).

## Verifying UI changes
- Tk screenshots: PowerShell `System.Drawing` `CopyFromScreen` on the window's root position;
  set the window `-topmost` first or another window gets captured.
- Pattern HTML: headless Edge (`msedge --headless --screenshot`); Edge windows can't go below
  ~500 px wide, so test phone width inside a 390 px iframe.
- Patch scripts: validate every replacement and compile before writing any file.
