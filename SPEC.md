# NTPC Bikaner Block 8 (200 MW) — MIS Dashboard Specification

**Live URL:** https://vikas-visilean.github.io/ntpc-block8-mis-dashboard/v2/
**Repository:** https://github.com/Vikas-visilean/ntpc-block8-mis-dashboard
**Project:** KPIGEL-NTPC Bikaner Block 8 (200 MW) Project-SAT · KPI Green Energy / KP Group
**Owner:** VisiLean (Vikas Patel)
**Spec updated:** 31-Aug-2026

> **Keeping the dashboards fed:** every project refreshes itself on a GitHub Actions worker —
> see **[SYNC-SETUP.md](SYNC-SETUP.md)**. A project needs its own VisiLean token as a repository
> secret (a token only works for the project it was generated for); without one its workflow
> skips its refresh loop with a warning rather than looping in green, and the daily
> `sync-health.yml` reports what is not fed. `python scripts/check_sync.py` reports every
> dashboard's build age and whether its sync is alive.

The working dashboard is **v2**, live from the VisiLean PowerBI APIs and embedded in VisiLean's
Custom Analytics. **Start at [section 10A](#10a-v2--v3--live-from-the-visilean-apis-the-current-system)**
— that describes the system as it runs today, including every rule KP has agreed.

Sections 1–9 describe the **locked v1.0 baseline** (`v1.0-baseline-2026-08-17`), which is driven by a
static MSP export and is kept only for reference and restore. Where the two disagree, 10A is correct.

> **Change control on v1.0:** the tagged baseline is not modified. All live work happens in `/v2/`
> and `/v3/`, and the tag always restores the v1.0 state exactly.

---

## 1. What this dashboard is  *(v1.0 — locked)*

A single self-contained HTML file (no external dependencies, ~2.2 MB) that renders a complete
project-management review system for the NTPC Bikaner Block 8 (200 MW) solar project:
13 pages covering the project summary, plant layout, procurement pipeline, MOM/actions, and nine
department views. It is generated from the approved **Rev-2 Weightages schedule**
(11,228 tasks / 10,853 dependency links) and published on GitHub Pages.

* All progress figures are **weightage-based** (the KP-approved Rev-2 weightages: Project Initiation 4 %,
  Regulatory 2 %, Design 8 %, Quality 1 %, Procurement 41 %, Execution & Construction 43 %, HOTO 1 %).
* All computations run **client-side** from an embedded JSON dataset, so every filter/toggle recomputes
  instantly with no server.

---

## 2. Architecture & data flow  *(v1.0 — MSP file driven; superseded by 10A)*

```
MS Project schedule (TRACKED Rev-2 XML)
        │  ntpc_dash_data.py  (Python + mpxj: reads schedule, computes forecast + float,
        │                      classifies every activity, emits compact JSON)
        ▼
ntpc_dashboard_data.json  (~2 MB: meta + months + depts + milestones + 10,362 leaf records)
        │  build_ntpc_dash2.py  (injects JSON + KP logo into the template)
        ▼
ntpc_dash_template.html  ──►  index.html  (single file, everything inline)
        │  git commit + push
        ▼
GitHub Pages  →  https://vikas-visilean.github.io/ntpc-block8-mis-dashboard/
```

The **template never touches the data source** — it only consumes the JSON contract below. This is
what makes the VisiLean API switch a data-layer swap (§10) with zero UI change.

---

## 3. Data contract  *(v1.0 — the live contract is in 10A)*

```jsonc
{
  "meta":   { "statusDate", "statusWd", "startDate", "project",
              "baselineFinishWd", "forecastFinishWd", "baselineFinish", "forecastFinish",
              "codBaseline", "codForecast", "statusIso",
              "plan", "act", "spi", "svPts", "svPct",          // weightage-based overall metrics
              "delayDays", "critical", "done", "inprog", "late", "total" },
  "months": [ { "label": "May-26", "wd": 22 }, ... ],           // month-end working-day markers
  "depts":  [ { "key": "engineering", "name": "Design & Engineering" }, ... ],  // 9 departments
  "milestones": [ { "name", "b", "f", "slip", "status" }, ... ],// 9 key milestones (wd indices)
  "cols":   ["dept","type","area","pkg","sec","stage","name","bES","bEF","fES","fEF",
             "pct","dur","qty","uom","tf","state","owner","sub","cost","seq"],
  "leaves": [ [ ...one array per activity, indexed by cols... ], ... ]   // 10,362 records
}
```

Per-activity fields (`leaves`):

| Field | Meaning |
|---|---|
| `dept` | department key (initiation / engineering / quality / supply / services / regulatory / execution / tnc / hoto) |
| `type` | Activity Type custom field (Engineering, Procurement-Supply, Construction, …) |
| `area` | Block-N / PSS / ICR / Plant-General / Off-site |
| `pkg`, `sec` | package (L3-ish) and section (L2-ish) names from the WBS |
| `stage`, `sub` | coarse stage bucket and fine pipeline sub-stage (Design/Tender/PO/…/At Site/Payment) |
| `bES`,`bEF`,`fES`,`fEF` | baseline / forecast start & finish as **working-day indices** |
| `pct` | % complete (0–100) |
| `dur` | duration in working days |
| `qty`,`uom` | quantity + unit (physical rows only) |
| `tf` | total float (working days) on the forecast network |
| `state` | done / inprog / late (past planned start, unstarted) / future |
| `owner` | department role owner (custom field Text4) |
| `cost` | activity cost in ₹ — **the Rev-2 weightage carrier** |
| `seq` | schedule (file) order for stable sorting |

**Working-day calendar:** 6-day weeks (Mon–Sat, Sundays off), day 1 = 07-May-2026 (LOA zero date).
Every date in the system is an index on this axis; `wdate()` converts back to dd-MMM-yy.

---

## 4. Calculation engine  *(v1.0 — the live engine is in 10A)*

### 4.1 Weighting
`weight(activity) = cost` (the Rev-2 weightage carrier). For any *filtered subset* whose total cost is
zero (e.g. pure quality-process views), the engine falls back to **duration weights** so bars never blank out.

### 4.2 The three curves (used by gauge, S-curves, progress bars)
For a set of activities R at date *t* (working-day index), with `w` = weight and clamp to [0,1]:

* **Plan %** `= Σ clamp((t − bES)/dur) · w ÷ Σ w` — planned value: each activity earns its weight
  linearly across its **baseline** window.
* **Actual %** `= Σ min(pct/100, elapsed-on-forecast) · w ÷ Σ w` — earned value; at today this equals
  Σ(pct·w)/Σw. (The `min` only matters when the date slider is dragged into the past.)
* **Forecast %** `= Σ clamp((t − fES)/dur) · w ÷ Σ w` — the projection on **forecast** dates.

Derived: **SPI = Actual ÷ Plan** · **Progress Variance = Actual − Plan** (percentage points).
Cross-check that always holds: Cost card EV ÷ BAC = overall Actual %.

### 4.3 Forecast dates (per activity)
Computed by a forward CPM pass over all 10,853 links:

1. **Complete (100 %)** → forecast = recorded actual dates.
2. **In progress** → forecast start = actual start; forecast finish = status date + duration × (1 − pct/100).
3. **Not started** → earliest start = max(status date, predecessor constraints
   (FS: pred fEF + lag · SS: pred fES + lag · FF: back-computed)); finish = start + duration.
4. Hard floor: *Project Closeout* cannot finish before wd 470 (**05-Nov-2027**, the FNET constraint).

Result at the 05-Aug-2026 status: baseline finish **05-Nov-27**, forecast **11-Nov-27** (+5 days).

### 4.4 Float & criticality
Backward pass from the forecast project end relaxes a Latest-Finish per activity through every link;
**Total Float = LF − fEF**. `Critical` = float ≤ 5 days and not complete (237 activities);
`Supercritical` = float ≤ 0 (169).

### 4.5 Status model (VisiLean-aligned)
Until the live VisiLean feed is connected, the dashboard asserts only what the schedule knows:

| Status | Colour | Rule |
|---|---|---|
| **Complete** | green `#1b8a2f` | pct = 100 |
| **Started** | purple `#7a4fb3` (VisiLean "Started") | 0 < pct < 100 |
| **Not Committed** | yellow `#8a7500` on wash | pct = 0 (all unstarted work) |

*Not Ready / Warning / Stopped and the quality states are reserved for the VisiLean live feed.*
Overdue-ness is shown as a **date fact** (red "was due dd-MMM-yy" text), never as an invented status.
Group/rollup status priority: all-done → Complete; **any progress → Started**; else Not Committed.
Other definitions: `Delayed` = forecast finish ≥ 4 days behind baseline (unfinished);
`Awaiting start` = pct 0 and baseline start before status date.

---

## 5. Pages & components  *(v1.0 — layout still broadly current; see 10A for behaviour)*

### 5.1 Project Summary (page 1)
| Component | Content / calculation |
|---|---|
| **Overall progress** (speedometer) | needle = Actual %, tick = Plan % (§4.2 on the filtered scope). Stats: SPI — Schedule Performance Index (= Actual % ÷ Planned %), Progress Variance (= Actual − Plan). Needle colour: green ≥ plan, amber ≥ 85 % of plan, red below. |
| **EPC bifurcation** | Engineering / Procurement / Construction rows: Actual % vs Baseline Plan %, activity counts, Δ progress variation, SPI chip. |
| **Cost** | Budget (BAC) = Σ cost; Earned Value = Σ cost·pct; CPI/Actual "—" awaiting accounts feed; FAC = BAC. |
| **KPI cards** | Total activities (incl. 9 milestones) · Completed (+% of count) · Delayed (≥4 days behind, + delayed-start count + critical chip) · Baseline vs Forecast (dates + "+N days" chip) · Days to COD. |
| **Key Milestones** | colour legend (green ≤6 days slip · amber 7–15 · red >15), mini progress track with today line, 9 cards: baseline/forecast dates + slip chip. |
| **Long Lead Item Delivery Status** | top-12 supply packages by weightage; delivery = "GRN at Site" step; baseline vs forecast delivery, Delay/Ahead in days, status chip. |
| **S-curve — Plan vs Actual** | **multi-select** discipline chips (Overall / E / P / C) overlaying curves — solid = actual, dashed = forecast, dotted = plan; **Cumulative and Monthly charts stacked**; Chart/Table toggle (table grows per-series columns). |
| **Stage progress** | Actual % vs Plan tick per stage bucket (Initiation → HOTO). |
| **Critical points — management attention** | top-5 *actionable* critical activities due within ~60 days (buffer/closeout excluded), each with full WBS path, VisiLean status, float, window, owner; supercritical counter. |
| **Open Constraints / Awaiting to Start** | two tabs: *Awaiting Start* (activities past planned start: WBS, Owner·Dept, planned start, pending-since days) and *VisiLean Constraints* (API placeholder — will list the constraints log + category pie once connected). |

### 5.2 Plant Layout
Block/feeder tile grid (24 blocks + PSS/ICR/general): each tile shows **Actual %** (red when behind
plan), plan %, activity count, delayed-count alarm chip, and per-category quantity bars
(Civil/Piling/MMS/Module/DC/AC-HT/BOP — physical quantities only; %-type rows excluded).
Clicking a tile filters the whole dashboard to that area. Below: Area Scorecard table
(plan/actual/SPI/delayed/critical per area).

### 5.3 Package Pipeline
Procurement pipeline matrix: rows = 61 packages, columns = **actual schedule steps** ordered by
earliest baseline start (up to 32, with a stage-column multi-select popover). Cell = VisiLean status
chip + due/done date (red when overdue vs baseline). Stage summary cards on top (done/total + "N in
progress"). Controls: **L1 section / L2-L3 package cascading filters**, package search, delayed-only
toggle. Click a row → step-level detail. Plus "Scope vs Order vs Deliver" quantity table.

### 5.4 MOM & Actions
Action tracker (seed content) — Responsible / Due / VisiLean-coloured status. Will sync from the
VisiLean action log (MOM category) via API.

### 5.5 Department pages (9)
Every department page: gauge, department S-curve, KPI cards, and:

* **Design & Engineering** — *Engineering Overview (Exec View)* single-row strip: stage, design status,
  % Engg complete (weightage-based), % RFP shared, TBER %, Material approval (client) %, tech queries
  (manual feed), current critical activity + float, On-track/Delayed chip. Then the engineering
  document pipeline (doc stages per package).
* **Procurement — Supply / Services** — *Key Procurement Dates (Exec View)* matrix (11 fixed columns
  RFP→GRN, dates coloured green ✓ complete / purple ▶ started / red overdue), *PO Tracker*
  (Wt %, baseline vs forecast/actual PO, Δ days, reason column for manual feed), *Committed vs
  Budgeted* card (committed = packages with PO placed), *Delay Analysis* bars for the ED heads a–e
  (RFQ receipt → PO placement), then the full pipeline matrix.
* **Regulatory & Statutory** — *Critical approvals tracker* (schedule order, sortable, searchable,
  status filter; **click a row to focus the Updates Sheet**), *All approval groups*, *Statutory
  Updates Sheet* (all 104 documents: timeline, scope/owner, target vs revised date, status).
* **Execution & Construction / T&C** — block/feeder scorecard + stage progress by work type.
* **Project Initiation / Quality / HOTO** — sections progress bars.

---

## 6. UI / UX system (VisiLean design language)

* **Colours (light):** page `#f5f6f8`, surface `#fff`, blue `#1793e6`, good `#00a455`, warn `#f59e00`,
  crit `#ff4343`; dark theme: page `#0E1216`, surface `#161B20`, blue `#45a9eb`. S-curve series:
  actual blue, plan purple, forecast dashed-blue; discipline overlays blue/purple/green/amber.
* **VisiLean status chips** (from the VisiLean Task Colours legend): Complete green · Started purple
  `#5C2D91`-family · Not Committed yellow · (Not Ready salmon / Warning amber reserved for live feed).
  A permanent legend sits in the filter bar.
* **Typography:** Inter; compact 11 px base scaled by **default zoom 1.3** on large screens
  (1.15 ≤ 1680 px, 1.0 ≤ 1400 px) per exec readability review.
* **Layout:** 12-column card grid, 8 px radius cards, sticky filter bar, left sidebar navigation
  (Project pages + Departments), Auto/Light/Dark theme toggle (persisted).
* **Terminology rules:** always “days” (never wd); "Actual % vs Baseline Plan %" phrasing; activity
  counts written as "N activities".

## 7. Interactions

* **Global filter bar** (applies to every page): Department, EPC type, Area, Package, **Owner**,
  **From/To date range** (forecast-window overlap), Critical-only, Delayed-only, **date slider**
  (re-evaluates all curves/KPIs at any as-of date), Reset.
* **Click-to-filter:** plant tiles → area filter; approvals tracker row → statutory sheet focus;
  pipeline row → step detail expand.
* **Scroll behaviour:** re-renders (toggles, filters) keep scroll position; only page *changes* scroll to top.
* **Tooltips:** S-curve hover (per-series values by month), milestone dots, pipeline quantity cells.
* **Sorting/search:** regulatory tables sortable by any column; package/approval search boxes.

## 8. Known placeholders (by design, awaiting feeds)
Tech query counts, billing status, CPI/actual cost, PO-delay reasons, committed-cost reasons —
shown as "— (manual)". VisiLean Constraints tab and MOM tracker await the API connection.

---

## 9. Update runbook  *(v1.0 MSP pipeline — the live runbook is in 10A)*

```
1. python ntpc_dash_data.py        # point P at the new TRACKED xml → ntpc_dashboard_data.json
2. python build_ntpc_dash2.py      # template + data + logo → index.html
3. QA: serve locally, walk 13 pages, zero console errors, spot-check EV ÷ BAC = Actual %
4. git commit + push (repo dir: C:\Users\vikas\AppData\Local\Temp\ntpc-mis-dash)
   (GitHub Pages may need: POST /repos/.../pages/builds to rebuild; verify by content marker)
5. Optional PDF: python make_print_html.py + headless Edge --print-to-pdf
```

All scripts live in `_build tools (do not delete)` and in the baseline snapshot (§11).

---

## 10. VisiLean API integration plan  *(delivered — see 10A for what was actually built)*

**Principle:** the template and every calculation stay untouched. Only the producer of
`ntpc_dashboard_data.json` changes — a new adapter builds the same JSON contract (§3) from VisiLean
APIs instead of the MSP file. Stub prepared: `visilean_api_adapter.py`.

What the adapter needs from the VisiLean APIs (to be mapped when API specs are provided):

| Need | Maps to |
|---|---|
| Activity list with WBS hierarchy (or L1–L7), name, duration, baseline start/finish | `pkg/sec/area` classification + `bES/bEF/dur` |
| Live % complete + actual start/finish per activity | `pct`, forecast engine inputs |
| VisiLean task status (Not Committed / Ready / Started / Warning / Stopped / Complete / quality states) | status chips — replaces the interim 3-state model, full legend activates |
| Custom fields: Department, Owner, Activity Type, Location, Package, Qty, UOM, Cost/Weightage | corresponding columns |
| Constraints log (category, status, activity link) | Open Constraints tab + category pie |
| Action log (MOM category) | MOM & Actions page |
| Assignee (VisiLean Activity Owner) | owner column/filter |

Refresh model options (decide with API): (a) scheduled regeneration (adapter → JSON → static publish,
e.g. every 15–60 min), or (b) client-side fetch where the page pulls JSON from a VisiLean endpoint at
load — template already reads one JSON object, so both are drop-in. Forecast/float can continue to be
computed in the adapter, or be replaced by VisiLean's own dates if preferred.

---

## 10A. v2 / v3 — live from the VisiLean APIs (**the current system**)

> **Read this section first.** Sections 1–9 describe the locked v1.0 baseline, which is driven by a
> static MSP export and is no longer the working dashboard. Everything below is what actually runs.

### Which build is which

| Path | What it is | Status |
|---|---|---|
| `/` (`index.html`) | v1.0 baseline, MSP-driven, tagged `v1.0-baseline-2026-08-17` | **locked, do not edit** |
| `/v2/` | live from the VisiLean APIs | **this is the one KP uses** — embedded in VisiLean Custom Analytics |
| `/v3/` | identical logic, VisiLean brand palette and rounder surfaces | built every cycle, awaiting KP's word to promote |

v2 and v3 share the *same* data JSON and differ only in their template's design tokens. **Every
functional change must be applied to both templates.** Nothing enforces this — the builds do not
compare them — so the patch scripts in this repo's history always edit the two files in one pass,
asserting each anchor matches exactly once. If you change one template by hand, change the other.

### Data source & tokens

Three VisiLean PowerBI endpoints, project `7A2842F6-7E5F-DB7C-3E7F-0EE7EF60698F`:

| Call | Purpose |
|---|---|
| `type=task` | every activity, custom fields, dates, % complete, status |
| `type=task` + `&IncludeStatusChange=true&IncludeReschedule=true&IncludeQuantities=true&IncludeConstraintNotes=true` | the history feed — **those flags are what populate `activityHistory`**, which is where variance reasons live |
| `type=constraintLog` | the constraints log |

One token serves all three calls. It is a GitHub Actions secret (`VL_TOKEN_NTPC`, falling back to
the `ntpc` entry of the flat `VL_TOKENS_JSON`) and, locally, the gitignored flat
`scripts/vl_tokens.json` (`{"ntpc": "<token>"}`) — see `scripts/vl_token.py`. **Never commit
them**; the build asserts `"accessToken" not in html`.

The API returns **403 to any request carrying a browser `Origin` header**, so the page cannot fetch
VisiLean directly. Everything goes through the GitHub Action.

### Schedule logic — predecessors and successors

`prerequisites` always comes back empty from the API, so the logic network is read from the sidecar
`scripts/vl_relations.json` — a flat list of `[predUid, succUid, type, lagDays]` (7,608 pairs),
extracted from the MSP file with **MSP Unique ID matched to VisiLean `externalId`**.

* Only the relationships are taken from the MSP. **Every figure on the dashboard comes from the
  VisiLean API** — the MSP file is never a source of dates, progress or status.
* `meta.logicCoverage` publishes the share of leaves still wired into the network (**99.6%** today).
* **This sidecar does not update itself.** Regenerate it whenever the schedule is re-imported or
  restructured in VisiLean, or float and criticality drift silently.

Published to the client as `preds` / `succs` (`{uid: [[uid, type, lag], …]}`) and `predMeta`
(`{uid: [name, pct, status, baselineFinishWd, forecastFinishWd, delayedFlag]}`) so the property
panel can show a predecessor's state without a second lookup.

### Classification — how a row gets its department, WBS and package

Levels 1–7, `Department`, `Package`, `Activity Type` and `Element/Scope` come from the row's
VisiLean custom fields. **Rows created directly in VisiLean carry no custom fields at all**, so:

* a leaf with no Levels **inherits its nearest classified ancestor's** classification, and takes its
  pipeline stage from that ancestor's name (`R1` matches no stage; *Submission to Client* does);
* `Weightage` and `Cost` are **never** inherited — see the revision rule below;
* the department fallback is **no longer silent**: any leaf that matches no rule is reported at build
  time. Before this, `dept_of()` quietly returned `"initiation"`, which is how 22 drawing revisions
  ended up filed under Project Initiation with an empty WBS.

### Post-baseline design revisions (KP rule, 31-Aug-2026)

KP has asked the client to raise a **new activity in VisiLean whenever a design revision comes up**,
because revisions are not fixed in the schedule. This population grows continuously, so it is
handled by rule, never by hand.

**The rule:** a superseded revision no longer represents the deliverable, so **the deliverable's
approved weight sits on the CURRENT revision**; earlier revisions carry none. A deliverable is
complete only when its latest revision is complete — a new revision correctly reopens one that had
been finished.

* **Identify structurally, never by name.** An MSP-imported activity has an `externalId`; one raised
  later in VisiLean does not. Naming already fails — of 25 post-baseline rows, one is `RO` (a typo)
  and one is `DBR R1 Submission`.
* **Order** within a deliverable = planned finish, then creation order. This agrees with the
  R-number in all 17 groups today.
* Applies only where **every** child under a parent is post-baseline. A parent that still has
  MSP-imported children has already distributed its weight to them; those are skipped and logged.
* **Any weightage typed onto a revision row is ignored.** Rows `52155`/`52156`/`52157` each had the
  parent's weight copied in, putting that deliverable in the denominator three times (0.0395 against
  its approved 0.0116). The rule closes that permanently.
* Post-baseline rows **stay in the counts** so the dashboard still reconciles with VisiLean, but are
  **stated**: the Total card reads "… · 25 post-baseline revisions", every KPI drill offers a
  **Post-baseline** subset, and the property panel marks each row *Current revision* or *Superseded*.

Columns `pb` / `sup`; meta `postBaseline`, `superseded`, `revDeliverables`.

### Weightage & progress

Progress is **weightage-based**, on VisiLean's `Weightage` custom field (**not** Cost — that was an
early error). KP's formula, confirmed 29-Aug-2026:

