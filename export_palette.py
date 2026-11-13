# GIMP 2.10 Python-Fu (Python 2). Dumps every layer of an .xcf (name, offsets, mean RGB,
# per-channel std dev, uniformity) to OUT_DIR/raw_layers.csv plus OUT_DIR/image_info.txt.
# It never saves the image; still, point XCF_IN at a COPY of your .xcf to be safe.
# palette.csv was then built from raw_layers.csv (Colors group only, minus Cafe RH, sorted by L*).
#
# Run headless (one line, PowerShell):
#   & "C:\Program Files\GIMP 2\bin\gimp-console-2.10.exe" -idf --batch-interpreter python-fu-eval
#     -b "exec(open(r'C:\path\to\export_palette.py').read())" -b "pdb.gimp_quit(1)"
import math, struct

XCF_IN = r"C:\path\to\AllColors_copy.xcf"
OUT_DIR = r"C:\path\to\output_dir"

def stats(layer):
    w, h = layer.width, layer.height
    rgn = layer.get_pixel_rgn(0, 0, w, h, False, False)
    data = rgn[0:w, 0:h]
    bpp = rgn.bpp
    n = w * h
    nch = 3 if bpp >= 3 else 1
    sums = [0.0] * 4; sq = [0.0] * 4
    a_min = 255
    distinct = set()
    for i in xrange(n):
        px = struct.unpack_from('%dB' % bpp, data, i * bpp)
        if len(distinct) < 50:
            distinct.add(px)
        for c in range(bpp):
            sums[c] += px[c]; sq[c] += px[c] * px[c]
        if bpp in (2, 4):
            a_min = min(a_min, px[-1])
    mean = [sums[c] / n for c in range(bpp)]
    sd = [math.sqrt(max(0.0, sq[c] / n - mean[c] ** 2)) for c in range(bpp)]
    return w, h, bpp, mean, sd, a_min, len(distinct), sorted(distinct)[0]

img = pdb.gimp_file_load(XCF_IN, XCF_IN)
info = open(OUT_DIR + r"\image_info.txt", "w")
info.write("gimp_version=%s\n" % str(pdb.gimp_version()))
info.write("size=%dx%d base_type=%d\n" % (img.width, img.height, img.base_type))
for attr in ("precision",):
    try:
        info.write("%s=%r\n" % (attr, getattr(img, attr)))
    except Exception as e:
        info.write("%s_err=%s\n" % (attr, e))
for proc in ("gimp_image_get_precision", "gimp_image_get_component_type"):
    try:
        info.write("%s=%r\n" % (proc, getattr(pdb, proc)(img)))
    except Exception as e:
        info.write("%s_err=%s\n" % (proc, e))
try:
    prof = pdb.gimp_image_get_color_profile(img)
    info.write("color_profile_bytes=%d\n" % len(prof[1] if isinstance(prof, tuple) else prof))
except Exception as e:
    info.write("color_profile_err=%s\n" % e)
for p in ("icc-profile", "icc-profile-name"):
    par = img.parasite_find(p)
    info.write("parasite %s: %s\n" % (p, ("%d bytes" % len(par.data)) if par else "none"))

def walk(layers, path, out):
    for idx, L in enumerate(layers):
        is_group = pdb.gimp_item_is_group(L)
        info.write("%s[%d] %r group=%s offs=%s size=%dx%d visible=%s mode=%s opacity=%.1f\n" % (
            path, idx, L.name, bool(is_group), L.offsets, L.width, L.height, L.visible, L.mode, L.opacity))
        if is_group:
            walk(L.layers, path + "/" + L.name, out)
        else:
            out.append((path, idx, L))

leaves = []
walk(img.layers, "", leaves)

csv = open(OUT_DIR + r"\raw_layers.csv", "w")
csv.write("group,stack_index,name,off_x,off_y,w,h,bpp,r,g,b,sd_r,sd_g,sd_b,alpha_min,distinct,first_px,visible,mode,opacity\n")
for path, idx, L in leaves:
    w, h, bpp, mean, sd, amin, nd, fp = stats(L)
    ox, oy = L.offsets
    vals = (mean + [0, 0])[:3] if bpp >= 3 else [mean[0]] * 3
    sds = (sd + [0, 0])[:3] if bpp >= 3 else [sd[0]] * 3
    csv.write('"%s",%d,"%s",%d,%d,%d,%d,%d,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%d,%d,"%s",%s,%s,%.1f\n' % (
        path, idx, L.name.replace('"', "'"), ox, oy, w, h, bpp, vals[0], vals[1], vals[2],
        sds[0], sds[1], sds[2], amin, nd, fp, L.visible, L.mode, L.opacity))
csv.close(); info.close()
pdb.gimp_image_delete(img)
