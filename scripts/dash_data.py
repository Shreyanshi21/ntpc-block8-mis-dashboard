# -*- coding: utf-8 -*-
"""Dashboard data builder — LIVE from the VisiLean PowerBI APIs, for any project.
   python dash_data.py <key>  reads scripts/projects/<key>.json (NTPC keeps ntpc_dash_data_v2.py).
   Tokens come from env (VL_TOKEN_TASK / VL_TOKEN_HISTORY / VL_TOKEN_CONSTRAINTS,
   set as GitHub Actions secrets) or a local vl_tokens.json next to this script
   (never committed). Pure Python. Emits scripts/ntpc_dashboard_data_v2.json."""
import sys, io, json, os, re, datetime, urllib.request
from collections import defaultdict, deque, Counter
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass
SCR = os.path.dirname(os.path.abspath(__file__))

BASE = "https://app.visilean.net/pb/PowerBiAPI/resource/powerBi/getData/visilean"
# ---------- project ----------
# One builder, many projects: `python dash_data.py sjvn` reads scripts/projects/sjvn.json.
# Everything that names the project or its schedule vocabulary comes from that file; a
# key it does not set keeps the NTPC behaviour this script was written with.
PKEY = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DASH_PROJECT", "")).strip().lower()
if not PKEY:
    raise SystemExit("usage: dash_data.py <project key>   (scripts/projects/<key>.json)")
CFG = json.load(open(os.path.join(SCR, "projects", PKEY + ".json"), encoding="utf-8"))
PROJECT = CFG["projectId"]

def _tokens():
    # env first (Actions secrets; a per-project VL_TOKEN_TASK_<KEY> wins over the plain
    # name), then the gitignored scripts/vl_tokens.json keyed by project
    K = PKEY.upper()
    e = lambda n: os.environ.get(n + "_" + K, "") or os.environ.get(n, "")
    t = {"task": e("VL_TOKEN_TASK"), "history": e("VL_TOKEN_HISTORY"),
         "constraintLog": e("VL_TOKEN_CONSTRAINTS")}
    if not t["task"]:
        f = os.path.join(SCR, "vl_tokens.json")
        if os.path.exists(f):
            j = json.load(open(f, encoding="utf-8"))
            t.update(j.get(PKEY) or {k: v for k, v in j.items() if isinstance(v, str)})
    if not t["task"]:
        raise SystemExit("no VisiLean tokens: set VL_TOKEN_* env vars or scripts/vl_tokens.json")
    return t

TOKENS = _tokens()

def fetch(kind, attempts=3):
    tp = "task" if kind == "history" else kind
    url = f"{BASE}?accessToken={TOKENS[kind]}&projectId={PROJECT}&type={tp}"
    if kind == "history":
        # these flags are what make activityHistory come back populated - it is the
        # audit trail the variance reasons are written into
        url += ("&IncludeStatusChange=true&IncludeReschedule=true"
                "&IncludeQuantities=true&IncludeConstraintNotes=true")
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "VisiLean-MIS-v2"})
            return json.loads(urllib.request.urlopen(req, timeout=120).read().decode("utf-8", errors="replace"))
        except Exception as e:
            last = e
            print(f"fetch {kind} attempt {i+1}/{attempts} failed: {e}")
            if i + 1 < attempts:
                import time as _t; _t.sleep(15 * (i + 1))
    raise last

print("fetching VisiLean APIs...")
try:
    TASKS = fetch("task")
    # Only the task feed is essential. A project may not have a constraints report
    # provisioned (no token, or the endpoint 500s); the Constraints tab then simply
    # has nothing to list, exactly as it does before any constraint is raised.
    try:
        CONS = fetch("constraintLog", 2)
    except Exception as ce:
        print("constraints feed unavailable, the constraints log will be empty:", ce)
        CONS = []
    try:
        HIST = fetch("history")
    except Exception as he:
        print("history feed unavailable, variance reasons will be empty:", he)
        HIST = []
except Exception as e:
    # transient VisiLean outage: skip this cycle cleanly; the next run recovers
    print(f"SKIP this cycle - VisiLean API unreachable after retries: {e}")
    sys.exit(0)
print("tasks:", len(TASKS), "| constraints:", len(CONS), "| history:", len(HIST))
RELS = json.load(open(os.path.join(SCR, CFG.get("relationsFile", "vl_relations.json")), encoding="utf-8"))

# ---------- calendar ----------
_cal = CFG.get("calendar") or {}
START = datetime.date.fromisoformat(_cal.get("startDate", "2026-05-07"))
TODAY = datetime.date.today()
WEEKLY_OFF = set(_cal.get("weeklyOff", [6]))          # python weekday(): Monday=0 .. Sunday=6
# a project with no baseline set in VisiLean reads its planned dates AS the baseline
BASELINE_PLANNED = (CFG.get("baselineMode", "visilean") == "planned")
NULL_LEVELS = {re.sub(r"[^a-z0-9]", "", str(x).lower()) for x in (CFG.get("nullLevels") or [])}
# Some projects carry no "Level N" custom fields at all - the WBS lives only in the
# task hierarchy. levelsFromChain reads the levels off the parent chain instead
# (root first); levelsFromChainDrop skips the leading names that are the project
# itself, so Level 1 lands on the same grouping the Level fields would have held.
CHAIN_LEVELS = bool(CFG.get("levelsFromChain"))
CHAIN_DROP = int(CFG.get("levelsFromChainDrop", 1))
wdates = []
d = START
while len(wdates) < 1200:
    if d.weekday() not in WEEKLY_OFF:
        wdates.append(d)
    d += datetime.timedelta(days=1)
STATUS_WD = max(i for i, dt in enumerate(wdates) if dt <= TODAY) + 1

def pdate(s):
    s = (s or "").strip()
    if not s: return None
    try: return datetime.datetime.strptime(s.split(" ")[0], "%d/%m/%Y").date()
    except Exception: return None

def wd_s(dt_): return next((i for i, x in enumerate(wdates) if x >= dt_), 0)
def wd_f(dt_): return max((i for i, x in enumerate(wdates) if x <= dt_), default=0) + 1
norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s or "").lower())

def money(s):
    try: return float(re.sub(r"[^\d.]", "", s or "")) if s and re.search(r"\d", s) else 0.0
    except Exception: return 0.0

recs = {}
milestones_raw = []
NA_SKIPPED = []
NA_UIDS = set()
GUID = {t.get("guid"): t for t in TASKS if t.get("guid")}

def chain_names(t):
    """Parent names from the project root down to this task's parent."""
    out, seen, cur = [], set(), t
    while True:
        g = cur.get("parentGUID")
        if not g or g in seen:
            break
        seen.add(g)
        p = GUID.get(g)
        if p is None:
            break
        out.append((p.get("taskName") or "").strip())
        cur = p
    return list(reversed(out))

