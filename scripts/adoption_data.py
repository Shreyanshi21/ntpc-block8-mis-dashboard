# -*- coding: utf-8 -*-
"""User adoption data for the NTPC dashboard — LIVE from the VisiLean PowerBI APIs.

Answers "who is actually using VisiLean on this project": which user updated which
activity, what kind of update it was, and when — sliceable by department, activity
type, location, package, activity owner and ownership.

Where the data comes from
-------------------------
VisiLean returns the audit trail on the task endpoint as one row per (task, event),
with the event written as an English sentence in `activityHistory` and its timestamp
in `historyDateTime`:

    Task 'KP to EPC PO Placement' set to 'Not Ready' as a result of action by Fenil Rana
    Task 'Support Installation at IDT side' imported from file '....mpp' by Shreyanshi Jaiswal.
    Task 'Manufacturing Clearance' assigned to Yash Lakdavala by Fenil Rana

So the acting user has to be parsed out of the sentence. To keep that honest we build
a roster first (VisiLean assignees + anyone the trail credits at least three times)
and only ever attribute an event to a name on that roster — a loose "by (.+)" capture
would otherwise invent users out of note text.

Three feeds are merged and de-duplicated on (taskId, timestamp, sentence), because the
flag sets overlap:
  * IncludeStatusChange / IncludeReschedule / IncludeTaskCreation / IncludeQuantities
  * IncludeConstraintNotes / IncludeOther   (assignments, owner changes, notes)
  * the plain task feed, used only for the assignee roster and the project size

Known gap: the PowerBI API exposes no file/attachment events, so document uploads
cannot be counted. Verified 07-Sep-2026 — IncludeAttachments / IncludeFiles /
IncludeDocuments all return the same payload with no file events. `meta.noAttachments`
carries that fact so the page can say so rather than imply zero uploads.

This reads the NTPC project, so it uses the NTPC project's one VisiLean token: env
VL_TOKEN_NTPC, or the "ntpc" entry in VL_TOKENS_JSON (GitHub Actions secrets), or the
flat scripts/vl_tokens.json next to this script (never committed) - see vl_token.py.
There is no separate adoption token. Emits scripts/adoption_data.json.
"""
import io
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

SCR = os.path.dirname(os.path.abspath(__file__))
BASE = "https://app.visilean.net/pb/PowerBiAPI/resource/powerBi/getData/visilean"
PROJECT = "7A2842F6-7E5F-DB7C-3E7F-0EE7EF60698F"
IST = timezone(timedelta(hours=5, minutes=30))

# Accounts to leave out of the adoption picture. Shreyanshi Jaiswal is the VisiLean
# administrator for this project: she imports the MPP schedule (6,459 of the 8,301
# events were one bulk import sweep) and then reassigns owners and dates. Counting that
# as "adoption" drowned out the site teams' own updating, so KP asked (07-Sep) for it to
# come out. Clear this set to put an account back in.
EXCLUDE_ACTORS = {"shreyanshi jaiswal"}
# Excluding anyone here removes them from BOTH reports, since the two share this data file.
# monika sen is hidden from the User Updates Report only, so that lives in
# updates_template.html (HIDE_ACTORS) rather than here - KP asked for it there alone.

# feed -> the flags that select it; every feed is type=task on the one project token
FEEDS = {
    "task": "",
    "hist": ("&IncludeStatusChange=true&IncludeReschedule=true"
             "&IncludeTaskCreation=true&IncludeQuantities=true"),
    "notes": "&IncludeConstraintNotes=true&IncludeOther=true",
}

sys.path.insert(0, SCR)
from vl_token import TokenPool, TokenRejected, fetch_json    # noqa: E402
# a rejected VL_TOKEN_NTPC falls back to the "ntpc" entry of VL_TOKENS_JSON
POOL = TokenPool("ntpc", "Adoption tracker")


def fetch(kind, attempts=3):
    return fetch_json(
        POOL, lambda t: "%s?accessToken=%s&projectId=%s&type=task%s" % (BASE, t, PROJECT, FEEDS[kind]),
        attempts=attempts, label=kind, agent="VisiLean-Adoption", timeout=300)


print("fetching VisiLean APIs...")
try:
    FEED = {k: fetch(k) for k in ("task", "hist", "notes")}
except TokenRejected as e:
    # a wrong credential is not an outage: fail the cycle so the run goes red
    print("::error title=%s every VisiLean token rejected::%s" % (POOL.label, e))
    sys.exit(1)
except Exception as e:                                            # noqa: BLE001
    # transient VisiLean outage: skip this cycle cleanly, the next run recovers
    print("SKIP this cycle - VisiLean API unreachable after retries: %s" % e)
    sys.exit(0)
print("task %d | hist %d | notes %d" % tuple(len(FEED[k]) for k in ("task", "hist", "notes")))