```
sum the weightage of all child-level activities            -> total units
activity % complete x that activity's weightage            -> activity actual units
sum the actual units / total units                         -> % complete
```

This holds for the project summary **and for every filter, department and section page** — the same
`wgt()` function computes all of them, so the gauge and the headline figure cannot drift apart.

* Published live in `meta`: `wtSum` (share of project weight assigned), `wtCoverage` (share of
  activities carrying a weightage) and `wtMissing`. On 31-Aug-2026: **99.84%**, **60.5%**, and
  **2,556** activities with no weightage. Those contribute nothing to progress — a data item for KP,
  published rather than hidden.
* A finished activity counts in full from the date it **actually** finished, so work completed ahead
  of schedule is not suppressed by the elapsed cap.

### Counting rules — these tie the dashboard to VisiLean 1:1

Reconciled activity-by-activity against VisiLean's own dashboard (29-Aug-2026):

* **Total = every leaf task**, whether or not it is baselined. (An earlier build excluded
  not-baselined rows from Completed/Delayed to match VisiLean; VisiLean now counts them, so that
  exclusion was removed.)
* **Completed** = `pct >= 100`. **Delayed** = past planned start with 0% progress, **or** past
  planned finish and not complete. **Actual %** = `Σ(w × pct) / Σw`.