# Rows created directly in VisiLean - the drawing revisions R0/R1/R2 - carry no custom
# fields, so they have no Levels, no Department and no Package, and every classifier
# below would fall through. They belong wherever their parent sits, so borrow the
# nearest classified ancestor's fields. Classification only: dates, %, status and
# weightage stay the row's own, and Weightage/Cost are never inherited because a
# parent's weight repeated across its revisions would be counted several times.
def _has_levels(cf):
    return any((cf or {}).get("Level %d" % i) for i in range(1, 8))

def classify_cf(t, depth=0):
    cf = t.get("customField") or {}
    if _has_levels(cf) or depth >= 6:
        return cf, ""
    p = GUID.get(t.get("parentGUID"))
    if p is None:
        return cf, ""
    up, _ = classify_cf(p, depth + 1)
    if not _has_levels(up):
        return cf, ""
    out = {k: v for k, v in up.items() if k not in ("Weightage", "Cost")}
    out.update({k: v for k, v in cf.items() if v not in (None, "")})
    return out, str(p.get("taskName") or "")

INHERITED = []
_synth = [0]
# A P6-driven project carries an activity CODE as its externalId ("S06A-CC-10220"),
# not a number. Map those codes onto stable integers - sorted, so every rebuild
# assigns the same uid - and reuse the map for the history feed and the relations
# sidecar, whose endpoints are then written as codes too. Numeric externalIds
# (MSP UniqueID, as NTPC and SJVN use) pass straight through.
_CODE_UID = {}
_codes = sorted({str(t.get("externalId") or "").strip() for t in TASKS
                 if str(t.get("externalId") or "").strip()
                 and not str(t.get("externalId")).strip().lstrip("-").isdigit()})
if _codes:
    _CODE_UID = {c: i + 1 for i, c in enumerate(_codes)}
    print(f"externalIds are activity codes: {len(_CODE_UID)} mapped to stable uids")

def uid_of(x):
    s = str(x if x is not None else "").strip()
    if not s: return None
    try: return int(s)
    except Exception: return _CODE_UID.get(s)

# relations may reference either form; resolve them once and drop links whose ends
# are not tasks we publish
RELS = [[uid_of(a), uid_of(b), c, d] for a, b, c, d in RELS]
RELS = [r for r in RELS if r[0] is not None and r[1] is not None]

for t in TASKS:
    uid = uid_of(t.get("externalId"))
    if uid is None:
        # Created directly in VisiLean, so no MSP UniqueID (drawing-revision rows
        # R0/R1/R2 etc). VisiLean counts these in "All Tasks" -> so do we.
        _synth[0] += 1
        uid = -_synth[0]
    cf, inherited_from = classify_cf(t)
    if inherited_from and not t.get("parent"):
        INHERITED.append((str(t.get("taskId") or ""), str(t.get("taskName") or ""), inherited_from))
    L = [cf.get(f"Level {i}", "") or "" for i in range(1, 8)]
    if CHAIN_LEVELS and not any(str(v).strip() for v in L):
        L = (chain_names(t)[CHAIN_DROP:] + [""] * 7)[:7]
    # Some schedules write a literal placeholder where a WBS level is unused (P6
    # exports "0"); treat those as empty so they never become a package or section.
    if NULL_LEVELS: L = ["" if norm(v) in NULL_LEVELS else v for v in L]
    bs, bf = pdate(t.get("baselineStartDate")), pdate(t.get("baselineEndDate"))
    # "not baselined": VisiLean counts these in All Tasks but leaves them out of
    # Completed / Delayed, because there is no baseline to measure them against.
    # Rows created straight in VisiLean (drawing revisions R0/R1/R2) look like this.
    nodate = 1 if (bs is None or bf is None) else 0
    if bs is None or bf is None:
        bs2, bf2 = pdate(t.get("plannedStartDate")), pdate(t.get("plannedEndDate"))
        bs, bf = bs or bs2, bf or bf2
        # planned-as-baseline projects: nothing is flagged un-baselined for that reason alone
        if BASELINE_PLANNED and bs is not None and bf is not None:
            nodate = 0
    if bs is None or bf is None:
        # Undated row: inherit the parent's window so it can be placed, and flag it
        # so every date-driven metric skips it. VisiLean does the same - such rows
        # appear in All Tasks but not in Completed / Delayed.
        p = GUID.get(t.get("parentGUID"))
        pbs = pbf = None
        if p is not None:
            pbs = pdate(p.get("baselineStartDate")) or pdate(p.get("plannedStartDate"))
            pbf = pdate(p.get("baselineEndDate")) or pdate(p.get("plannedEndDate"))
        bs = bs or pbs or START
        bf = bf or pbf or bs
    r = {"uid": uid, "name": t.get("taskName") or "", "parent": bool(t.get("parent")),
         "L": L, "atype": cf.get("Activity Type", ""), "pkgcf": cf.get("Package", ""),
         "deptcf": cf.get("Department", ""),
         "owner": cf.get("Owner.", "") or cf.get("Owner", ""),
         "tid": str(t.get("taskId") or ""), "org": str(t.get("organisation") or "").strip(),
         "guid": t.get("guid"), "pguid": t.get("parentGUID"),
         # no MSP externalId -> raised in VisiLean after the baseline was set
         "pb": 0 if str(t.get("externalId") or "").strip() else 1, "sup": 0,
         "assignee": t.get("owner") or "", "loc": t.get("location") or "Off-site / Office",
         "bES": wd_s(bs), "bEF": wd_f(bf),
         "pES": (wd_s(pdate(t.get("plannedStartDate"))) if pdate(t.get("plannedStartDate")) else None),
         "pEF": (wd_f(pdate(t.get("plannedEndDate"))) if pdate(t.get("plannedEndDate")) else None),
         "aS": pdate(t.get("actualStartDate")), "aF": pdate(t.get("actualEndDate")),
         "pct": float(t.get("percentComplete") or 0),
         "vls": t.get("status") or "Not Committed",
         "qty": t.get("totalQuantity"), "uom": t.get("quantityUnits") or "",
         "cost": money(cf.get("Cost")),
         # KP 26-Aug: progress weight comes from VisiLean's own "Weightage" custom
         # field - the approved Rev-2 model, which sums to ~100 across the project.
         # Cost is kept only for the budget card.
         "wt": money(cf.get("Weightage")), "nd": nodate,
         "note": t.get("notes") or "", "desc": t.get("description") or "",
         "crit": (cf.get("Critical Activity") or ""),
         # a revision row is named "R1"; its schedule stage is its parent's
         "stagename": inherited_from,
         "psd": (pdate(t.get("plannedStartDate")) or bs),
         "ped": (pdate(t.get("plannedEndDate")) or bf), }
    try: r["dur"] = max(0.0, float(t.get("baselineDuration") or t.get("plannedDuration") or 0))
    except Exception: r["dur"] = max(0.0, float(r["bEF"] - r["bES"]))
    if r["dur"] == 0 and not r["parent"]:
        r["dur"] = max(0.0, float(r["bEF"] - r["bES"]))
    if (L[0] or "").startswith("Key Milestones") or re.match(r"^MS-\d", r["name"]):
        if not r["parent"]: milestones_raw.append(r)
        continue
    # KP rule 26-Aug: an activity whose trade is "Not Applicable" is out of scope for
    # this project. Dropping it here removes it from every count, every progress and
    # weightage calculation, and every table - not just from the views.
    if norm(t.get("trade")) in ("notapplicable", "na"):
        NA_SKIPPED.append(r["name"])
        NA_UIDS.add(uid)
        continue
    recs[uid] = r