# ---------- roster ----------
# Only person-shaped names, so note text can never masquerade as a user.
PERSON = re.compile(r"^[A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){1,3}$")
NOT_PERSON = re.compile(r"^(target date|for action|the designated|action by)", re.I)
BY = re.compile(r"\bby\s+([A-Za-z][^\.,:;\r\n]{2,40})")
# VisiLean writes these sentences itself, so a name sitting in one of these positions is a
# real user on their very first action. The >=3 rule below exists only to stop free note
# text inventing people, and it was costing new joiners their first updates: Vikram Singh's
# only action on 14-Sep read as "Unattributed" until this existed.
STRICT_BY = re.compile(
    r"(?:was forced ready to start by|as a result of action by|bulk completed by"
    r"|imported from file[^.]{0,160}?by|created by|completed on time by|started on time by"
    r"|rescheduled by|assigned to [^.]{1,80}?by)\s+([A-Za-z][^\.,:;\r\n]{2,40})", re.I)

owners = {}
for r in FEED["task"]:
    n = " ".join(str(r.get("owner") or "").split())
    if n:
        owners[n.lower()] = n

cand = {}
strict = set()
for feed in ("hist", "notes"):
    for r in FEED[feed]:
        txt = str(r.get("activityHistory") or "")
        if not txt:
            continue
        for m in BY.finditer(txt):
            n = " ".join(m.group(1).split())
            n = re.sub(r"\s+for action$", "", n).strip()
            if not PERSON.match(n) or NOT_PERSON.match(n):
                continue
            k = n.lower()
            cand.setdefault(k, [n, 0])
            cand[k][1] += 1
        for m in STRICT_BY.finditer(txt):
            n = " ".join(m.group(1).split())
            n = re.sub(r"\s+for action$", "", n).strip()
            if PERSON.match(n) and not NOT_PERSON.match(n):
                strict.add(n.lower())

roster = list(owners.values())
for k, (n, c) in cand.items():
    if k not in owners and (c >= 3 or k in strict):   # three generic credits, or one in a sentence VisiLean wrote
        roster.append(n)
roster = sorted(set(roster))   # parsing vocabulary - keeps excluded names so their events are still recognised (and then dropped)

# Department of each user. On the plain type=task feed VisiLean carries the user in `owner`
# and that user's department in `organisation` (KP, 09-Sep-2026), so this is the recorded
# answer rather than something inferred from which activities a person happens to update.
# One entry per user; a user who owns no task simply has none.
_by_user = {}
for r in FEED["task"]:
    who = " ".join(str(r.get("owner") or "").split())
    org = " ".join(str(r.get("organisation") or "").split())
    if who and org:
        _by_user.setdefault(who, {})
        _by_user[who][org] = _by_user[who].get(org, 0) + 1
dept_by_user = {who: max(orgs.items(), key=lambda kv: kv[1])[0] for who, orgs in _by_user.items()}

# Everyone the schedule assigns work to, with how much. A user can own hundreds of
# activities and never once open VisiLean - Santosh Singh owns 3,214 and has never updated
# - and that absence is the adoption finding, so the reports need the assignee list and not
# just the people the audit trail happens to mention.
_tasks_owned = {}
for r in FEED["task"]:
    who = " ".join(str(r.get("owner") or "").split())
    if who:
        _tasks_owned[who] = _tasks_owned.get(who, 0) + 1
assignees = [{"name": who, "tasks": n, "dept": dept_by_user.get(who, "")}
             for who, n in sorted(_tasks_owned.items(), key=lambda kv: -kv[1])
             if who.lower() not in EXCLUDE_ACTORS]

# Departments for users VisiLean has no record for, because they own no task on this
# project. Add "name": "Department - ORG" here and the report shows it as KP's answer
# rather than VisiLean's; the task feed always wins where it has an entry.
DEPT_MANUAL = {}
dept_manual = {k: v for k, v in DEPT_MANUAL.items()
               if not any(k.lower() == w.lower() for w in dept_by_user)}
print("departments from the task feed (%d users): %s"
      % (len(dept_by_user), ", ".join("%s=%s" % kv for kv in sorted(dept_by_user.items()))))
ROSTER_RE = re.compile("(" + "|".join(re.escape(n) for n in sorted(roster, key=len, reverse=True)) + ")")
print("roster (%d): %s" % (len(roster), ", ".join(roster)))

LEAD = re.compile(r"^" + ROSTER_RE.pattern + r"\s*[:\.]")
RESULT_OF = re.compile(r"as a result of action by\s+" + ROSTER_RE.pattern)
BY_ROSTER = re.compile(r"\bby\s+" + ROSTER_RE.pattern)


def actor(sentence):
    s = " ".join(sentence.split())
    m = LEAD.match(s)                       # "NUR ISLAM : ...", "Sabir Ahmed. Note added: ..."
    if m:
        return m.group(1)
    m = RESULT_OF.search(s)                 # explicit attribution
    if m:
        return m.group(1)
    hits = BY_ROSTER.findall(s)             # "assigned to X by Y" -> Y acts
    if hits:
        return hits[-1]
    m = ROSTER_RE.search(s)
    return m.group(1) if m else "Unattributed"