* **The single deliberate difference from VisiLean:** activities whose trade is
  **"Not Applicable"** are excluded from every count, progress and weightage calculation — KP's
  explicit instruction. 13 activities today; the Total card states it.
* **E / P / C are counted on `Activity Type`**, not on the department mapping (which folds Testing &
  Commissioning into Construction and disagrees with VisiLean).
* **Milestones** are added to the headline count only when no filter is applied.
* **Long Lead Item Delivery Status** lists *every* `Procurement - Supply` package (33), not a top-N
  slice. Delivery row = the package's "GRN at site" activity, falling back to its last activity.

### Reasons for Variance

VisiLean files one variance record per **late event**, and the dashboard now reads it the same way.
The source is the history feed's `activityHistory` text:

```
Task 'Layout Preparation' started late by <who>. Note added: <free text>  KP: Manpower
Task 'Layout Preparation' completed late by <who>. Note added: <free text>  KP: Manpower
```

* `started late` → Reason Category **Late Started**; `completed late` → **Late Completed**. The card
  has a switch for the two.
* The reason is the trailing `<Party>: <Category>` — the label exactly as it reads in VisiLean's
  Custom Reasons list.
* **One record per event, not per activity**: an activity that started late *and* finished late for
  the same reason counts twice, as it does in VisiLean's export.