leafs = {u: r for u, r in recs.items() if not r["parent"]}

# ---------- post-baseline revisions: weight follows the current revision ----------
# KP 31-Aug: a superseded revision no longer represents the deliverable, so the
# deliverable's approved weight sits on the LATEST revision and the earlier ones carry
# none. Order is taken from the planned finish, then creation order - never from the
# name, which already includes "RO" and "DBR R1 Submission".
_pb_by_parent = defaultdict(list)
for r in leafs.values():
    if r["pb"] and r["pguid"]:
        _pb_by_parent[r["pguid"]].append(r)
REV_GROUPS, REV_MIXED = [], []
for pg, ch in _pb_by_parent.items():
    p = GUID.get(pg)
    if p is None: continue
    # only when the whole set under this parent is post-baseline; a parent that still
    # has MSP children has already distributed its weight to them
    sibs = [t for t in TASKS if t.get("parentGUID") == pg and not t.get("parent")]
    if any(str(t.get("externalId") or "").strip() for t in sibs):
        REV_MIXED.append(str(p.get("taskName") or ""))
        continue
    ch.sort(key=lambda r: (r["ped"] or datetime.date(1900, 1, 1), int(r["tid"] or 0)))
    pw = money((p.get("customField") or {}).get("Weightage"))
    for r in ch:
        r["wt"] = 0.0      # a weightage typed onto a revision row is ignored
        r["sup"] = 1
    ch[-1]["wt"] = pw
    ch[-1]["sup"] = 0
    ch[-1]["revof"] = str(p.get("taskName") or "")
    REV_GROUPS.append((str(p.get("taskId") or ""), [r["name"] for r in ch], pw))
if REV_GROUPS:
    print("post-baseline revisions: %d rows under %d deliverables; the approved weight "
          "follows the current revision" % (sum(len(x[1]) for x in REV_GROUPS), len(REV_GROUPS)))
if REV_MIXED:
    print("  NOTE: left alone (parent still has MSP-imported children):", ", ".join(REV_MIXED[:5]))
print("usable leaves:", len(leafs), "| milestones:", len(milestones_raw),
      "| excluded (trade = Not Applicable):", len(NA_SKIPPED))
if INHERITED:
    print("classification inherited from the parent for %d rows with no custom fields:"
          % len(INHERITED), ", ".join("%s %s<-%s" % x for x in INHERITED[:4]),
          "..." if len(INHERITED) > 4 else "")

# ---------- forecast = VisiLean PLANNED dates, verbatim (KP rule 17-Aug-2026) ----------
# No dashboard-side re-forecasting: VisiLean owns scheduling. Planned start/end
# from the API ARE the forecast; baseline start/end are the baseline.
succ = defaultdict(list)
for pu, su, code, lag in RELS:
    if pu in leafs and su in leafs:
        succ[pu].append((su, code, lag))
fES, fEF = {}, {}
for u, r in leafs.items():
    fES[u] = float(r["pES"] if r["pES"] is not None else r["bES"])
    fEF[u] = float(r["pEF"] if r["pEF"] is not None else r["bEF"])
    if fEF[u] < fES[u]:
        fEF[u] = fES[u]
print(f"forecast = VisiLean planned dates; finish {max(fEF.values()):.0f} wd = {wdates[int(round(max(fEF.values())))-1]}")

# ---------- total float, computed on VisiLean planned dates ----------
END = max(fEF.values())
LF = {u: float(END) for u in leafs}
order = sorted(leafs, key=lambda u: -fEF[u])
for _ in range(3):
    for u in order:
        for (v, code, lag) in succ[u]:
            dv = leafs[v]["dur"]
            if code == "SS": cand = LF[v] - dv - lag + leafs[u]["dur"]
            elif code == "FF": cand = LF[v] - lag
            else: cand = LF[v] - dv - lag
            if cand < LF[u]: LF[u] = cand
TF = {u: max(0.0, LF[u] - fEF[u]) for u in leafs}
# How much of the schedule is actually wired into the logic network. The relations
# sidecar is a static capture; when activities are deleted in VisiLean the chains
# break and float stops being meaningful, so publish the coverage alongside it.
_inlogic = set()
for pu, su, code, lag in RELS:
    if pu in leafs and su in leafs: _inlogic.add(pu); _inlogic.add(su)
LOGIC_COV = round(100.0 * len(_inlogic) / max(1, len(leafs)), 1)
print(f"logic coverage: {LOGIC_COV}% of leaves are in the relation network")

# ---------- classification ----------
DEPTS = [("initiation", "Project Initiation"), ("engineering", "Design & Engineering"),
         ("quality", "Quality Assurance"), ("supply", "Procurement - Supply"),
         ("services", "Procurement - Services"),
         ("regulatory", "Regulatory & Statutory"), ("execution", "Execution & Construction"),
         ("tnc", "Testing & Commissioning"), ("hoto", "HOTO (Handover)")]
UNCLASSIFIED = []
# project vocabulary hooks (each falls back to the NTPC behaviour when absent)
DEPT_MAP = {"/".join(norm(p) for p in k.split("/")): v
            for k, v in (CFG.get("departments") or {}).items() if not k.startswith("_")}
ATYPE_FROM_DEPT = bool(CFG.get("activityTypeFromDepartment"))
# A project may name its Activity Type values differently ("Execution" for what the
# dashboard calls Construction). Map them onto the four the EPC card counts on;
# anything unmapped passes through and lands in "other activity types".
ATYPE_MAP = {norm(k): v for k, v in (CFG.get("activityTypeMap") or {}).items()
             if not k.startswith("_")}
def atype_of(dept, raw):
    if ATYPE_FROM_DEPT: return ATYPE_BY_DEPT.get(dept, "") or raw
    return ATYPE_MAP.get(norm(raw), raw)
# EPC discipline per department, for projects with no "Activity Type" field. Every
# department is covered so the EPC card's "other activity types" line stays readable.
ATYPE_BY_DEPT = {"engineering": "Engineering", "supply": "Procurement - Supply",
                 "services": "Procurement - Services", "execution": "Construction",
                 "tnc": "Construction", "regulatory": "Statutory & Approvals",
                 "liaisoning": "Statutory & Approvals", "quality": "Quality",
                 "initiation": "Project Management", "hoto": "Handover"}
