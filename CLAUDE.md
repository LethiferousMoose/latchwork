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
- I push myself (the SSH key has a passphrase). Commit, don't push.

## Layout
- `latchwork.py`: launcher (checks Python/Tkinter, adds `src/` to the path).
  `latchwork.bat` / `.command` / `.sh` wrap it per OS (`.gitattributes` keeps their line endings).
- `src/latchwork/`: the package, relative imports. `app.py` is the main window; `colormath`,
  `palette`, `project`, `plan`, `pattern`, `pixelart` have no Tk; `palette_window`,
  `project_panel`, `widgets`, `help` are Tk UI. `pattern_template.html` is the phone pattern.
- `data/`: palettes (`palette.csv` + `palette.brands.csv`, my real yarns).
- `settings/`: per-user settings (git-ignored).
- `tests/`: `python -m unittest discover -s tests` (adds `src/` to the path).
- `tools/export_palette.py`: the GIMP 2.10 script that exported the original palette.
- `docs/images/`: README screenshots, made from a neutral demo image (not my rug samples).

## My setup (the defaults)
- Hershner's is pre-cut, 320 pieces per pack; Red Heart and Loops & Threads are cut from skeins.
- Canvas 3.75 holes per inch; borders 3 per side, 8 top (hanging loop), 3 bottom + 1 empty row.
- I hook bottom to top, generally left to right. Phone: Android (Galaxy S25 Ultra).
- Color weight 0.5 was fitted on my own rugs (see DESIGN.md).

## Verifying UI changes
- Tk screenshots: PowerShell `System.Drawing` `CopyFromScreen` on the window's root position;
  set the window `-topmost` first or another window gets captured.
- Pattern HTML: headless Edge (`msedge --headless --screenshot`); Edge windows can't go below
  ~500 px wide, so test phone width inside a 390 px iframe.
- Patch scripts: validate every replacement and compile before writing any file.