* Reschedules, `set to 'Not Ready'` and stops are **not** variances to VisiLean and are not counted.
  Counting them was what produced a spurious "No reason recorded" slice — every genuine late event in
  the feed carries a reason. Their notes still reach the Notes / Comments column.
* An activity can have several history rows; **merge them all**. Keeping only the longest row lost
  the stop on task 44699 behind a longer "started early" row.
* **Reconciliation with VisiLean's export** (worked 31-Aug-2026): 45 records on the dashboard
  + 3 on Not Applicable activities = the export's 48. The card states the excluded three
  (`meta.naReasonRecords`) so the difference is visible rather than discovered. The counts move as
  the team logs reasons — the *rule* is what to check, not the numbers.

### Notes / Comments, and predecessor-derived notes

The Notes column and the property panel show, in order: VisiLean's own `notes` field, then the
recorded reason. When VisiLean's note already carries the free text, only the reason *category* is
appended, so the line does not repeat itself.

When a **delayed** activity has no note and no reason of its own, the note is derived from the
schedule logic (`predNote()`):

* `Predecessor incomplete: <name> (<status>, <pct>%) — <that predecessor's own reason>`
* or `… — running late, no reason recorded` when the predecessor has no reason either;
* or `All N predecessors complete — no reason recorded against this activity`, which says the delay
  is the activity's own.