AREA_L3_RE = re.compile(CFG["areaFromLevel3"], re.I) if CFG.get("areaFromLevel3") else None
AREA_LABEL = CFG.get("areaLabel", "Area-%s")
PKG_FROM_FIELD = CFG.get("packageFromField", True)
ITEM_JOIN_L4 = bool(CFG.get("itemJoinLevel4"))
def dept_of(r):
    dcf = norm(re.sub(r"^\s*\d+\s*", "", r.get("deptcf") or ""))
    l1 = dcf if dcf else norm(r["L"][0])
    l2 = norm(r["L"][1])
    # the project's own map first: "Department" -> key, or "Department/Level2-prefix"
    # for a split such as Procurement/Service Vendors
    if DEPT_MAP:
        for k, v in DEPT_MAP.items():
            if "/" in k:
                a, b = k.split("/", 1)
                if a == l1 and b and l2.startswith(b): return v
        if l1 in DEPT_MAP: return DEPT_MAP[l1]
    if l1.startswith("testing"): return "tnc"
    if l1.startswith("projectinitiation"): return "initiation"
    if l1.startswith("design"): return "engineering"
    if l1.startswith("quality"): return "quality"
    if l1.startswith("procurement"): return "services" if "services" in l2 else "supply"
    if l1.startswith("regulatory") or l1.startswith("liaisoning"): return "regulatory"
    if l1.startswith("hoto"): return "hoto"
    if l1.startswith("execution"):
        return "tnc" if (r["L"][2] or "").startswith("Testing & Commissioning") else "execution"
    # Nothing matched. Report it rather than quietly filing the row under Project
    # Initiation, which is how R0/R1 revisions ended up in the wrong department.
    UNCLASSIFIED.append((r.get("tid", ""), r["name"]))
    return "initiation"

ENG_STAGE = [("asbuilt", "As-Built"), ("gfcissuance", "GFC"), ("finalacceptance", "Acceptance"),
             ("submissiontoclient", "Submission"), ("internalapproval", "Int. Approval"),
             ("internalchecking", "Int. Check"), ("drafting", "Drafting"), ("finalreport", "Acceptance")]
PROC_STAGE = [
    (("rfppreparation", "fqap", "mqap", "additionalvendor", "vendorapprovalfromclient", "prfraising",
      "floatingofrfp", "vendorproposal", "technicalbid", "commercialbid", "cspreparation", "eauction"), "Tender"),
    (("managementapproval", "pqplacement", "poplacement", "abg", "advancepayment"), "Order & Advance"),
    (("designdocument",), "Vendor Docs"),
    (("manufacturingclearance", "stageinspection", "predispatch", "assigninspector", "collectshare",
      "inspectionreport", "submitquality", "compliancereport", "mdccissuance", "sharemdcc"), "Mfg & Quality"),
    (("jmsabstract", "dispatchofmaterial", "incomingmaterial", "grnatsite"), "Delivery / JMS"),
    (("paymentprocess", "invoicebooking", "finalpaymentprocess"), "Payments"),
]
EXEC_STAGE = [
    (("boundaryfencing", "roadconstruction", "drainage", "landallocation", "siteclearance",
      "civilworks", "platformconstruction", "foundation", "watchtower", "securit"), "Civil & Foundations"),
    (("pilefoundation", "pile"), "Civil & Foundations"),
    (("modulemountingstructureinstallation", "mmsinstallation", "mms"), "MMS & Module"),
    (("moduleinstallation", "module"), "MMS & Module"),
    (("dcstring", "dcpower", "dccable", "scb", "stringcombiner"), "DC Works"),
    (("htcable", "accable", "acht", "jointing", "termination"), "AC / HT Works"),
    (("earthing", "lainstallation", "lightning"), "Earthing & LA"),
    (("equipmentinstallation", "wmsinstallation", "abtmeter", "peripherylight",
      "icrlights", "nomenclature", "idtfoundation"), "Equipment"),
    (("poolingsubstation", "pss", "switchyard", "bay"), "PSS & Switchyard"),
    (("rfi", "ncr", "siteobservation", "sitestorage", "testingwitness", "verificationofchecklist"), "Quality Process"),
]
SUB_MAP = [
    (("rfppreparation", "draftingconceptual", "internalcheckingof", "internalapproval",
      "submissiontocustomer", "finalacceptanceof"), "Design"),
    (("additionalvendorapprovallist", "vendorapprovalfromclient", "prfraising", "floatingofrfp",
      "vendorproposalcollection", "technicalbidevaluation", "commercialbidevaluation",
      "cspreparation", "eauction"), "Tender"),
    (("managementapproval", "pqplacement", "poplacement"), "PO"),
    (("abg", "advancepaymentrelease"), "Advance"),
    (("designdocumentreview", "designdocumentapproval", "fqapreview", "mqapreview",
      "fqapapproval", "mqapapproval"), "Vendor Docs"),
    (("manufacturingclearance", "stageinspection"), "Mfg"),
    (("predispatch", "assigninspector", "collectshare", "inspectionreport", "submitquality",
      "compliancereport", "mdccissuance", "sharemdcc", "jmsabstract"), "Inspection / MDCC-JMS"),
    (("dispatchofmaterial", "incomingmaterialinspection"), "Dispatch"),
    (("grnatsite",), "At Site"),
    (("paymentprocess", "invoicebooking", "finalpaymentprocess"), "Payment"),
]
# a project may replace the schedule vocabulary wholesale: lists of [[keys...], stage]
def _stages(name, default):
    v = CFG.get(name)
    return [(tuple(k), s) for k, s in v] if v else default
if CFG.get("engStage"):
    ENG_STAGE = [(k, v) for k, v in CFG["engStage"]]
PROC_STAGE = _stages("procStage", PROC_STAGE)
EXEC_STAGE = _stages("execStage", EXEC_STAGE)
SUB_MAP = _stages("subMap", SUB_MAP)
def strip_html(x):
    x = re.sub(r"<br\s*/?>", " ", x or "")
    x = re.sub(r"</p>", " ", x)
    x = re.sub(r"<[^>]+>", "", x)
    for a, b in (("&amp;", "&"), ("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'")):
        x = x.replace(a, b)
    return re.sub(r"\s+", " ", x).strip()

BLOCK_RE = re.compile(r"(?i)^block[\s-]*(no)?\d+")
# A Level-4 value that appears under many different Packages is a process step,
# not a deliverable - "MQAP" sits under 32 supply packages, "Field Quality Plan &
# HSE" under 4. Only a Level 4 that belongs to a single Package is a real package
# item; anything shared falls back to the Package field so stages never surface as
# packages in the pipeline table.
L4_SPAN = defaultdict(set)
for _r in leafs.values():
    if _r["L"][3] and _r["pkgcf"]: L4_SPAN[_r["L"][3]].add(_r["pkgcf"])
