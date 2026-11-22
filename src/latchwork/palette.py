"""The yarn bank: yarns + brands, load/save, GIMP .gpl and CSV import/export, import merge rules.

Files: a palette CSV (one row per yarn) and its companion brand list next to it, named after it
(palette.csv -> palette.brands.csv). A yarn is identified by name + brand (case-insensitive).
Yarn photos (optional) live in a folder next to it (palette.csv -> palette.swatches/), with
photos.csv there linking each photo to its yarn; the palette CSV itself never mentions them.
Pack size: a brand's default (blank = cut from skeins), optionally overridden per yarn.

No Tk in here, so everything is unit-testable.
"""
import csv
import os
import re
import shutil
import tempfile

from .colormath import lightness, parse_hex, rgb_to_lab, rgb_to_lch, to_hex

FIELDS = ["order", "sku", "brand", "r", "g", "b", "hex", "L_gimp", "pack_size", "retired"]
BRAND_FIELDS = ["brand", "pack_size"]
PHOTO_FIELDS = ["sku", "brand", "file"]
PHOTOS_FILE = "photos.csv"
PHOTO_TYPES = (".png", ".gif")     # what Tk can read without extra packages
_PLACEHOLDER = re.compile(r"^(|index\s*\d*|untitled.*|unnamed.*|color\s*\d*|colour\s*\d*)$", re.I)

# How palettes made before brands existed were read (from the name suffix). Used only when a
# palette CSV has no brand column, and for projects saved before brands existed.
_LEGACY_SUFFIX = (("L&T", "Loops & Threads"), ("RH", "Red Heart"))
LEGACY_DEFAULT_BRAND = "Herrschners"
LEGACY_PACKS = {"Herrschners": 320, "Red Heart": None, "Loops & Threads": None}


def legacy_brand(sku):
    s = sku.strip()
    for suffix, name in _LEGACY_SUFFIX:
        if s.endswith(" " + suffix):
            return name
    return LEGACY_DEFAULT_BRAND


def strip_legacy_suffix(sku):
    """'Gold RH' -> 'Gold' (the brand now lives in its own column)."""
    s = clean_name(sku)
    for suffix, _ in _LEGACY_SUFFIX:
        if s.endswith(" " + suffix):
            return s[:-len(suffix) - 1].rstrip()
    return s


def legacy_assignment(name):
    """(name, brand, pack) for a yarn saved before brands existed."""
    brand = legacy_brand(name)
    return strip_legacy_suffix(name), brand, LEGACY_PACKS.get(brand)


def name_key(name):
    """Names compare case-insensitively and ignore extra spaces."""
    return " ".join((name or "").split()).casefold()


def clean_name(name):
    return " ".join((name or "").split())


def is_placeholder(name):
    return bool(_PLACEHOLDER.match(clean_name(name)))


def yarn_key(name, brand):
    return (name_key(name), name_key(brand))


def label(name, brand):
    """How a yarn is shown: 'Name (Brand)', or just 'Name' when it has no brand."""
    return "%s (%s)" % (name, brand) if brand else name


def parse_pack(value):
    """'320' -> 320; blank/0/'cut' -> None. Raises ValueError for anything else."""
    s = str(value if value is not None else "").strip().lower()
    if s in ("", "0", "cut", "none", "-"):
        return None
    n = int(float(s))
    if n < 1:
        raise ValueError("pack size must be a positive number")
    return n


class Brand:
    def __init__(self, name, pack=None):
        self.name, self.pack = clean_name(name), pack

    @property
    def key(self):
        return name_key(self.name)

    def copy(self):
        return Brand(self.name, self.pack)

    def __repr__(self):
        return "Brand(%r, %r)" % (self.name, self.pack)


class Yarn:
    def __init__(self, sku, rgb, retired=False, brand="", pack=None, photo=None):
        self.sku = clean_name(sku)
        self.brand = clean_name(brand)
        self.pack = pack          # per-yarn override; None = use the brand's pack size
        self.retired = bool(retired)
        self.photo = photo        # file in the palette's swatch folder ('Red Heart/Gold.png')
        self.set_rgb(rgb)

    def set_rgb(self, rgb):
        self.rgb = tuple(int(c) for c in rgb)
        self.L = lightness(*self.rgb)
        self.hex = to_hex(*self.rgb)
        self.lch = rgb_to_lch(*self.rgb)
        self.lab = rgb_to_lab(*self.rgb)

    @property
    def key(self):
        return yarn_key(self.sku, self.brand)

    @property
    def label(self):
        return label(self.sku, self.brand)

    def copy(self):
        return Yarn(self.sku, self.rgb, self.retired, self.brand, self.pack, self.photo)

    def __repr__(self):
        return "Yarn(%r, %s%s)" % (self.label, self.hex, ", retired" if self.retired else "")