Derived notes are shown in a **tinted card** with the caveat *"Nothing recorded against this activity
in VisiLean — read from the schedule logic"*, so they are never mistaken for something a person wrote.

### Data contract

`scripts/ntpc_dashboard_data_v2.json`:

| Key | Contents |
|---|---|
| `cols` | column order for `leaves` — see below |
| `leaves` | one array per activity, positionally indexed by `cols` |
| `msLeaves` | milestones in the *same* shape, so drills can list them beside tasks |
| `milestones` | the 9 key milestones with baseline/forecast |
| `months` | month buckets for the S-curves |
| `reasons` | one record per activity with a variance, each carrying `cats[]` and `events[]` |
| `preds` / `succs` / `predMeta` | the logic network and each predecessor's state |
| `constraints` | the VisiLean constraints log |
| `supplyDeliv` | long-lead package delivery dates from the VisiLean package summaries |
| `depts` | department key → display name |
| `meta` | headline figures and provenance |

**`cols` (37):** `dept, type, area, pkg, sec, stage, name, bES, bEF, fES, fEF, pct, dur, qty, uom, tf,
state, owner, sub, cost, seq, vls, ownship, nd, dly, item, wt, vcrit, desc, note, aef, tid, wbs, org,
uid, pb, sup`

Working-day calendar: Mon–Sat, Sundays off, day 1 = 07-May-2026. `bES`/`fES` are 0-based,
`bEF`/`fEF` 1-based.

