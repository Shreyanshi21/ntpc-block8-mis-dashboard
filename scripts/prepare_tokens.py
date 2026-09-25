# -*- coding: utf-8 -*-
"""Turn whatever form the tokens arrived in into the secret values, verified.

    python scripts/prepare_tokens.py <file-from-visilean> [-o tokens.secret.json] [--project sjvn]

VisiLean issues one API token per project, and it serves every feed. This accepts any
of the ways such tokens get passed around:

  * a flat map keyed by project        {"sjvn": "<token>", "ntpc": "<token>"}
  * Power BI feed URLs, one per line, in a .txt or .json - the accessToken and
    projectId are read out of each URL; any feed's URL will do
  * ONE project's token with --project <key>: a bare token, a single URL, or the
    old {"task": "...", "history": "...", "constraintLog": "..."} map
  * the old nested vl_tokens.json {"sjvn": {"task": "...", ...}} - collapsed to one
    token per project, provided the three really are the same token
  * any mixture of the above

If a project turns up with two different tokens, nothing is written: only one can be
current, and guessing would file a stale token under a live project.

Then it asks VisiLean about every feed for every project and writes the flat map to a
file. Tokens are never printed: the output goes to a file you open and copy from, so
nothing lands in a terminal history or a chat transcript.

Delete the file once the secrets are saved.
"""
import argparse, json, os, re, sys

SCR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCR)
from check_tokens_json import check_map, project_ids        # noqa: E402

# keys the old per-feed shape used for one project's tokens
FEED_KEYS = {"task", "history", "constraintlog", "constraints", "constraint", "hist",
             "notes", "token"}


def harvest_urls(text, ids, found, notes):
    """Pull accessToken + projectId out of any Power BI feed URLs in the text."""
    by_pid = {v.lower(): k for k, v in ids.items() if v}
    for m in re.finditer(r"https?://\S*accessToken=\S+", text, re.I):
        url = m.group(0)
        tok = re.search(r"accessToken=([^&\s\"']+)", url, re.I)
        pid = re.search(r"projectId=([^&\s\"']+)", url, re.I)
        if not tok:
            continue
        key = by_pid.get(pid.group(1).lower()) if pid else None
        if not key:
            notes.append("a URL had projectId=%s, which matches no scripts/projects/*.json"
                         % (pid.group(1)[:12] + "..." if pid else "(none)"))
            continue
        found.setdefault(key, set()).add(tok.group(1))


def _leaves(v):
    """Every string inside a (possibly nested) dict."""
    if isinstance(v, str):
        yield v.strip()
    elif isinstance(v, dict):
        for x in v.values():
            for s in _leaves(x):
                yield s


def normalise(raw, ids, project, notes, found):
    """File contents that parsed as JSON -> found[key] = {tokens}."""
    if isinstance(raw, str):
        if project:
            found.setdefault(project, set()).add(raw.strip())
        else:
            notes.append("the file is a bare token but does not say which project - "
                         "re-run with --project <key>")
        return
    if not isinstance(raw, dict):
        return
    one_project = {}
    for k, v in raw.items():
        kl = str(k).strip().lower()
        if kl in ids:
            leaves = [s for s in _leaves(v) if s]
            if isinstance(v, dict) and leaves:
                notes.append("%s was in the old per-feed shape; using its %d entr%s as the "
                             "one token" % (kl, len(leaves), "y" if len(leaves) == 1 else "ies"))
            found.setdefault(kl, set()).update(leaves)
        elif kl.startswith("adopt_"):
            notes.append("ignored %r - the adoption tracker now uses the ntpc token" % k)
        elif kl in FEED_KEYS:
            one_project[kl] = v
        else:
            notes.append("ignored unknown key %r" % k)
    if one_project:
        leaves = [s for x in one_project.values() for s in _leaves(x) if s]
        if project:
            found.setdefault(project, set()).update(leaves)
        else:
            notes.append("this file holds one project's token(s) but does not say which - "
                         "re-run with --project <key>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("infile")
    ap.add_argument("-o", "--out", default="tokens.secret.json")
    ap.add_argument("--project", help="project key, when the file holds one project's token")
    a = ap.parse_args()
    project = (a.project or "").strip().lower()

    if not os.path.exists(a.infile):
        print("No such file: %s" % a.infile); return 1
    text = open(a.infile, encoding="utf-8", errors="replace").read()
    ids, notes, found = project_ids(), [], {}
    if project and project not in ids:
        print("--project %s matches no scripts/projects/*.json (known: %s)"
              % (project, ", ".join(sorted(ids)))); return 1

    try:
        raw = json.loads(text)
    except Exception:
        raw = None
    if raw is not None:
        normalise(raw, ids, project, notes, found)
    harvest_urls(text, ids, found, notes)
    if not found and project and text.strip() and not re.search(r"\s", text.strip()):
        found[project] = {text.strip()}                    # a bare token in a .txt

    for n in notes:
        print("note: " + n)
    found = {k: v for k, v in found.items() if v}
    if not found:
        print("Found no tokens in %s." % a.infile)
        print('Expected {"sjvn": "<token>", ...}, Power BI feed URLs, or one project\'s '
              "token with --project <key>.")
        return 1

    conflicts = sorted(k for k, v in found.items() if len(v) > 1)
    if conflicts:
        for k in conflicts:
            print("ERROR: %s has %d different tokens across the input. VisiLean issues one "
                  "token per project; check which is current and remove the other."
                  % (k, len(found[k])))
        print("Nothing written.")
        return 1
    out = {k: next(iter(v)) for k, v in found.items()}

    print()
    bad = check_map(out, ids)
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=2, sort_keys=True)
    print("\nWrote %s (%d project%s)." % (a.out, len(out), "" if len(out) == 1 else "s"))
    if bad:
        print("%d feed(s) did not work - fix those before pasting." % bad)
        print("  HTTP 400 'not valid for the requested project' = right token, wrong key.")
        print("  HTTP 500 'API does not exist'                  = token not recognised.")
        return 1
    print("Every token works for all three feeds. Open that file and either copy all of it")
    print("into the VL_TOKENS_JSON secret, or set each entry as its own VL_TOKEN_<KEY>")
    print("secret (VL_TOKEN_SJVN, VL_TOKEN_NTPC, ...). Then delete the file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
