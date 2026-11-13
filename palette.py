"""The yarn bank: load/save palette.csv, GIMP .gpl and CSV import/export, import merge rules.

No Tk in here, so everything is unit-testable.
"""
import csv
import os
import re
import tempfile

from colormath import lightness, parse_hex, rgb_to_lch, to_hex

FIELDS = ["order", "sku", "r", "g", "b", "hex", "L_gimp", "retired"]
_BRANDS = (("L&T", "Loops & Threads"), ("RH", "Red Heart"))
_PLACEHOLDER = re.compile(r"^(|index\s*\d*|untitled.*|unnamed.*|color\s*\d*|colour\s*\d*)$", re.I)


def brand_of(sku):
    s = sku.strip()
    for suffix, name in _BRANDS:
        if s.endswith(" " + suffix):
            return name
    return "Hershner's"


def name_key(name):
    """Names compare case-insensitively and ignore extra spaces."""
    return " ".join(name.split()).casefold()


def clean_name(name):
    return " ".join(name.split())


def is_placeholder(name):
    return bool(_PLACEHOLDER.match(clean_name(name)))


class Yarn:
    def __init__(self, sku, rgb, retired=False):
        self.sku = clean_name(sku)
        self.retired = bool(retired)
        self.set_rgb(rgb)

    def set_rgb(self, rgb):
        self.rgb = tuple(int(c) for c in rgb)
        self.L = lightness(*self.rgb)
        self.hex = to_hex(*self.rgb)
        self.lch = rgb_to_lch(*self.rgb)

    @property
    def brand(self):
        return brand_of(self.sku)

    @property
    def key(self):
        return name_key(self.sku)

    def copy(self):
        return Yarn(self.sku, self.rgb, self.retired)

    def __repr__(self):
        return "Yarn(%r, %s%s)" % (self.sku, self.hex, ", retired" if self.retired else "")


class Entry:
    """A color read from an import file (name may be empty or a placeholder)."""

    def __init__(self, name, rgb, retired=False):
        self.name, self.rgb, self.retired = clean_name(name), tuple(rgb), bool(retired)
        self.hex = to_hex(*self.rgb)


def sort_yarns(yarns):
    """Lightest -> darkest; stable, so ties keep their current order."""
    return sorted(yarns, key=lambda y: -y.L)


def active(yarns):
    return [y for y in yarns if not y.retired]


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "yes", "y", "true", "x", "retired")


# ---------- CSV ----------
def read_csv_entries(path):
    """Rows of a palette-style CSV. Needs a name column (sku or name) and hex or r,g,b."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
        name_col = cols.get("sku") or cols.get("name")
        if not name_col:
            raise ValueError("needs a 'sku' or 'name' column")
        has_rgb = all(k in cols for k in ("r", "g", "b"))
        if not has_rgb and "hex" not in cols:
            raise ValueError("needs a 'hex' column or 'r', 'g', 'b' columns")
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
            out.append(Entry(row[name_col] or "", rgb, _truthy(row.get(cols.get("retired", ""), ""))))
    return out


def load_palette(path):
    entries = read_csv_entries(path)
    for e in entries:
        if not e.name:
            raise ValueError("a row has no name (hex %s)" % e.hex)
    return sort_yarns(Yarn(e.name, e.rgb, e.retired) for e in entries)


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
    def write(fh):
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for i, y in enumerate(sort_yarns(yarns), 1):
            w.writerow([i, y.sku, *y.rgb, y.hex, "%.4f" % y.L, "yes" if y.retired else ""])
    _atomic_write(path, write)


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
    """Active yarns only (.gpl has no retired flag)."""
    def write(fh):
        fh.write("GIMP Palette\nName: %s\nColumns: 16\n#\n" % title)
        for y in sort_yarns(active(yarns)):
            fh.write("%3d %3d %3d\t%s\n" % (y.rgb + (y.sku,)))
    _atomic_write(path, write)


def read_import_file(path):
    if path.lower().endswith(".gpl"):
        return read_gpl(path)
    return read_csv_entries(path)


# ---------- add / edit helpers ----------
def name_problem(name, yarns, exclude=None):
    """Why this name can't be used for a yarn, or None."""
    n = clean_name(name)
    if not n:
        return "Name is empty"
    k = name_key(n)
    for y in yarns:
        if y is not exclude and y.key == k:
            return "Name already used by %s%s" % (y.sku, " (retired)" if y.retired else "")
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
            CLASH: "Name exists with a different color",
            RETIRED: "Matches a retired yarn",
            HEX_MATCH: "Same color as %s" % (self.existing.sku if self.existing else "?"),
            PLACEHOLDER: "Placeholder name, needs a real one",
            DUPLICATE: "Name repeated in the file",
        }[self.kind]


def plan_import(bank, entries):
    by_name = {}
    by_hex = {}
    for y in bank:
        by_name.setdefault(y.key, y)
        by_hex.setdefault(y.hex, y)
    seen, items = set(), []
    for e in entries:
        k = name_key(e.name)
        if is_placeholder(e.name):
            item = ImportItem(e, PLACEHOLDER)
        elif k in seen:
            item = ImportItem(e, DUPLICATE, by_name.get(k))
        elif k in by_name:
            ex = by_name[k]
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


def suggest_name(name, taken_keys):
    base = clean_name(name) or "New yarn"
    n = 2
    while name_key("%s %d" % (base, n)) in taken_keys:
        n += 1
    return "%s %d" % (base, n)


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
                raise ValueError("%s is no longer in the bank" % it.existing.sku)
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
            result.append(Yarn(e.name, e.rgb, e.retired))
        elif a in ("keep_both", "add_named"):
            result.append(Yarn(it.new_name, e.rgb, e.retired))
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
        counts.setdefault(y.key, []).append(y.sku)
    for names in counts.values():
        if len(names) > 1:
            problems.append("Name used more than once: %s" % names[0])
    return problems


def apply_import(bank, items):
    problems = import_problems(bank, items)
    if problems:
        raise ValueError("; ".join(problems))
    return sort_yarns(_apply(bank, items))