rows = []
for r in sorted(leafs.values(), key=lambda x: x["uid"]):
    u = r["uid"]; dept = dept_of(r); ln = norm(r["name"]); L = r["L"]
    area = r["loc"] or "Off-site / Office"
    if AREA_L3_RE:
        # areas named in the WBS ("Feeder-2 - 50 MW" / "Feeder-4 (L&G)") or in the
        # location ("Feeder 2 - ...") - whichever carries the number
        m3 = AREA_L3_RE.match(L[2] or "") or AREA_L3_RE.match(L[3] or "") or AREA_L3_RE.match(r["loc"] or "")
        area = (AREA_LABEL % m3.group(1)) if m3 else "Off-site / Office"
    # Package = VisiLean 'Package' custom field VERBATIM (KP field-match rule 18-Aug);
    # Level-derived fallback only for rows where the field is empty in VisiLean.
    # Section = WBS Level 2, i.e. the level directly under the department, for every
    # department. The department page's section dropdown then sits one level above its
    # package dropdown (Level 3 / the Package field) instead of both listing Level 3.
    # For Supply and Services, Level 2 already reads "Supply" / "EPCC & I&C Services".
    sec = L[1] or L[0]
    if dept in ("supply", "services"):
        fb = L[2] or L[1]
    elif dept == "engineering":
        fb = L[3] or L[2] or L[1]
    elif dept in ("execution", "tnc"):
        cand = [x for x in L[2:6] if x and not BLOCK_RE.match(x) and norm(x) != "construction"]
        fb = cand[-1] if cand else (L[3] or L[2] or L[1])
    else:
        fb = L[1] or L[0]
    pkg = (r["pkgcf"] if PKG_FROM_FIELD else "") or fb
    # Deepest WBS level that exists for this row. In Design & Engineering the Package
    # field carries the Level-3 group, so the Level-4 deliverable is the real package;
    # where Level 4 is blank this falls back to the Package field unchanged.
    if ITEM_JOIN_L4 and dept in ("supply", "services") and L[3]:
        # SJVN: the deliverable is the package x feeder ("Inverter (SPLY) · Feeder-2 (INV)")
        item = (str(pkg) + " · " + L[3])[:80]
    else:
        item = L[3] if (L[3] and len(L4_SPAN.get(L[3], ())) == 1) else pkg
    stage = ""
    # "R1" matches no stage; the revision belongs to the stage of the activity it
    # revises, so match on the parent's name where one was inherited
    ln = norm(r.get("stagename") or "") or ln
    if dept == "engineering":
        stage = next((v for kk, v in ENG_STAGE if kk in ln), "Drafting" if "drafting" in ln else "")
    elif dept in ("supply", "services"):
        for keys, v in PROC_STAGE:
            if any(k in ln for k in keys): stage = v; break
    elif dept in ("execution", "tnc"):
        full = norm(pkg) + ln
        for keys, v in EXEC_STAGE:
            if any(k in full for k in keys): stage = v; break
        stage = stage or ("T&C" if dept == "tnc" else "Other Site Works")
        if dept == "tnc": stage = "T&C"
    sub = ""
    if dept in ("supply", "services"):
        sub = next((v for keys, v in SUB_MAP if any(k in ln for k in keys)), "Design")
    elif dept == "engineering":
        sub = stage
    vs = r["vls"]
    # Delayed (VisiLean-equivalent): not complete, and it should have started or
    # finished by today. Matches VisiLean's "Delayed Tasks" counter. The old test
    # (forecast finish >= 4 days past baseline) always read 0, because VisiLean's
    # planned dates equal the baseline until the schedule is actually rescheduled.
    dly = 0
    # VisiLean counts an activity whether or not it is baselined, so we do too.
    if r["pct"] < 100:
        if r["ped"] < TODAY or (r["psd"] < TODAY and r["pct"] == 0): dly = 1
    if r["pct"] >= 100 or vs == "Complete": state = "done"
    elif r["pct"] > 0 or vs in ("Started", "Warning", "Stopped"): state = "inprog"
    elif r["bES"] < STATUS_WD: state = "late"
    else: state = "future"
    rows.append([dept, atype_of(dept, r["atype"]), area, str(pkg)[:70], str(sec)[:60], stage,
                 r["name"][:70], int(r["bES"]), int(r["bEF"]), int(round(fES[u])), int(round(fEF[u])),
                 round(r["pct"]), round(r["dur"], 1), r["qty"], r["uom"][:14],
                 int(round(TF.get(u, 0))), state,
                 (r["assignee"] or "")[:30], sub, round(r["cost"]), len(rows), vs,
                 (r["owner"] or "")[:40], r["nd"], dly, str(item)[:80], round(r["wt"], 6),
                 1 if str(r.get("crit") or "").strip().lower().startswith("y") else 0,
                 strip_html(r["desc"])[:120], strip_html(r["note"])[:220],
                 # actual finish, so completed work counts from when it finished
                 (wd_f(r["aF"]) if r["aF"] else None),
                 r["tid"], " > ".join([x for x in r["L"][:5] if x])[:170],
                 ("" if r["org"].lower() == "none" else r["org"])[:60], u,
                 r["pb"], r["sup"]])
n_crit = sum(1 for x in rows if x[15] <= 5 and x[16] != "done" and not x[23])

ms = []
for m in sorted(milestones_raw, key=lambda x: x["name"]):
    bw = m["bEF"]; fw = bw + max(0, STATUS_WD - 78)
    ms.append({"name": m["name"], "b": bw, "f": fw, "slip": fw - bw,
               "status": "done" if m["pct"] >= 100 else ("ontrack" if fw - bw <= 6 else ("watch" if fw - bw <= 15 else "late"))})

months = []
# month-ends from the calendar start to a month past the latest finish
_lf = max(max(x[8], x[10]) for x in rows) if rows else 1
_lastfin = wdates[min(len(wdates) - 1, max(0, int(_lf) - 1))]
m0 = (START.replace(day=1) + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
_mend = (_lastfin.replace(day=1) + datetime.timedelta(days=62)).replace(day=1) - datetime.timedelta(days=1)
while m0 <= _mend:
    months.append({"label": m0.strftime("%b-%y"), "wd": max((i for i, dt in enumerate(wdates) if dt <= m0), default=0) + 1})
    m0 = (m0 + datetime.timedelta(days=46)).replace(day=1) - datetime.timedelta(days=1)

WT_I = 26   # "wt" column - VisiLean's Weightage custom field (asserted below)
def w_of(x): return x[WT_I] if x[WT_I] and x[WT_I] > 0 else 0.0
WSUM = sum(w_of(x) for x in rows)
W = (lambda x: w_of(x)) if WSUM > 0 else (lambda x: x[12])
WT = sum(W(x) for x in rows) or 1.0
plan_pct = sum(min(1.0, max(0.0, (STATUS_WD - x[7]) / max(0.5, x[12]))) * W(x) for x in rows) / WT
# Same formula the dashboard uses for the gauge, so the published figure and the
# gauge cannot disagree: progress is capped by how much of the activity has actually
# elapsed, which is what stops work reported before its scheduled start from counting.
AEF_I = 30   # "aef" column (asserted against the contract below)
def _prog(x):
    return x[11] / 100.0
def _elapsed(x):
    if _prog(x) >= 1.0:   # finished: counts from the date it actually finished
        fin = x[AEF_I] if x[AEF_I] is not None else x[10]
        return 1.0 if STATUS_WD >= fin else 0.0
    return max(0.0, (STATUS_WD - x[9]) / max(0.5, x[12]))
act_pct = sum(min(_prog(x), _elapsed(x)) * W(x) for x in rows) / WT
bfin = max(x[8] for x in rows); ffin = max(x[10] for x in rows)
NOW_UTC = datetime.datetime.now(datetime.timezone.utc)
IST_NOW = NOW_UTC.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))