class Entry:
    """A color read from an import file. brand None = the file had no brand information."""

    def __init__(self, name, rgb, retired=False, brand=None, pack=None):
        self.name, self.rgb, self.retired = clean_name(name), tuple(rgb), bool(retired)
        self.brand = None if brand is None else clean_name(brand)
        self.pack = pack
        self.hex = to_hex(*self.rgb)

    @property
    def key(self):
        return yarn_key(self.name, self.brand or "")

    @property
    def label(self):
        return label(self.name, self.brand)


def sort_yarns(yarns):
    """Lightest -> darkest; stable, so ties keep their current order."""
    return sorted(yarns, key=lambda y: -y.L)


def active(yarns):
    return [y for y in yarns if not y.retired]


# ---------- brands ----------
def brand_by_key(brands, name):
    k = name_key(name)
    return next((b for b in brands if b.key == k), None)


def effective_pack(yarn, brands):
    """Pieces per pre-cut pack for this yarn, or None when it's cut from skeins."""
    if yarn.pack:
        return yarn.pack
    b = brand_by_key(brands, yarn.brand)
    return b.pack if b else None


def ensure_brands(brands, yarns):
    """Brand list including every brand a yarn uses (new ones get no pack size)."""
    out = [b.copy() for b in brands]
    for y in yarns:
        if y.brand and not brand_by_key(out, y.brand):
            out.append(Brand(y.brand))
    return sorted(out, key=lambda b: b.name.lower())


def brands_path(palette_path):
    root, _ = os.path.splitext(palette_path)
    return root + ".brands.csv"


