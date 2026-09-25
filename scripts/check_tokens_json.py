# -*- coding: utf-8 -*-
"""Check VisiLean tokens against VisiLean BEFORE pasting them into GitHub.

    python scripts/check_tokens_json.py tokens.json

The file has the shape of the VL_TOKENS_JSON secret - one token per project, flat:

    {
      "ntpc": "...",
      "sjvn": "..."
    }

Each project's one token is tried against all three feeds its dashboard reads (tasks,
history, constraints), so this proves the token really covers every feed and not just
the task list. A wrong or mismatched token comes back as a quiet HTTP 400 - "This API
access token is not valid for the requested project" - which is easy to miss once it is
buried in a runner log, so it is worth catching while the file is still in front of you.

Prints only row counts and errors - never a token.
"""
import io, json, os, sys, urllib.error, urllib.request

SCR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCR)
from vl_token import TokenError, parse_tokens_map            # noqa: E402

BASE = "https://app.visilean.net/pb/PowerBiAPI/resource/powerBi/getData/visilean"
HIST_FLAGS = ("&IncludeStatusChange=true&IncludeReschedule=true"
              "&IncludeQuantities=true&IncludeConstraintNotes=true")
# feed name -> (type= value, extra flags), exactly as the builders call them
FEEDS = {"task": ("task", ""), "history": ("task", HIST_FLAGS),
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
    t, flags = FEEDS[kind]
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


def check_map(tokens, ids):
    """Probe every feed for every project in a flat {key: token} map. Prints the table
    and returns the number of problems."""
    bad = 0
    print("%-11s %-15s %s" % ("PROJECT", "FEED", "VISILEAN SAYS"))
    print("-" * 64)
    for key in sorted(tokens):
        pid = ids.get(key)
        if not pid:
            print("%-11s %-15s no scripts/projects/%s.json - unknown project key" % (key, "-", key))
            bad += 1
            continue
        tok = tokens[key]
        if not tok:
            print("%-11s %-15s missing" % (key, "-"))
            bad += 1
            continue
        result = {}
        for feed in FEEDS:
            ok, detail = probe(tok, pid, feed)
            print("%-11s %-15s %s%s" % (key, feed, "OK  " if ok else "FAILED  ", detail))
            result[feed] = ok
            bad += 0 if ok else 1
        if result.get("task") and not result.get("constraintLog"):
            print("%-11s %-15s ^ the task feed works but constraintLog does not: either this"
                  % ("", ""))
            print("%-11s %-15s   project has no constraints report (the Constraints tab will"
                  % ("", ""))
            print("%-11s %-15s   just be empty), or the token pre-dates one-token-per-project -"
                  % ("", ""))
            print("%-11s %-15s   ask VisiLean for a fresh project token." % ("", ""))
    return bad


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: check_tokens_json.py <tokens.json>")
    path = sys.argv[1]
    if not os.path.exists(path):
        print("No such file: %s" % path)
        return 1
    try:
        tokens = parse_tokens_map(io.open(path, encoding="utf-8").read(), path)
    except TokenError as e:
        print(str(e))
        print("GitHub will accept it, but every workflow will fail on it - fix it now.")
        return 1
    if not tokens:
        print("%s holds no tokens." % path)
        return 1

    bad = check_map(tokens, project_ids())
    print()
    if bad:
        print("%d problem(s). VisiLean distinguishes two failures, and they need different fixes:" % bad)
        print("  HTTP 400 'not valid for the requested project' - a real token, filed under the")
        print("           wrong key. Move it to the project it was generated for.")
        print("  HTTP 500 'API does not exist'                  - VisiLean does not recognise the")
        print("           token at all: mistyped, truncated, or revoked. Generate it again.")
        return 1
    print("Every token works for all three feeds. Paste the file into the VL_TOKENS_JSON")
    print("secret, or set each entry as its own VL_TOKEN_<KEY> secret (VL_TOKEN_SJVN, ...).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
