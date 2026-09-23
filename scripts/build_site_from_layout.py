# -*- coding: utf-8 -*-
"""Read a plant's real geometry off its issued array-layout PDF into siteModel.

    python scripts/build_site_from_layout.py <array-layout.pdf> <project-key> [sheet]

The overall plant array layout sheet carries named CAD layers, so every element - the ICR
block outlines, the plant and turbine roads, the 33kV/400kV corridors, the boundaries, the
no-go areas and the turbines - is read off its own layer instead of being guessed from
colour, and georeferenced from the sheet's own surveyed E/N callouts.

On the ICR Grouping layer each block outline is drawn as a chain of hair-thin filled bands
(six items per band, item 1 being the edge itself) and one ring is split across several
drawing groups, so it cannot be read group by group. Instead: collect every edge on the
layer, weld the endpoints into a graph and trace the cycles, taking the next edge clockwise
at each node so the corners where two blocks touch split the way they are drawn. Nothing is
inferred or repaired - if a block does not close on the drawing, this fails rather than
inventing an outline.

Writes siteModel into scripts/projects/<project-key>.json. Output is metres, x = east,
y = north, origin at the model south-west corner. Run the data + page build afterwards:
siteModel is published through dash_data.py, so build_dash.py alone will not pick it up.
"""
import sys, os, re, json, math, collections

try:
    import pymupdf
except ImportError:
    sys.exit("pymupdf is required: pip install pymupdf")

HERE = os.path.dirname(os.path.abspath(__file__))

if len(sys.argv) < 3:
    sys.exit(__doc__)
PDF, KEY = sys.argv[1], sys.argv[2]
SHEET = (int(sys.argv[3]) if len(sys.argv) > 3 else 2) - 1     # printed sheet no. -> index
CFGP = os.path.join(HERE, "projects", KEY + ".json")

doc = pymupdf.open(PDF)
page = doc[SHEET]
seglen = lambda a, b: math.hypot(a[0] - b[0], a[1] - b[1])

# the drawing reference as issued, recovered from the file name a browser saved it under
DRAWING = os.path.splitext(os.path.basename(PDF))[0]
DRAWING = re.sub(r"\s*\(\d+\)$", "", DRAWING)          # "... (1)" duplicate-download suffix
DRAWING = re.sub(r"\s+\d+$", "", DRAWING)              # "... 1" ditto
DRAWING = re.sub(r"\s+", " ", DRAWING.replace("_", " ")).strip()


def lin(pairs):
    n = len(pairs); mu = sum(u for u, _ in pairs) / n; mv = sum(v for _, v in pairs) / n
    den = sum((u - mu) ** 2 for u, _ in pairs)
    if den < 1e-9: return None
    a = sum((u - mu) * (v - mv) for u, v in pairs) / den
    b = mv - a * mu
    return a, b, max(abs(a * u + b - v) for u, v in pairs)


# Fit E and N against whichever page axis actually carries them - these sheets are rotated.
E, N, I = [], [], []
for x0, y0, x1, y1, t, *_ in page.get_text("words"):
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    m = re.fullmatch(r"([EN]):(\d{6,7}\.\d+)", t)
    if m: (E if m.group(1) == "E" else N).append((float(m.group(2)), cx, cy))
    if re.fullmatch(r"(?i)ICR[\-–]?\d{1,2}", t): I.append((int(re.sub(r"\D", "", t)), cx, cy))
if not (E and N and I):
    sys.exit("sheet %d carries no E/N callouts or ICR labels - wrong sheet?" % (SHEET + 1))


def best(v):
    o = []
    for ax, s in (("x", 1), ("y", 2)):
        f = lin([(q[s], q[0]) for q in v])
        if f: o.append((f[2], ax, f))
    return min(o)


rE, axE, (aE, bE, _) = best(E)
rN, axN, (aN, bN, _) = best(N)
f2 = lambda x, y: (aE * (x if axE == "x" else y) + bE, aN * (x if axN == "x" else y) + bN)
print("sheet %d georeference: residual E %.3f m / N %.3f m at %.4f m/pt"
      % (SHEET + 1, rE, rN, abs(aE)))
icr = {n: f2(cx, cy) for n, cx, cy in I}
print("ICR labels: %d (ICR-%d..ICR-%d)" % (len(icr), min(icr), max(icr)))