meta = {"statusDate": TODAY.strftime("%d-%b-%Y"), "statusWd": STATUS_WD, "startDate": START.strftime("%d-%b-%Y"),
        "project": CFG.get("name", "KPIGEL-NTPC Bikaner Block 8 · 200 MW"),
        "baselineFinishWd": bfin, "forecastFinishWd": ffin,
        "baselineFinish": wdates[bfin - 1].strftime("%d-%b-%y"),
        "forecastFinish": wdates[ffin - 1].strftime("%d-%b-%y"),
        "codBaseline": wdates[bfin - 1].isoformat(), "codForecast": wdates[ffin - 1].isoformat(),
        "statusIso": TODAY.isoformat(),
        "plan": round(100 * plan_pct, 1), "act": round(100 * act_pct, 1),
        "spi": round(act_pct / plan_pct, 2) if plan_pct > 0.0005 else 0,
        "svPts": round(100 * (act_pct - plan_pct), 1),
        "svPct": round(100 * (act_pct - plan_pct) / plan_pct, 1) if plan_pct > 0.0005 else 0,
        "delayDays": ffin - bfin, "critical": n_crit,
        "done": sum(1 for x in rows if x[16] == "done"),
        "inprog": sum(1 for x in rows if x[16] == "inprog"),
        "late": sum(1 for x in rows if x[16] == "late"),
        "delayed": sum(1 for x in rows if x[24]), "logicCoverage": LOGIC_COV,
        "wtSum": round(sum(w_of(x) for x in rows), 3),
        "wtCoverage": round(100.0 * sum(1 for x in rows if w_of(x) > 0) / max(1, len(rows)), 1),
        "wtMissing": sum(1 for x in rows if not w_of(x)),
        "naExcluded": len(NA_SKIPPED), "naReasonRecords": 0,
        "postBaseline": sum(1 for x in rows if x[35]),
        "superseded": sum(1 for x in rows if x[36]),
        "revDeliverables": len(REV_GROUPS),
        "total": len(rows), "totalTasks": len(rows) + len(ms),
        "undated": sum(1 for x in rows if x[23]),
        "source": "VisiLean live API",
        # KP reads this in India, so the stamp is IST. generatedAtEpoch is the same
        # instant in unix seconds, used by the page to work out how old the data is.
        "generatedAt": IST_NOW.strftime("%d-%b-%Y %H:%M IST"),
        "generatedAtEpoch": int(NOW_UTC.timestamp())}

# ---------- supply package delivery, straight off VisiLean's summary rows -------
# KP rule 25-Aug: the Long Lead table's Baseline / Forecast delivery must equal the
# dates VisiLean shows on the package summary row under Procurement > Supply.
_kids = defaultdict(list)
for t in TASKS:
    if t.get("parentGUID"): _kids[t["parentGUID"]].append(t)

def _descendants(t, depth=0):
    if depth > 6: return
    for c in _kids.get(t.get("guid"), []):
        yield c
        for g in _descendants(c, depth + 1): yield g

SUPPLY_DELIV = {}
_ss = CFG.get("supplySummary") or {"level1": "Procurement & Vendor Documents", "level2": "Supply",
                                   "level3Blank": True, "packageFrom": "field"}
for t in TASKS:
    cfx = t.get("customField") or {}
    if not t.get("parent"): continue
    if (cfx.get("Level 1") or "").strip() != _ss["level1"]: continue
    if (cfx.get("Level 2") or "").strip() != _ss["level2"]: continue
    l3 = (cfx.get("Level 3") or "").strip()
    if _ss.get("level3Blank", True):
        # NTPC: Level 3 is set on the nested MQAP sub-summaries; the package summary leaves it blank
        if l3: continue
    else:
        # projects whose package summary carries Level 3 but no Level 4
        if not l3 or (cfx.get("Level 4") or "").strip(): continue
    if (t.get("taskName") or "").strip() in ("", "Supply"): continue
    if _ss.get("packageFrom", "field") == "level3":
        pkg = l3
    elif _ss.get("packageFrom") == "name":
        # SJVN: the package summary is named after the package ("PV Module (SPLY)")
        pkg = (t.get("taskName") or "").strip()
    else:
        pkgs = Counter()
        for d in _descendants(t):
            p = ((d.get("customField") or {}).get("Package") or "").strip()
            if p: pkgs[p] += 1
        if not pkgs: continue
        pkg = pkgs.most_common(1)[0][0]
    be, pe = pdate(t.get("baselineEndDate")), pdate(t.get("plannedEndDate"))
    if be is None and pe is None: continue
    # key must match the row's pkg column, which is truncated the same way
    SUPPLY_DELIV[str(pkg)[:70]] = {"b": wd_f(be or pe), "f": wd_f(pe or be)}
print("supply package delivery dates from VisiLean summaries:", len(SUPPLY_DELIV))
if UNCLASSIFIED:
    print("WARNING: %d rows matched no department rule and defaulted to Project Initiation:"
          % len(UNCLASSIFIED), ", ".join("%s %s" % x for x in UNCLASSIFIED[:5]))

cons = []
# The constraint log carries activityGuid - the activity the constraint was raised
# against. Resolve it to the same uid the activity rows use, so the Constraints Log
# page can open that activity's property panel, and carry the name for projects
# where the activity itself is not published (parent/summary rows). uid_of() is used
# rather than int() so a schedule whose externalIds are activity codes resolves too.
for c in CONS:
    ag = (c.get("activityGuid") or "").strip()
    at = GUID.get(ag)
    auid = uid_of(at.get("externalId")) if at is not None else None
    cons.append({"id": c.get("constrainId"), "title": c.get("title") or "", "desc": (c.get("discription") or "")[:200],
                 "author": c.get("author") or "", "owner": c.get("owner") or "",
                 "cat": (c.get("category") or "").strip() or "Uncategorised",
                 "pri": c.get("priority") or "—",
                 "created": c.get("creationDate") or "", "target": c.get("targetDate") or "",
                 "committed": c.get("commitmentDate") or "", "completed": (c.get("completionDate") or "").strip(),
                 "open": not (c.get("completionDate") or "").strip(),
                 "trade": (c.get("trade") or "").strip(), "zone": (c.get("zone") or "").strip(),
                 "note": (c.get("note") or "")[:200],
                 "act": auid, "actName": (at.get("taskName") if at is not None else "") or ""})
print("constraints: %d, of which %d resolve to an activity"
      % (len(cons), sum(1 for c in cons if c.get("act") is not None)))

