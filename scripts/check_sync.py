# -*- coding: utf-8 -*-
"""How fresh is every published dashboard, and is its sync alive?

    python scripts/check_sync.py

Reads the PUBLISHED pages, not the working copy, so it reports what a reader actually
sees. Age alone does not mean broken - the workers publish only when something changes -
so each project's workflow is checked too, and the two are reported separately.

Exits non-zero if any dashboard's sync is failing or has never run, so it can be used
as a check rather than only read by eye.
"""
import json, sys, time, urllib.request, urllib.error

REPO = "Vikas-visilean/ntpc-block8-mis-dashboard"
PAGES = "https://vikas-visilean.github.io/ntpc-block8-mis-dashboard"

# dashboard -> (published path, workflow that feeds it)
DASH = [
    ("NTPC Bikaner Block 8 · 200 MW", "v2", "refresh-v2.yml"),
    ("NTPC (v3 theme)", "v3", "refresh-v2.yml"),
    ("SJVN Khavda · 200 MW", "sjvn", "refresh-sjvn.yml"),
    ("Adani Green S6a · 234 MW", "adani", "refresh-adani.yml"),
    ("Adani Green S7 · 300 MW", "adani-s7", "refresh-adani-s7.yml"),
    ("Floating Solar · Kadana Dam", "floating", "refresh-floating.yml"),
    ("Adoption tracker", "adoption", "refresh-adoption.yml"),
    ("Updates", "updates", "refresh-adoption.yml"),
]


def get(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": "kp-sync-check",
                                               "Cache-Control": "no-cache"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace"))


def workflow_state(wf, cache={}):
    """Last run of this workflow: (verdict, url). Unauthenticated, so best-effort."""
    if wf in cache:
        return cache[wf]
    try:
        j = get(f"https://api.github.com/repos/{REPO}/actions/workflows/{wf}/runs?per_page=1")
        runs = j.get("workflow_runs") or []
        if not runs:
            out = ("never run", "")
        else:
            r = runs[0]
            if r.get("status") != "completed":
                out = ("running", r.get("html_url", ""))
            elif r.get("conclusion") == "success":
                out = ("ok", r.get("html_url", ""))
            else:
                out = ("FAILING", r.get("html_url", ""))
    except Exception as e:
        out = ("unknown (%s)" % str(e)[:24], "")
    cache[wf] = out
    return out


def main():
    now = time.time()
    bad = []
    print("%-32s %-10s %-22s %-11s %s" % ("DASHBOARD", "PATH", "LAST BUILT", "AGE", "SYNC"))
    print("-" * 96)
    for name, path, wf in DASH:
        try:
            m = get(f"{PAGES}/{path}/meta.json")
        except Exception as e:
            print("%-32s %-10s %s" % (name, path, "UNREACHABLE " + str(e)[:40]))
            bad.append(name)
            continue
        ep = m.get("generatedAtEpoch")
        if ep:
            h = (now - ep) / 3600
            age = "%d h" % round(h) if h < 48 else "%.1f days" % (h / 24)
        else:
            age = "?"
        verdict, url = workflow_state(wf)
        flag = ""
        if verdict in ("FAILING", "never run"):
            bad.append(name)
            flag = "  <- " + (url or "check Actions")
        print("%-32s %-10s %-22s %-11s %s%s"
              % (name, path, m.get("generatedAt", "?"), age, verdict, flag))

    print()
    if bad:
        print("Sync is not healthy for: " + ", ".join(sorted(set(bad))))
        print("See SYNC-SETUP.md - a project needs its own VisiLean tokens as repo secrets.")
        return 1
    print("All dashboards are syncing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
