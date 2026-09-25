# -*- coding: utf-8 -*-
"""Check a VL_TOKENS_JSON file against VisiLean BEFORE pasting it into GitHub.

    python scripts/check_tokens_json.py tokens.json

Hits every feed each project declares and reports what VisiLean actually says. A wrong
or mismatched token comes back as a quiet HTTP 400 - "This API access token is not
valid for the requested project" - which is easy to miss once it is buried in a runner
log, so it is worth catching while the file is still in front of you.

Reads the same shape the secret takes:

    {
      "sjvn":     {"task": "...", "history": "...", "constraintLog": "..."},
      "adopt_task": "...", "adopt_hist": "...", "adopt_notes": "..."
    }

Prints only row counts and errors - never a token.
"""
import json, os, sys, urllib.error, urllib.request

SCR = os.path.dirname(os.path.abspath(__file__))
BASE = "https://app.visilean.net/pb/PowerBiAPI/resource/powerBi/getData/visilean"
HIST_FLAGS = ("&IncludeStatusChange=true&IncludeReschedule=true"
              "&IncludeQuantities=true&IncludeConstraintNotes=true")
SLOT_TYPE = {"task": ("task", ""), "history": ("task", HIST_FLAGS),
             "constraintLog": ("constraintLog", "")}


def project_ids():
    ids = {}
    d = os.path.join(SCR, "projects")
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if fn.endswith(".json"):
            cfg = json.load(open(os.path.join(d, fn), encoding="utf-8"))
            ids[fn[:-5]] = cfg.get("projectId", "")
    return ids


def probe(token, pid, kind):
    """Returns (ok, detail). Never echoes the token."""
    t, flags = SLOT_TYPE[kind]
    url = "%s?accessToken=%s&projectId=%s&type=%s%s" % (BASE, token, pid, t, flags)
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "kp-token-check"}), timeout=120)
        body = json.loads(r.read().decode("utf-8", "replace"))
        n = len(body) if isinstance(body, list) else 1
        return True, "%d rows" % n
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8", "replace")).get("error", "")
        except Exception:
            msg = ""
        return False, "HTTP %s%s" % (e.code, " - " + msg if msg else "")
    except Exception as e:
        return False, str(e)[:70]


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: check_tokens_json.py <tokens.json>")
    path = sys.argv[1]
    if not os.path.exists(path):
        print("No such file: %s" % path)
        return 1
    try:
        blob = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        print("Not valid JSON: %s" % e)
        print("GitHub will accept it, but the first run will fail on this - fix it now.")
        return 1
    if not isinstance(blob, dict):
        print("The file must be a JSON object."); return 1

    ids = project_ids()
    bad = 0
    print("%-11s %-15s %s" % ("PROJECT", "FEED", "VISILEAN SAYS"))
    print("-" * 64)

    for key in sorted(k for k in blob if isinstance(blob[k], dict)):
        pid = ids.get(key)
        if not pid:
            print("%-11s %-15s no scripts/projects/%s.json - unknown project key" % (key, "-", key))
            bad += 1
            continue
        for slot in ("task", "history", "constraintLog"):
            tok = (blob[key] or {}).get(slot, "")
            if not tok:
                print("%-11s %-15s missing" % (key, slot)); bad += 1; continue
            ok, detail = probe(tok, pid, slot)
            print("%-11s %-15s %s%s" % (key, slot, "OK  " if ok else "FAILED  ", detail))
            bad += 0 if ok else 1

    adopt = {k: blob.get(k, "") for k in ("adopt_task", "adopt_hist", "adopt_notes")}
    if any(adopt.values()):
        # the adoption tracker reads NTPC's project with its own tokens
        pid = ids.get("ntpc", "")
        for k, slot in (("adopt_task", "task"), ("adopt_hist", "history"),
                        ("adopt_notes", "constraintLog")):
            if not adopt[k]:
                print("%-11s %-15s missing" % ("adoption", k)); bad += 1; continue
            ok, detail = probe(adopt[k], pid, slot)
            print("%-11s %-15s %s%s" % ("adoption", k, "OK  " if ok else "FAILED  ", detail))
            bad += 0 if ok else 1

    print()
    if bad:
        print("%d problem(s). VisiLean distinguishes two failures, and they need different fixes:" % bad)
        print("  HTTP 400 'not valid for the requested project' - a real token, filed under the")
        print("           wrong key. Move it to the project it was generated for.")
        print("  HTTP 500 'API does not exist'                  - VisiLean does not recognise the")
        print("           token at all: mistyped, truncated, or revoked. Generate it again.")
        return 1
    print("Every token works. Safe to paste into the VL_TOKENS_JSON secret.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
