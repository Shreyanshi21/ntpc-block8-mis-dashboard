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

Tokens come from env (VL_TOKEN_ADOPT_TASK / _HIST / _NOTES, set as GitHub Actions
secrets) or scripts/vl_tokens.json next to this script (never committed).
Emits scripts/adoption_data.json.
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

FEEDS = {
    "task": ("VL_TOKEN_ADOPT_TASK", ""),
    "hist": ("VL_TOKEN_ADOPT_HIST",
             "&IncludeStatusChange=true&IncludeReschedule=true"
             "&IncludeTaskCreation=true&IncludeQuantities=true"),
    "notes": ("VL_TOKEN_ADOPT_NOTES", "&IncludeConstraintNotes=true&IncludeOther=true"),
}


def _tokens():
    t = {k: os.environ.get(env, "") for k, (env, _) in FEEDS.items()}
    if not all(t.values()):
        f = os.path.join(SCR, "vl_tokens.json")
        if os.path.exists(f):
            j = json.load(open(f, encoding="utf-8"))
            for k in FEEDS:
                t[k] = t[k] or j.get("adopt_" + k, "") or j.get(k, "")
    missing = [k for k, v in t.items() if not v]
    if missing:
        raise SystemExit("no VisiLean token for: %s (set VL_TOKEN_ADOPT_* or scripts/vl_tokens.json)"
                         % ", ".join(missing))
    return t


TOKENS = _tokens()


def fetch(kind, attempts=3):
    url = "%s?accessToken=%s&projectId=%s&type=task%s" % (BASE, TOKENS[kind], PROJECT, FEEDS[kind][1])
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "VisiLean-Adoption"})
            raw = urllib.request.urlopen(req, timeout=300).read()
            return json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as e:                                    # noqa: BLE001
            last = e
            print("fetch %s attempt %d/%d failed: %s" % (kind, i + 1, attempts, e))
            if i + 1 < attempts:
                time.sleep(15 * (i + 1))
    raise last


print("fetching VisiLean APIs...")
try:
    FEED = {k: fetch(k) for k in ("task", "hist", "notes")}
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

owners = {}
for r in FEED["task"]:
    n = " ".join(str(r.get("owner") or "").split())
    if n:
        owners[n.lower()] = n

cand = {}
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

roster = list(owners.values())
for k, (n, c) in cand.items():
    if k not in owners and c >= 3:          # credited at least three times = a real actor
        roster.append(n)
roster = sorted(set(roster))
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

        cf = r.get("customField") or {}
        events.append([
            ts,
            canon(actor(txt)),
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
    "rosterSize": len(roster),
    "tasksInProject": len(FEED["task"]),
    "locFilled": sum(1 for e in events if e[7]),
    "firstEvent": lo.strftime("%Y-%m-%d") if lo else "",
    "lastEvent": hi.strftime("%Y-%m-%d") if hi else "",
    "source": ("VisiLean PowerBI API · type=task with IncludeStatusChange / IncludeReschedule / "
               "IncludeTaskCreation / IncludeQuantities / IncludeConstraintNotes / IncludeOther"),
    "noAttachments": True,
}
out = {"meta": meta, "cols": ["ts", "actor", "action", "tid", "task", "dept", "atype",
                              "loc", "pkg", "owner", "ownship", "detail"], "events": events}
dst = os.path.join(SCR, "adoption_data.json")
with open(dst, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
print("wrote %s | %d events, %d actors, %d activities, window %s -> %s"
      % (dst, len(events), len(actors), meta["tasks"], meta["firstEvent"], meta["lastEvent"]))