ACTIONS = (
    ("import", re.compile(r"imported from file")),
    ("bulk", re.compile(r"bulk completed")),
    ("forced", re.compile(r"was forced ready")),
    ("assign", re.compile(r"assigned to")),
    ("ownerchg", re.compile(r"Owner\.? changed|changed for Task")),
    ("fieldchg", re.compile(r"Trade set to|Task type is now set|Make Ready Date changed")),
    ("pct", re.compile(r"New completion percentage")),
    ("status", re.compile(r"set to '")),
    ("resched", re.compile(r"rescheduled|date changed")),
    ("actionitem", re.compile(r"To be acted upon by")),
    ("constraint", re.compile(r"constraint")),
    ("note", re.compile(r"Note added|Note:|note:|Updated content|\s:\s")),
)


def action(sentence):
    for key, rx in ACTIONS:
        if rx.search(sentence):
            return key
    return "other"


# a sentence, not a stray field value ("Construction" arrives in IncludeOther rows)
SENTENCE = re.compile(r"\bby\b|Task '|Note|note|\s:\s")
CANON = {}


def canon(name):
    k = " ".join(name.split())
    return CANON.setdefault(k.lower(), k)


# ---------- events ----------
seen = set()
events = []
lo = hi = None
for feed in ("hist", "notes"):
    for r in FEED[feed]:
        txt = str(r.get("activityHistory") or "").strip()
        if len(txt) < 8 or not SENTENCE.search(txt):
            continue
        key = (str(r.get("taskId")), str(r.get("historyDateTime")), txt)
        if key in seen:
            continue
        seen.add(key)

        ts = ""
        raw = str(r.get("historyDateTime") or "")
        if raw:
            try:
                d = datetime.strptime(raw, "%d/%m/%Y %H:%M:%S")
                ts = d.strftime("%Y-%m-%dT%H:%M:%S")
                lo = d if lo is None or d < lo else lo
                hi = d if hi is None or d > hi else hi
            except ValueError:
                ts = ""

        who = canon(actor(txt))
        if who.lower() in EXCLUDE_ACTORS:
            continue
        cf = r.get("customField") or {}
        events.append([
            ts,
            who,
            action(txt),
            str(r.get("taskId") or ""),
            str(r.get("taskName") or ""),
            str(cf.get("Department") or "").strip(),
            str(cf.get("Activity Type") or r.get("taskType") or "").strip(),
            str(r.get("location") or r.get("zoneName") or "").strip(),
            str(cf.get("Package") or "").strip(),
            str(cf.get("Owner.") or r.get("owner") or "").strip(),
            str(r.get("organisation") or "").strip(),
            " ".join(txt.split()),
            str(r.get("status") or "").strip(),
            str(r.get("trade") or "").strip(),
            1 if str(cf.get("Critical Activity") or "").strip().lower() == "yes" else 0,
        ])

actors = sorted({e[1] for e in events})
now = datetime.now(IST)
meta = {
    "project": "KPIGEL-NTPC Bikaner Block 8 (200MW)",
    "projectShort": "NTPC Bikaner Block 8 · 200 MW",
    "client": "KPI Green Energy",
    "generatedAt": now.strftime("%d-%b-%Y %H:%M") + " IST",
    "generatedAtEpoch": int(now.timestamp()),
    "events": len(events),
    "tasks": len({e[3] for e in events}),
    "actors": len(actors),
    "rosterSize": len([n for n in roster if n.lower() not in EXCLUDE_ACTORS]),
    "deptByUser": dept_by_user,
    "assignees": assignees,
    "deptManual": dept_manual,
    "tasksInProject": len(FEED["task"]),
    "locFilled": sum(1 for e in events if e[7]),
    "firstEvent": lo.strftime("%Y-%m-%d") if lo else "",
    "lastEvent": hi.strftime("%Y-%m-%d") if hi else "",
    "source": ("VisiLean PowerBI API · type=task with IncludeStatusChange / IncludeReschedule / "
               "IncludeTaskCreation / IncludeQuantities / IncludeConstraintNotes / IncludeOther"),
    "noAttachments": True,
    "excluded": sorted(EXCLUDE_ACTORS),
}
out = {"meta": meta, "cols": ["ts", "actor", "action", "tid", "task", "dept", "atype",
                              "loc", "pkg", "owner", "ownship", "detail",
                              "status", "trade", "crit"], "events": events}
dst = os.path.join(SCR, "adoption_data.json")
with open(dst, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
print("wrote %s | %d events, %d actors, %d activities, window %s -> %s"
      % (dst, len(events), len(actors), meta["tasks"], meta["firstEvent"], meta["lastEvent"]))