**`meta`** carries `total, totalTasks, done, inprog, late, delayed, act, plan, spi, svPct, critical,
wtSum, wtCoverage, wtMissing, naExcluded, naReasonRecords, postBaseline, superseded, revDeliverables,
logicCoverage, undated, statusDate, generatedAt, generatedAtEpoch, source`.

### UI system — drills and the property panel

One generic `drillOpen(spec)` engine serves every drill on the dashboard. Each gets:

* **KP's standard 11 columns**, identical everywhere: Task ID, Activity, WBS, Description, Owner,
  Organisation, Status, % complete, Baseline finish, Planned finish, Notes / Comments. Widths are
  explicit and total ~1,430px; the drill is 1,620px wide so they all fit without sideways scrolling.
* sorting on any header, a filter box under every column, paging, **Copy** and **Export CSV** (both
  export *every filtered row*, not just the visible page);
* per-subset row sets and column sets, so one drill can offer e.g. **Packages** and **Activities**
  views with different columns;
* subsets for Tasks / Milestones / Critical / No baseline / **Post-baseline**.

**The property panel.** Clicking a row does *not* replace the list — the panel slides in on the right
and the list stays in view with the clicked row highlighted, so the next activity is one click away.
It survives sorting, filtering and paging, has its own back arrow for walking a predecessor chain, and
Esc closes the panel before the list. Properties are grouped under **Activity / Status /
Responsibility / Schedule**, followed by the Notes card, reasons, VisiLean history, description, and
the predecessor / successor lists. One panel serves every activity, wherever it was opened from.