def read_brands(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
        if "brand" not in cols:
            raise ValueError("%s needs a 'brand' column" % os.path.basename(path))
        out = []
        for n, row in enumerate(reader, 2):
            name = clean_name(row.get(cols["brand"]))
            if not name:
                continue
            try:
                pack = parse_pack(row.get(cols.get("pack_size", ""), ""))
            except ValueError:
                raise ValueError("%s line %d: bad pack size" % (os.path.basename(path), n))
            if not brand_by_key(out, name):
                out.append(Brand(name, pack))
    return out


# ---------- CSV ----------
def read_csv_entries(path):
    """Rows of a palette-style CSV. Needs a name column (sku or name) and hex or r,g,b.
    Optional: brand, pack_size, retired."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
        name_col = cols.get("sku") or cols.get("name")
        if not name_col:
            raise ValueError("needs a 'sku' or 'name' column")
        has_rgb = all(k in cols for k in ("r", "g", "b"))
        if not has_rgb and "hex" not in cols:
            raise ValueError("needs a 'hex' column or 'r', 'g', 'b' columns")
        brand_col = cols.get("brand")
        out = []
        for n, row in enumerate(reader, 2):
            if not any((v or "").strip() for v in row.values()):
                continue
            try:
                if has_rgb and (row[cols["r"]] or "").strip():
                    rgb = tuple(int(float(row[cols[k]])) for k in ("r", "g", "b"))
                    if not all(0 <= c <= 255 for c in rgb):
                        raise ValueError
                else:
                    rgb = parse_hex(row[cols["hex"]] or "")
                    if rgb is None:
                        raise ValueError
            except (ValueError, KeyError):
                raise ValueError("line %d: can't read a color for %r" % (n, row.get(name_col)))
            try:
                pack = parse_pack(row.get(cols.get("pack_size", ""), ""))
            except ValueError:
                raise ValueError("line %d: bad pack size for %r" % (n, row.get(name_col)))
            out.append(Entry(row[name_col] or "", rgb,
                             str(row.get(cols.get("retired", ""), "") or "").strip().lower()
                             in ("1", "yes", "y", "true", "x", "retired"),
                             brand=(row.get(brand_col) or "") if brand_col else None, pack=pack))
    return out


def load_bank(path):
    """(yarns lightest -> darkest, brands) from a palette CSV and its brand file.

    A palette without a brand column (made before brands existed) gets brands from the old
    name-suffix rules and the old pack sizes, so its numbers stay the same."""
    entries = read_csv_entries(path)
    legacy = any(e.brand is None for e in entries)
    yarns = []
    for e in entries:
        if not e.name:
            raise ValueError("a row has no name (hex %s)" % e.hex)
        brand = legacy_brand(e.name) if e.brand is None else e.brand
        yarns.append(Yarn(e.name, e.rgb, e.retired, brand, e.pack))
    bpath = brands_path(path)
    if os.path.exists(bpath):
        brands = read_brands(bpath)
    elif legacy:
        brands = [Brand(n, p) for n, p in LEGACY_PACKS.items()]
    else:
        brands = []
    attach_photos(path, yarns)
    return sort_yarns(yarns), ensure_brands(brands, yarns)


def load_palette(path):
    return load_bank(path)[0]


def _atomic_write(path, write):
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".latchwork-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            write(fh)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def save_palette(path, yarns):
    """The yarn file only."""
    def write(fh):
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for i, y in enumerate(sort_yarns(yarns), 1):
            w.writerow([i, y.sku, y.brand, *y.rgb, y.hex, "%.4f" % y.L, y.pack or "",
                        "yes" if y.retired else ""])
    _atomic_write(path, write)


def write_brands(path, brands):
    def write(fh):
        w = csv.writer(fh)
        w.writerow(BRAND_FIELDS)
        for b in sorted(brands, key=lambda b: b.name.lower()):
            w.writerow([b.name, b.pack or ""])
    _atomic_write(path, write)


def save_bank(path, yarns, brands):
    """Palette CSV plus its brand file (and the photo list, when there are photos)."""
    save_palette(path, yarns)
    write_brands(brands_path(path), ensure_brands(brands, yarns))
    write_photos(path, yarns)


# ---------- yarn photos ----------
def swatch_dir(palette_path):
    """palette.csv -> palette.swatches (the folder holding that palette's yarn photos)."""
    root, _ = os.path.splitext(os.path.abspath(palette_path))
    return root + ".swatches"


def photos_path(palette_path):
    return os.path.join(swatch_dir(palette_path), PHOTOS_FILE)


def read_photos(palette_path):
    """{yarn key: file} from the palette's photo list ({} when there is none)."""
    path = photos_path(palette_path)
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            f = (row.get("file") or "").strip().replace("\\", "/")
            if f:
                out[yarn_key(row.get("sku"), row.get("brand"))] = f
    return out


def attach_photos(palette_path, yarns):
    photos = read_photos(palette_path)
    for y in yarns:
        y.photo = photos.get(y.key)


def write_photos(palette_path, yarns):
    """Rewrite photos.csv from the yarns. Nothing is created for a palette without photos."""
    rows = sorted(((y.sku, y.brand, y.photo) for y in yarns if y.photo),
                  key=lambda r: (r[1].lower(), r[0].lower()))
    path = photos_path(palette_path)
    if not rows and not os.path.exists(path):
        return

    def write(fh):
        w = csv.writer(fh)
        w.writerow(PHOTO_FIELDS)
        w.writerows(rows)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic_write(path, write)


def photo_file(palette_path, yarn):
    """Full path of the yarn's photo, or None when it has none. It may be missing on disk."""
    if not yarn.photo or not palette_path:
        return None
    return os.path.join(swatch_dir(palette_path), *yarn.photo.split("/"))


def has_photo(palette_path, yarn):
    f = photo_file(palette_path, yarn)
    return bool(f and os.path.isfile(f))


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_file_name(name):
    """A yarn or brand name as a file/folder name (characters Windows forbids become '-')."""
    s = _UNSAFE.sub("-", clean_name(name)).strip(" .")
    return s or "yarn"


def new_photo_name(palette_path, yarn, ext=".png"):
    """Where a new photo for this yarn goes, relative to the swatch folder: 'Brand/Name.png',
    'Brand/Name (2).png' when that's taken."""
    folder = safe_file_name(yarn.brand) if yarn.brand else "No brand"
    base = safe_file_name(yarn.sku)
    root = swatch_dir(palette_path)
    name, n = base + ext, 2
    while os.path.exists(os.path.join(root, folder, name)):
        name, n = "%s (%d)%s" % (base, n, ext), n + 1
    return folder + "/" + name


def tidy_photo_name(palette_path, yarn):
    """A replaced photo is copied in as 'Name (2).png' while the old one still exists; once the
    old one is gone, rename it back to 'Name.png'. Returns the new name, or None if unchanged."""
    if not yarn.photo or "/" not in yarn.photo:
        return None
    folder, current = yarn.photo.rsplit("/", 1)
    want = folder + "/" + safe_file_name(yarn.sku) + os.path.splitext(current)[1]
    src, dst = photo_file(palette_path, yarn), os.path.join(swatch_dir(palette_path),
                                                            *want.split("/"))
    if want == yarn.photo or os.path.exists(dst) or not os.path.isfile(src):
        return None
    os.replace(src, dst)
    return want


def copy_photos(src_palette, dst_palette, yarns):
    """Copy the yarns' photos to another palette's swatch folder (for an export). Photos that
    are missing are dropped from the copies. Returns the yarns to save with the new palette."""
    out = []
    for y in yarns:
        c = y.copy()
        src = photo_file(src_palette, y)
        if src and os.path.isfile(src):
            dst = os.path.join(swatch_dir(dst_palette), *y.photo.split("/"))
            if os.path.normcase(os.path.abspath(src)) != os.path.normcase(os.path.abspath(dst)):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
        else:
            c.photo = None
        out.append(c)
    return out


# ---------- GIMP .gpl ----------
def read_gpl(path):
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        lines = fh.read().splitlines()
    if not lines or lines[0].strip() != "GIMP Palette":
        raise ValueError("not a GIMP palette file (first line isn't 'GIMP Palette')")
    out = []
    for n, line in enumerate(lines[1:], 2):
        s = line.strip()
        if not s or s.startswith("#") or re.match(r"(Name|Columns)\s*:", s, re.I):
            continue
        m = re.match(r"(\d+)\s+(\d+)\s+(\d+)\s*(.*)$", s)
        if not m:
            raise ValueError("line %d: can't read %r" % (n, line))
        rgb = tuple(int(m.group(i)) for i in (1, 2, 3))
        if not all(0 <= c <= 255 for c in rgb):
            raise ValueError("line %d: color value out of range" % n)
        out.append(Entry(m.group(4), rgb))
    return out


def write_gpl(path, yarns, title="Latchwork yarns"):
    """Active yarns only (.gpl has no retired flag). Names include the brand."""
    def write(fh):
        fh.write("GIMP Palette\nName: %s\nColumns: 16\n#\n" % title)
        for y in sort_yarns(active(yarns)):
            fh.write("%3d %3d %3d\t%s\n" % (y.rgb + (y.label,)))
    _atomic_write(path, write)


def read_import_file(path):
    """(entries, brands from a companion brand file or []) for a .gpl or .csv file."""
    if path.lower().endswith(".gpl"):
        return read_gpl(path), []
    bpath = brands_path(path)
    return read_csv_entries(path), (read_brands(bpath) if os.path.exists(bpath) else [])


def needs_brand(entries):
    """True when some imported colors came without brand information (e.g. every .gpl)."""
    return any(e.brand is None for e in entries)


def set_brand(entries, brand):
    for e in entries:
        if e.brand is None:
            e.brand = clean_name(brand)


def merge_brands(brands, incoming):
    """Add brands from an import that aren't known yet; existing brands keep their settings."""
    out = [b.copy() for b in brands]
    for b in incoming:
        if not brand_by_key(out, b.name):
            out.append(b.copy())
    return sorted(out, key=lambda b: b.name.lower())


# ---------- add / edit helpers ----------
def name_problem(name, brand, yarns, exclude=None):
    """Why this name + brand can't be used for a yarn, or None."""
    n = clean_name(name)
    if not n:
        return "Name is empty"
    k = yarn_key(n, brand)
    for y in yarns:
        if y is not exclude and y.key == k:
            return "%s already exists%s" % (y.label, " (retired)" if y.retired else "")
    return None


def placement(yarns, L, exclude=None):
    """Where a yarn with lightness L would sit among the active yarns.

    Returns (position 1-based, total, lighter neighbor or None, darker neighbor or None).
    """
    act = [y for y in sort_yarns(active(yarns)) if y is not exclude]
    i = sum(1 for y in act if y.L >= L)
    return i + 1, len(act) + 1, (act[i - 1] if i > 0 else None), (act[i] if i < len(act) else None)


# ---------- import merge ----------
NEW, SAME, CLASH, RETIRED, HEX_MATCH, PLACEHOLDER, DUPLICATE = (
    "new", "same", "clash", "retired", "hex_match", "placeholder", "duplicate")

ACTION_LABELS = {
    "add": "Add",
    "skip": "Skip",
    "keep_mine": "Keep mine",
    "take_file": "Take the file's color",
    "keep_both": "Keep both (new name)",
    "restore": "Restore with the file's color",
    "restore_same": "Restore",
    "restore_keep_hex": "Restore, keep my color",
    "rename_existing": "Rename my yarn to this name",
    "add_named": "Add with a new name",
}


class ImportItem:
    def __init__(self, entry, kind, existing=None):
        self.entry, self.kind, self.existing = entry, kind, existing
        self.options = self._options()
        self.action = self.options[0]
        self.new_name = ""

    def _options(self):
        if self.kind == NEW:
            return ("add", "skip")
        if self.kind == SAME:
            return ("skip",)
        if self.kind == CLASH:
            return ("keep_mine", "take_file", "keep_both")
        if self.kind == RETIRED:
            if self.existing.hex == self.entry.hex:
                return ("restore_same", "skip")
            return ("restore", "restore_keep_hex", "skip")
        if self.kind == HEX_MATCH:
            return ("skip", "add", "rename_existing")
        return ("skip", "add_named")  # PLACEHOLDER, DUPLICATE

    @property
    def needs_name(self):
        return self.action in ("keep_both", "add_named")

    def describe(self):
        return {
            NEW: "New yarn",
            SAME: "Already in the bank",
            CLASH: "Same name and brand, different color",
            RETIRED: "Matches a retired yarn",
            HEX_MATCH: "Same color as %s" % (self.existing.label if self.existing else "?"),
            PLACEHOLDER: "Placeholder name, needs a real one",
            DUPLICATE: "Name repeated in the file",
        }[self.kind]


def plan_import(bank, entries):
    """Entries must have a brand by now (see needs_brand / set_brand)."""
    by_key, by_hex = {}, {}
    for y in bank:
        by_key.setdefault(y.key, y)
        by_hex.setdefault(y.hex, y)
    seen, items = set(), []
    for e in entries:
        k = e.key
        if is_placeholder(e.name):
            item = ImportItem(e, PLACEHOLDER)
        elif k in seen:
            item = ImportItem(e, DUPLICATE, by_key.get(k))
        elif k in by_key:
            ex = by_key[k]
            if ex.retired and not e.retired:
                kind = RETIRED          # file has it active: offer to restore
            else:
                kind = SAME if ex.hex == e.hex else CLASH
            item = ImportItem(e, kind, ex)
        elif e.hex in by_hex:
            item = ImportItem(e, HEX_MATCH, by_hex[e.hex])
        else:
            item = ImportItem(e, NEW)
        if not is_placeholder(e.name):
            seen.add(k)
        items.append(item)
    return items


def suggest_name(name, brand, taken_keys):
    base = clean_name(name) or "New yarn"
    n = 2
    while yarn_key("%s %d" % (base, n), brand) in taken_keys:
        n += 1
    return "%s %d" % (base, n)


def _new_yarn(name, e):
    return Yarn(name, e.rgb, e.retired, e.brand or "", e.pack)


def _apply(bank, items):
    result = [y.copy() for y in bank]
    copy_of = {id(orig): new for orig, new in zip(bank, result)}
    by_key = {y.key: y for y in reversed(result)}
    for it in items:
        e, a = it.entry, it.action
        ex = None
        if it.existing is not None:
            ex = copy_of.get(id(it.existing)) or by_key.get(it.existing.key)
            if ex is None and a not in ("skip", "keep_mine", "add", "keep_both", "add_named"):
                raise ValueError("%s is no longer in the bank" % it.existing.label)
        if a in ("skip", "keep_mine"):
            continue
        if a == "take_file":
            ex.set_rgb(e.rgb)
        elif a == "restore":
            ex.retired = False
            ex.set_rgb(e.rgb)
        elif a in ("restore_same", "restore_keep_hex"):
            ex.retired = False
        elif a == "rename_existing":
            ex.sku = e.name
        elif a == "add":
            result.append(_new_yarn(e.name, e))
        elif a in ("keep_both", "add_named"):
            result.append(_new_yarn(it.new_name, e))
    return result


def import_problems(bank, items):
    """Human-readable problems that block the import (bad or clashing names)."""
    problems = []
    for it in items:
        if it.needs_name:
            n = clean_name(it.new_name)
            if not n:
                problems.append("%s: type a name" % (it.entry.name or it.entry.hex))
            elif is_placeholder(n):
                problems.append("%s: %r is still a placeholder name" % (it.entry.hex, n))
    counts = {}
    for y in _apply(bank, items):
        counts.setdefault(y.key, []).append(y.label)
    for names in counts.values():
        if len(names) > 1:
            problems.append("Used more than once: %s" % names[0])
    return problems


def apply_import(bank, items):
    problems = import_problems(bank, items)
    if problems:
        raise ValueError("; ".join(problems))
    return sort_yarns(_apply(bank, items))