# ---------- variance reasons (from the task-history audit trail) ----------
# Event phrasings VisiLean writes into activityHistory. The first four are the ones
# that represent a schedule variance.
EVENTS = [
    (r"started late",            "latestart",  "Started late"),
    (r"completed late",          "latefinish", "Completed late"),
    (r"(?:Start|End) Date changed", "resched", "Rescheduled"),
    (r"\bstopped\b",             "stopped",    "Stopped"),
    (r"set to 'Not Ready'",      "notready",   "Set to Not Ready"),
    (r"started early",           "startearly", "Started early"),
    (r"completed early",         "finishearly","Completed early"),
    (r"started on time",         "startontime","Started on time"),
    (r"completed on time",       "finishontime","Completed on time"),
    (r"bulk completed",          "bulk",       "Bulk completed"),
    (r"was forced ready",        "forcedready","Forced ready"),
    (r"Constraint '",            "constraint", "Constraint raised"),
]
# What keeps an activity in the reasons feed at all (so its notes stay readable).
VARIANCE_KINDS = {"latestart", "latefinish", "resched", "notready", "stopped"}
# What VisiLean counts as a variance record, and the Reason Category it files it under.
REASON_CATEGORY = {"latestart": "Late Started", "latefinish": "Late Completed"}

# VisiLean wraps the text the user typed with the note type; strip it before the
# category is read, or "Late completion note" is mistaken for a party.
NOTE_PREFIX_RE = re.compile(
    r"\b(late start note|late completion note|completion note|start note|"
    r"stopped note|rejection note|note added to task[^:]*|note added|note)\s*:\s*", re.I)

# The team writes reasons as "<Responsible party>: <Category>".
PARTIES = ["KP", "Client", "Vendor", "NTPC", "SJVN", "External", "Consultant",
           "Contractor", "Sub-contractor", "Subcontractor", "PMC", "Site", "Store"]
PARTY_RE = re.compile(r"\b(" + "|".join(PARTIES) + r")\s*:\s*([A-Za-z][A-Za-z&/ -]{1,24})", re.I)
# VisiLean also defines reasons with no responsible party, listed on their own in
# Project Settings > Custom Reasons.
STANDALONE = ["Predecessor", "Weather", "Rework", "Design Change", "Statutory"]
STANDALONE_RE = re.compile(r"^\s*(" + "|".join(STANDALONE) + r")\s*\.?\s*$", re.I)
CAT_CANON = {"machinery": "Machine", "machines": "Machine", "machine": "Machine",
             "materials": "Material", "material": "Material",
             "manpower": "Manpower", "labour": "Manpower", "labor": "Manpower",
             "approval": "Approval", "approvals": "Approval",
             "external": "External", "design": "Design", "drawing": "Design",
             "weather": "Weather", "payment": "Payment", "permit": "Statutory"}


def canon_cat(c):
    c = re.sub(r"\s+", " ", (c or "").strip(" .,-")).strip()
    return CAT_CANON.get(c.lower(), c[:24].title() if c else "")

def split_events(hist):
    """Cut the audit trail into one chunk per event, keeping the note with it."""
    txt = strip_html(hist)
    if not txt: return []
    idx = [m.start() for m in re.finditer(r"(?=Task '|Note added to task '|Constraint ')", txt)]
    if not idx: idx = [0]
    chunks = [txt[a:b] for a, b in zip(idx, idx[1:] + [len(txt)])]
    out = []
    for ch in chunks:
        kind, label = "other", "Other"
        for pat, k, lab in EVENTS:
            if re.search(pat, ch, re.I): kind, label = k, lab; break
        m = re.search(r"Note added:\s*(.*)$", ch, re.I) or \
            re.search(r"Note:\s*(.*)$", ch, re.I) or \
            re.search(r"by [^:]+:\s*(.*)$", ch, re.I)
        note = NOTE_PREFIX_RE.sub("", (m.group(1).strip() if m else "")).strip()
        # history rows are joined with " | ", so anything past the first bar belongs
        # to the next row, not to this event's note
        note = note.split(" | ")[0].strip(" |").strip()
        who = ""
        w = re.search(r"\bby ([A-Za-z][\w.\- ]{1,30}?)(?=[.:,]|$)", ch)
        if w: who = w.group(1).strip()
        out.append({"kind": kind, "label": label, "note": note, "by": who})
    return out

# Each history row carries one event, so keeping only the longest row loses the
# others - the stop on task 44699 sat behind a longer "started early" row. Merge
# every distinct trail an activity has.
_hist_seen = defaultdict(list)
for h in HIST:
    hu = uid_of(h.get("externalId"))
    if hu is None: continue
    a = strip_html(str(h.get("activityHistory") or ""))
    if not a: continue
    if a not in _hist_seen[hu]: _hist_seen[hu].append(a)
# Join with a bar, not a space: some history rows are a bare word ("Construction",
# "Engineering"), and a space let the last row's trailing category run into the next
# row's first word - "KP: Manpower" + "Construction" read as one category.
hist_by_uid = {u: " | ".join(v) for u, v in _hist_seen.items()}

# Late events on Not Applicable activities: counted, not shown. This is the whole of
# the difference between this card and VisiLean's own variance export.
na_reason_records = 0
for _u in NA_UIDS:
    for _e in split_events(hist_by_uid.get(_u, "")):
        if _e["kind"] in REASON_CATEGORY and _e["note"]:
            na_reason_records += len(PARTY_RE.findall(_e["note"])) or \
                                 (1 if STANDALONE_RE.match(_e["note"]) else 0)

reasons = []
cat_tally = Counter()
for r in sorted(leafs.values(), key=lambda x: x["uid"]):
    u = r["uid"]
    evs = split_events(hist_by_uid.get(u, ""))
    if not evs: continue
    cats, seen = [], set()
    for e in evs:
        if not e["note"]: continue
        # one record per (event, reason) pair, as in VisiLean's export: an activity
        # that started late and finished late for the same reason counts twice
        rc = REASON_CATEGORY.get(e["kind"], "")
        hits = PARTY_RE.findall(e["note"])
        solo = STANDALONE_RE.match(e["note"])
        if hits:
            for party, cat in hits:
                cc = canon_cat(cat)
                if not cc: continue
                pty = party.upper() if party.upper() == "KP" else party.title()
                # the reason is the whole "<party>: <category>" string, exactly as it
                # reads in VisiLean's Custom Reasons list - one consolidated label
                full = pty + ": " + cc
                if (e["kind"], full) in seen: continue
                seen.add((e["kind"], full))
                cats.append({"party": pty, "cat": full, "kind": e["kind"], "rc": rc,
                             "label": e["label"], "text": e["note"][:300]})
        elif solo:
            full = solo.group(1).title()
            if (e["kind"], full) not in seen:
                seen.add((e["kind"], full))
                cats.append({"party": "", "cat": full, "kind": e["kind"], "rc": rc,
                             "label": e["label"], "text": e["note"][:300]})
    var = [e for e in evs if e["kind"] in VARIANCE_KINDS]
    if not cats and not var: continue          # nothing variance-related to report
    for c in cats:
        if c["rc"]: cat_tally[c["rc"] + " / " + c["cat"]] += 1
    wbs = " > ".join([x for x in r["L"][:5] if x])
    reasons.append({
        "uid": u, "tid": r["tid"], "org": r["org"], "name": r["name"][:110], "dept": dept_of(r),
        "type": r["atype"], "pkg": str(r["pkgcf"] or "")[:70],
        "wbs": wbs[:170], "area": r["loc"],
        "owner": (r["assignee"] or "")[:40], "ownship": (r["owner"] or "")[:60],
        "vls": r["vls"], "pct": round(r["pct"]),
        "bES": int(r["bES"]), "bEF": int(r["bEF"]),
        "fES": int(round(fES[u])), "fEF": int(round(fEF[u])),
        "aES": (wd_s(r["aS"]) if r["aS"] else None),
        "aEF": (wd_f(r["aF"]) if r["aF"] else None),
        "sSlip": (wd_s(r["aS"]) if r["aS"] else int(round(fES[u]))) - int(r["bES"]),
        "fSlip": (wd_f(r["aF"]) if r["aF"] else int(round(fEF[u]))) - int(r["bEF"]),
        "tf": int(round(TF.get(u, 0))),
        "crit": str(r.get("crit") or "").strip().lower().startswith("y"),
        "cats": cats,
        "events": [{"label": e["label"], "kind": e["kind"], "by": e["by"], "text": e["note"][:300]}
                   for e in evs if e["kind"] in VARIANCE_KINDS or e["note"]][:8],
        "desc": strip_html(r["desc"])[:400],
    })