### Running inside VisiLean's Custom Analytics iframe

The dashboard is embedded as an iframe, which breaks three things that look fine standalone:

* **`navigator.clipboard.writeText()` rejects** — the host does not delegate clipboard-write. Copy
  falls back to a selected `<textarea>` + `document.execCommand("copy")` off the real click, then to a
  visible pre-selected box for Ctrl+C. CSV download is blocked the same way and uses the same chain.
* **`100vh` / `innerHeight` can be the whole scrollable page**, not the band on screen, if the host
  sizes the iframe to its content. The visible band is measured with an `IntersectionObserver` on a
  viewport-sized sentinel — in a cross-origin iframe the implicit root *is* the top-level viewport —
  and published as `--vph`. The overlay is repositioned onto that band **only when the frame is
  genuinely clipped**, so the ordinary case stays pure CSS with no polling and no scroll lag. The
  observer must be **re-observed** to report again: the host scrolling the iframe fires no scroll
  event inside it and does not change the intersection ratio.
* **The modal must cap its own height.** `#rsnmodal-box` carries `overflow:hidden`, which makes it a
  scroll container — so a sticky header sticks to the top of *the box*, not the viewport, and scrolls
  away with it. The box is a flex column capped to `--vph`, with the header pinned and the body
  scrolling inside.

> **Verify layout by measuring `getBoundingClientRect()` after a real scroll or hover — never by
> reading the stylesheet.** Both the sticky-header bug and the Supply package panel bug passed a CSS
> read and failed in the browser. Note also that the preview pane does not paint while hidden, so CSS
> transitions freeze and `IntersectionObserver` never fires; force a screenshot before measuring.

### Refresh — how it actually works

GitHub `schedule` events are best-effort and heavily throttled. Measured on this repo with
`cron: "*/5"` over 23–24 Aug 2026: **median gap 27 min, maximum 111 min** — never once 5 minutes.
`cron: "7 */2"` was worse in practice: actual triggers ~11 hours apart.

So the schedule only has to *start* a worker:

* `cron: "7,37 * * * *"` asks every 30 minutes; `concurrency: cancel-in-progress: true` means a new
  worker cleanly replaces the running one, so extra triggers cost nothing.
* The worker loops **every 5 minutes for ~340 minutes** (`timeout-minutes: 350`, under the 6-hour
  ceiling), so a delayed or dropped trigger is still covered by the previous worker.
* Each cycle builds **both v2 and v3** and publishes only when `v2/.datahash` changes (the hash
  excludes `generatedAt`). A failed cycle logs, reverts the tree and continues.
* `workflow_dispatch` with `once: true` runs a single refresh — useful for a manual catch-up.
* A VisiLean outage exits the cycle cleanly (`sys.exit(0)`) rather than publishing a broken build.

On the page: the header shows the build time **in IST** plus a live **data-age chip** (green ≤ 10 min,
amber ≤ 30 min, red beyond), and a background poll checks `meta.json` every 60 seconds and reloads
when a new build lands.

### Build & run

