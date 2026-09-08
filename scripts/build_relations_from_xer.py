# Build the logic network for the Adani S6a dashboard from the P6 XER.
# VisiLean's task feed returns prerequisites empty, so the schedule file is the only
# place the links exist. Endpoints are written as ACTIVITY CODES (task_code), which is
# what VisiLean carries as externalId - dash_data.py resolves them to uids.
import json, collections, sys
XER = r"C:\Users\shreyanshi.jaiswal\OneDrive - VisiLean India Private Limited\Documents\KPI Claude\Adani S6a\FY26-P18 S6a 07.09.2026.xer"
rows = collections.defaultdict(list); fields = {}; cur = None
for line in open(XER, encoding="cp1252", errors="replace"):
    p = line.rstrip("\r\n").split("\t")
    if p[0] == "%T": cur = p[1]
    elif p[0] == "%F" and cur: fields[cur] = p[1:]
    elif p[0] == "%R" and cur: rows[cur].append(dict(zip(fields[cur], p[1:])))
code = {t["task_id"]: t["task_code"] for t in rows["TASK"]}
name = {t["task_id"]: t["task_name"] for t in rows["TASK"]}
print("TASK rows:", len(rows["TASK"]), "| TASKPRED rows:", len(rows["TASKPRED"]))
# P6 hours-per-day, for turning the lag into days
hpd = 8.0
for c in rows.get("CALENDAR", []):
    d = c.get("day_hr_cnt") or ""
    try:
        if float(d) > 0: hpd = float(d); break
    except Exception: pass
print("hours per day used for lag:", hpd)
TYPE = {"PR_FS":"FS","PR_SS":"SS","PR_FF":"FF","PR_SF":"SF"}
out, skipped, kinds = [], 0, collections.Counter()
for r in rows["TASKPRED"]:
    p, s = code.get(r["pred_task_id"]), code.get(r["task_id"])
    if not p or not s: skipped += 1; continue
    k = TYPE.get(r["pred_type"], "FS"); kinds[k] += 1
    try: lag = round(float(r["lag_hr_cnt"] or 0) / hpd, 1)
    except Exception: lag = 0
    out.append([p, s, k, lag])
print("links:", len(out), "| skipped (endpoint not in TASK):", skipped)
print("by type:", dict(kinds))
print("with a lag:", sum(1 for x in out if x[3]))
json.dump(out, open("adani_relations.json","w",encoding="utf-8"), separators=(",",":"))
print("sample:", out[:3])