# ============================ blocks =========================================
EDGES = []
for g in page.get_cdrawings():
    if (g.get("layer") or "") != "ICR Grouping": continue
    it = g["items"]
    for k in range(len(it) // 6):
        e = it[1 + 6 * k]                      # item 1 of every six is the edge itself
        if e[0] != "l": continue
        a = f2(e[1][0], e[1][1]); b = f2(e[2][0], e[2][1])
        if seglen(a, b) >= 2.0: EDGES.append((a, b))
print("ICR Grouping edges: %d" % len(EDGES))

WELD = 1.2       # band corners sit ~0.7 m apart, neighbouring blocks ~2.5 m
_cells = collections.defaultdict(list)
nodes = []


def weld(p):
    gx, gy = int(p[0] // WELD), int(p[1] // WELD)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for i in _cells[(gx + dx, gy + dy)]:
                if math.hypot(nodes[i][0] - p[0], nodes[i][1] - p[1]) < WELD: return i
    nodes.append([p[0], p[1]]); i = len(nodes) - 1
    _cells[(gx, gy)].append(i)
    return i


adj = collections.defaultdict(set)
for a, b in EDGES:
    u, v = weld(a), weld(b)
    if u != v: adj[u].add(v); adj[v].add(u)
print("  welded to %d nodes, degrees %s"
      % (len(nodes), dict(sorted(collections.Counter(len(adj[u]) for u in adj).items()))))

ang = {(u, v): math.atan2(nodes[v][1] - nodes[u][1], nodes[v][0] - nodes[u][0])
       for u in adj for v in adj[u]}
order = {u: sorted(adj[u], key=lambda v: ang[(u, v)]) for u in adj}
seen, rings = set(), []
for u in list(adj):
    for v in adj[u]:
        if (u, v) in seen: continue
        ring, a, b = [], u, v
        while True:
            seen.add((a, b)); ring.append(a)
            o = order[b]                              # next edge clockwise from b->a
            a, b = b, o[(o.index(a) - 1) % len(o)]
            if (a, b) == (u, v) or len(ring) > 4000: break
        if len(ring) >= 3: rings.append([nodes[i] for i in ring])
print("  rings traced: %d" % len(rings))


def sarea(r):
    s = 0
    for i in range(len(r)):
        p, q = r[i], r[(i + 1) % len(r)]
        s += p[0] * q[1] - q[0] * p[1]
    return abs(s) / 2


def inside(pt, r):
    x, y = pt; o = False
    for i in range(len(r)):
        p = r[i]; q = r[i - 1]
        if (p[1] > y) != (q[1] > y) and x < (q[0] - p[0]) * (y - p[1]) / (q[1] - p[1]) + p[0]: o = not o
    return o


cell = {}
for r in rings:
    A = sarea(r)
    if A < 20000: continue                                   # 2 ha floor drops slivers
    ins = [n for n, p in icr.items() if inside(p, r)]
    if len(ins) != 1: continue
    n = ins[0]
    if n in cell and cell[n][0] <= A: continue                # keep the tightest cell
    cell[n] = (A, r)
missing = [n for n in sorted(icr) if n not in cell]
print("  ICR cells traced: %d%s" % (len(cell), "  MISSING %s" % missing if missing else ""))
if missing:
    sys.exit("ICR %s did not close on the drawing - inspect the layer before trusting this"
             % missing)

# ---- model window: the block field plus its shoulder ------------------------
ex = [q[0] for _, r in cell.values() for q in r]; ny = [q[1] for _, r in cell.values() for q in r]
E0, N0 = min(ex), min(ny)
E1, N1 = max(ex), max(ny)
loc = lambda e, n: (e - E0, n - N0)
inb = lambda e, n: E0 - 400 <= e <= E1 + 400 and N0 - 400 <= n <= N1 + 400

# ============================ everything else ================================
lines = collections.defaultdict(list); wtgpts = []
MINLEN = {"tl33": 150, "tl400": 25, "nogo": 40}   # the corridors are drawn as hatch
ROADL = {"Plant Road": "road", "Road": "road", "5.2MW WTG Road": "wtgroad",
         "33kV TL Corridor": "tl33", "400kV TL Corridor": "tl400", "400kV TL Route": "tl400",
         "Boundary-Khavda Park": "bnd", "EPC Boundary": "bnd",
         "Boundary-MW Cluster": "cluster", "No Go Area": "nogo"}
for g in page.get_cdrawings():
    lay = g.get("layer") or ""
    if lay in ROADL:
        k = ROADL[lay]
        for i in g["items"]:
            if i[0] != "l": continue
            a = f2(i[1][0], i[1][1]); b = f2(i[2][0], i[2][1])
            if seglen(a, b) < MINLEN.get(k, 20): continue
            if not (inb(*a) or inb(*b)): continue
            lines[k].append([[round(v, 1) for v in loc(*a)], [round(v, 1) for v in loc(*b)]])
    elif lay == "5.2MW WTG-AGEL":
        r = g["rect"]; c = f2((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)
        if inb(*c): wtgpts.append(c)

# turbines: the symbol comes in parts, so merge parts within 90 m
wtg = []
for c in sorted(wtgpts):
    q = loc(*c)
    for w in wtg:
        if math.hypot(w[0] - q[0], w[1] - q[1]) < 90: break
    else: wtg.append([q[0], q[1]])
wtg = [[round(w[0], 1), round(w[1], 1)] for w in wtg]

# the tracker grid on the detail sheets: rows every 7.5 m northward, tables
# 32.28 x 4.78 m - so the rows run east-west across each block
ROW = {"pitch": 7.5, "axis": "x", "tableLen": 32.28, "tableWid": 4.78}


def simplify(poly, tol=1.5):
    out = []
    for q in poly:
        if out and math.hypot(q[0] - out[-1][0], q[1] - out[-1][1]) < tol: continue
        out.append(q)
    while len(out) > 4 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < tol: out.pop()
    return out


blocks = {n: simplify([[round(x, 1), round(y, 1)] for x, y in [loc(*q) for q in v[1]]])
          for n, v in cell.items()}

# tighten the window onto the blocks, keeping the context around them
bxs = [q[0] for v in blocks.values() for q in v]; bys = [q[1] for v in blocks.values() for q in v]
MX0, MX1 = min(bxs) - 180, max(bxs) + 180
MY0, MY1 = min(bys) - 180, max(bys) + 180
shift = lambda q: [round(q[0] - MX0, 1), round(q[1] - MY0, 1)]
for n in blocks: blocks[n] = [shift(q) for q in blocks[n]]
# keep the surrounding context tight - the park boundary and the turbine roads run for
# kilometres around the plant and would otherwise frame the model around empty desert
for k in lines: lines[k] = [[shift(a), shift(b)] for a, b in lines[k]
                            if MX0 - 260 < a[0] < MX1 + 260 and MY0 - 200 < a[1] < MY1 + 200
                            and MX0 - 260 < b[0] < MX1 + 260 and MY0 - 200 < b[1] < MY1 + 200]
wtg = [shift(w) for w in wtg if MX0 - 200 < w[0] < MX1 + 200 and MY0 - 200 < w[1] < MY1 + 200]

sm = collections.OrderedDict()
sm["_comment"] = (
    "Real plant geometry from the issued array layout %s, sheet %d (overall plant array "
    "layout), built by scripts/build_site_from_layout.py. The sheet carries named CAD "
    "layers, so each element is read off its own layer: Plant Road / Road / 5.2MW WTG "
    "Road, 33kV and 400kV TL Corridor, Boundary-Khavda Park, EPC Boundary, Boundary-MW "
    "Cluster, No Go Area and 5.2MW WTG-AGEL. On the ICR Grouping layer each block outline "
    "is a chain of hair-thin filled bands whose ring is split across several drawing "
    "groups, so the block polygons are the cycles of that layer after welding endpoints, "
    "traced by taking the next edge clockwise so the corners where blocks touch split the "
    "way they are drawn. All %d ICRs close on the drawing as issued; no outline is "
    "inferred or repaired. Georeferenced from the sheet's own surveyed E/N callouts "
    "(residual %.2f m E / %.2f m N at %.2f m per point). Row pitch and table size come "
    "from the pile grid on the detail sheets. Metres; x east, y north, origin at the "
    "model's south-west corner."
    % (DRAWING, SHEET + 1, len(blocks), rE, rN, abs(aE)))
sm["units"] = "m"
sm["source"] = "%s, sheet %d" % (DRAWING, SHEET + 1)
sm["origin"] = {"E": round(E0 + MX0, 1), "N": round(N0 + MY0, 1),
                "crs": "UTM 43N (drawing survey grid)"}
sm["extent"] = [round(MX1 - MX0, 1), round(MY1 - MY0, 1)]
sm["row"] = ROW
sm["wtg"] = wtg
sm["wtgHubM"] = 120
sm["wtgRotorM"] = 160
sm["lines"] = {k: v for k, v in lines.items() if v}
sm["blocks"] = []
for n in sorted(blocks):
    poly = blocks[n]
    xs = [q[0] for q in poly]; ys = [q[1] for q in poly]
    sm["blocks"].append({"area": "Block-%02d" % n, "poly": poly,
                         "bbox": [min(xs), min(ys), max(xs), max(ys)],
                         "areaM2": round(abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
                                                 - poly[(i + 1) % len(poly)][0] * poly[i][1]
                                                 for i in range(len(poly)))) / 2)})

print("\nblocks: %d" % len(sm["blocks"]))
for b in sm["blocks"]:
    bb = b["bbox"]
    print("  %s %3d pts  %6.0f x %6.0f m  area %6.1f ha"
          % (b["area"], len(b["poly"]), bb[2] - bb[0], bb[3] - bb[1], b["areaM2"] / 10000))
print("total block area: %.1f ha" % (sum(b["areaM2"] for b in sm["blocks"]) / 1e4))
print("extent: %s  origin: %s" % (sm["extent"], sm["origin"]))
print("lines: %s" % {k: len(v) for k, v in sm["lines"].items()})
print("wtg: %d" % len(sm["wtg"]))

cfg = json.load(open(CFGP, encoding="utf-8"), object_pairs_hook=collections.OrderedDict)
names = {b["area"] for b in sm["blocks"]}
cfg["siteModel"] = sm
with open(CFGP, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(cfg, fh, indent=2, ensure_ascii=False)
print("\nsiteModel -> %s" % CFGP)
print("block names: %s .. %s" % (min(names), max(names)))
print("now rebuild:  python scripts/dash_data.py %s && python scripts/build_dash.py %s"
      % (KEY, KEY))