```bash
python scripts/ntpc_dash_data_v2.py     # VisiLean APIs -> scripts/ntpc_dashboard_data_v2.json
python scripts/build_ntpc_dash_v2.py    # + template + logo -> v2/index.html, meta.json, .datahash
python scripts/build_ntpc_dash_v3.py    # same data, v3 template -> v3/index.html
```

The working copy lives at `C:\Users\vikas\ntpc-mis-dash` — **not** under `%TEMP%`, where Windows
cleanup previously deleted tracked files and corrupted the local git objects.

**After any rebase or stash involving `v2/` or `v3/`, grep the outputs for `<<<<<<<`.** Merge-conflict
markers have been committed into `index.html` and `meta.json` before, which serves an invalid build.
The auto-refresh worker commits to the same files every few minutes, so conflicts are routine:

```bash
gh run cancel <in-progress-id>
git checkout --theirs v2/index.html v2/meta.json v2/.datahash v3/index.html v3/meta.json v3/.datahash
git add v2 v3 && git rebase --continue && git push origin master
gh workflow run refresh-v2.yml
```

---

## 10B. Open items — what the next person needs to pick up

| # | Item | Detail |
|---|---|---|
| 1 | **Planned % is unreconciled** | VisiLean publishes 13.78%; the dashboard computes 8.5%. ~25 variants were tried (weightage / cost / duration / equal × baseline / planned × elapsed / step × leaves / incl-parents × week fields); the closest reached 11.86%. **It is not derivable from the task endpoint** — the VisiLean product team needs to state the definition or the field. |
| 2 | **2,556 activities carry no weightage** | 60.5% coverage. They contribute nothing to progress. KP data action in VisiLean. |
| 3 | **109 activities have no baseline** | e.g. taskIds 52490, 52449, 52461, 52474 ("KP to EPC PO Placement"), 52417 ("GFC Issuance"). They count in Total and Delayed but have no baseline to vary against. |
| 4 | **VisiLean's Critical Activity flag is set on only 5 activities** | The `Critical (VisiLean)` filter and column are near-empty as a result. Float-based criticality is computed separately from the logic network. |
| 5 | **Three revision rows still carry a copied weightage in VisiLean** | `52155` / `52156` / `52157`. The dashboard ignores them, but they are misleading in VisiLean's own views — worth clearing, with a note to the client that revision activities should not have a weightage typed at all. |
| 6 | **`vl_relations.json` is a static capture** | Regenerate from the MSP whenever the schedule is re-imported; watch `meta.logicCoverage`. |
| 7 | **v3 promotion** | v3 is built every cycle and is functionally identical. Promoting it to `/v2/` (or repointing the VisiLean embed) awaits KP's word. |

---

## 11. Baseline lock & backups

* **Git tag** `v1.0-baseline-2026-08-17` on the public repo — restores the v1.0 dashboard any time
  (`git checkout v1.0-baseline-2026-08-17`).
* **Frozen snapshot folder:** `Downloads\Baseline Schedule KP\Dashboard Baseline v1.0 (17-Aug-2026)\`
  — index.html, template, data JSON, all build scripts, the PDF export, this spec, and the API adapter
  stub — plus a ZIP of the same.
* **Change policy:** v1.0 at the repository root is not modified. All live work happens in `/v2/`
  and `/v3/`.

## 12. File inventory

### Current system (v2 / v3)

| File | Role |
|---|---|
| `scripts/ntpc_dash_data_v2.py` | **the adapter** — fetches the three VisiLean APIs, classifies, computes float/forecast/reasons, emits the data JSON |
| `scripts/ntpc_dash_template_v2.html` | v2 UI template (all pages, calculations, drill engine, property panel) |
| `scripts/ntpc_dash_template_v3.html` | v3 template — same logic, VisiLean brand palette |
| `scripts/build_ntpc_dash_v2.py` / `_v3.py` | template + data + logo → `v2/index.html`, `meta.json`, `.datahash` |
| `scripts/vl_relations.json` | logic network `[predUid, succUid, type, lag]` from the MSP (7,608 pairs) |
| `scripts/vl_tokens.json` | API tokens — **gitignored, never commit** |
| `scripts/kp_logo.b64` | embedded KP logo |
| `.github/workflows/refresh-v2.yml` | the refresh worker |
| `v2/index.html`, `v2/meta.json`, `v2/.datahash` | published build |
| `v3/index.html`, `v3/meta.json`, `v3/.datahash` | published build |

### Locked v1.0 baseline

| File | Role |
|---|---|
| `index.html` | the v1.0 dashboard (self-contained) |
| `print.html` | print-mode build for the PDF export |
| `ntpc_dash_template.html` | v1.0 UI template |
| `ntpc_dashboard_data.json` | v1.0 dataset (05-Aug-2026 status) |
| `ntpc_dash_data.py` | MSP→JSON builder |
| `SPEC.md` | this document |