print("variance reasons:", sum(cat_tally.values()), "records on", len(reasons),
      "activities | Late Started:", sum(v for k, v in cat_tally.items() if k.startswith("Late Started")),
      "| Late Completed:", sum(v for k, v in cat_tally.items() if k.startswith("Late Completed")))
print("  categories:", dict(cat_tally))
meta["naReasonRecords"] = na_reason_records   # meta is built before this point
print("  excluded from the card (trade = Not Applicable):", na_reason_records, "records")

# Milestones shaped like activity rows, purely so the All-activities drill can list
# them beside the tasks. They stay out of `rows`, so no count or progress changes.
ms_rows = []
for r in sorted(milestones_raw, key=lambda x: x["uid"]):
    u = r["uid"]
    ms_rows.append([
        dept_of(r), r["atype"], r["loc"], str(r["pkgcf"] or "")[:70],
        str(r["L"][1] or r["L"][0])[:60], "Milestone", r["name"][:70],
        int(r["bES"]), int(r["bEF"]),
        int(r["pES"] if r["pES"] is not None else r["bES"]),
        int(r["pEF"] if r["pEF"] is not None else r["bEF"]),
        round(r["pct"]), round(r["dur"], 1), r["qty"], r["uom"][:14], 0,
        ("done" if r["pct"] >= 100 else "future"),
        (r["assignee"] or "")[:30], "", round(r["cost"]), len(ms_rows), r["vls"],
        (r["owner"] or "")[:40], r["nd"], 0, r["name"][:80], round(r["wt"], 6),
        1 if str(r.get("crit") or "").strip().lower().startswith("y") else 0,
        strip_html(r["desc"])[:120], strip_html(r["note"])[:220],
        (wd_f(r["aF"]) if r["aF"] else None),
        r["tid"], " > ".join([x for x in r["L"][:5] if x])[:170],
        ("" if r["org"].lower() == "none" else r["org"])[:60], u, r["pb"], r["sup"]])

# ---------- predecessor network for the activity panel ----------
# Shown, not calculated with: float still comes from the same links above. Only links
# whose successor is on the dashboard are kept, and a predecessor that is not itself a
# dashboard row gets an entry in predMeta so it can still be named.
on_board = set(leafs) | {m["uid"] for m in milestones_raw}
preds, succs = defaultdict(list), defaultdict(list)
_pseen = set()
for pu, su, code, lag in RELS:
    if su not in on_board or pu == su: continue
    if (pu, su) in _pseen: continue
    _pseen.add((pu, su))
    preds[su].append([pu, code, round(float(lag or 0), 1)])
    succs[pu].append(su)

TASK_BY_UID = {}
for _t in TASKS:
    try: TASK_BY_UID[int(_t.get("externalId"))] = _t
    except Exception: pass

pred_meta = {}
for pu in {p[0] for v in preds.values() for p in v}:
    if pu in on_board: continue
    t = TASK_BY_UID.get(pu)
    if not t: continue
    pc = float(t.get("percentComplete") or 0)
    pe = pdate(t.get("plannedEndDate")) or pdate(t.get("baselineEndDate"))
    ps = pdate(t.get("plannedStartDate")) or pdate(t.get("baselineStartDate"))
    dl = 1 if (pc < 100 and ((pe and pe < TODAY) or (ps and ps < TODAY and pc == 0))) else 0
    pred_meta[pu] = [str(t.get("taskName") or "")[:70], round(pc),
                     str(t.get("status") or ""),
                     (wd_f(pdate(t.get("baselineEndDate"))) if pdate(t.get("baselineEndDate")) else None),
                     (wd_f(pe) if pe else None), dl]
print("logic network: %d activities have a predecessor | %d predecessors are off-dashboard"
      % (len(preds), len(pred_meta)))

_dept_used = {x[0] for x in rows}
DATA = {"meta": meta, "months": months, "reasons": reasons, "msLeaves": ms_rows,
        # the page reads its labels and schedule vocabulary from here (template CFG)
        "cfg": {k: v for k, v in CFG.items() if not k.startswith("_")},
        "preds": {str(k): v for k, v in preds.items()},
        "succs": {str(k): v for k, v in succs.items()},
        "predMeta": {str(k): v for k, v in pred_meta.items()}, "depts": [{"key": k, "name": n} for k, n in DEPTS if k in _dept_used],
        "milestones": ms, "constraints": cons, "supplyDeliv": SUPPLY_DELIV,
        "cols": ["dept", "type", "area", "pkg", "sec", "stage", "name", "bES", "bEF", "fES", "fEF",
                 "pct", "dur", "qty", "uom", "tf", "state", "owner", "sub", "cost", "seq", "vls",
                 "ownship", "nd", "dly", "item", "wt", "vcrit", "desc", "note", "aef",
                 "tid", "wbs", "org", "uid", "pb", "sup"],
        "leaves": rows}
assert DATA["cols"][WT_I] == "wt", f"WT_I points at {DATA['cols'][WT_I]!r}, not 'wt'"
assert DATA["cols"][AEF_I] == "aef", f"AEF_I points at {DATA['cols'][AEF_I]!r}, not 'aef'"
out = os.path.join(SCR, CFG.get("dataFile", "ntpc_dashboard_data_v2.json"))
json.dump(DATA, open(out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(f"meta: plan={meta['plan']}% act={meta['act']}% finish {meta['forecastFinish']} (+{meta['delayDays']}d) crit={n_crit}")
print("json ->", out)
