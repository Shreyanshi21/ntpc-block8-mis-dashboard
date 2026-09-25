# -*- coding: utf-8 -*-
"""Turn whatever form the tokens arrived in into the VL_TOKENS_JSON secret, verified.

    python scripts/prepare_tokens.py <file-from-shreyanshi> [-o tokens.secret.json]

Accepts any of these, because tokens get passed around in all of them:

  * a vl_tokens.json keyed by project      {"sjvn": {"task": "...", ...}, ...}
  * a flat map for ONE project             {"task": "...", "history": "...", ...}
    (say which with --project sjvn)
  * Power BI feed URLs, one per line, in a .txt or .json - the accessToken and
    projectId are read out of each URL and filed under the matching project
  * any mixture of the above

Then it asks VisiLean about every feed and writes the normalised secret to a file.
Tokens are never printed: the output goes to a file you open and copy from, so nothing
lands in a terminal history or a chat transcript.

Delete the file once the secret is saved.
"""
import argparse, json, os, re, sys

SCR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCR)
from check_tokens_json import probe, project_ids            # noqa: E402

SLOTS = ("task", "history", "constraintLog")
# how a feed URL identifies itself -> which slot it fills
URL_SLOT = [("type=constraintlog", "constraintLog"),
            ("includestatuschange=true", "history"),
            ("type=task", "task")]
ALIASES = {"constraintlog": "constraintLog", "constraints": "constraintLog",
           "constraint": "constraintLog", "hist": "history", "notes": "constraintLog",
           "task": "task", "history": "history"}


def slot_of(url_lower):
    for needle, slot in URL_SLOT:
        if needle in url_lower:
            return slot
    return None


def harvest_urls(text, ids, out, notes):
    """Pull accessToken + projectId out of any Power BI feed URLs in the text."""
    by_pid = {v.lower(): k for k, v in ids.items() if v}
    for m in re.finditer(r"https?://\S*accessToken=\S+", text):
        url = m.group(0)
        low = url.lower()
        tok = re.search(r"accesstoken=([^&\s\"']+)", low)
        pid = re.search(r"projectid=([^&\s\"']+)", low)
        if not tok:
            continue
        slot = slot_of(low)
        key = by_pid.get(pid.group(1)) if pid else None
        if not key:
            notes.append("a URL had projectId=%s, which matches no scripts/projects/*.json"
                         % (pid.group(1)[:12] + "..." if pid else "(none)"))
            continue
        if not slot:
            notes.append("could not tell which feed a %s URL is - skipped" % key)
            continue
        # take the token verbatim from the original-case URL
        raw = re.search(r"accessToken=([^&\s\"']+)", url, re.I)
        out.setdefault(key, {})[slot] = raw.group(1)


def normalise(raw, ids, project, notes):
    out = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            kl = str(k).strip().lower()
            if isinstance(v, dict):                      # keyed by project
                if kl in ids:
                    out[kl] = {ALIASES.get(str(s).lower(), s): t
                               for s, t in v.items() if isinstance(t, str)}
                else:
                    notes.append("ignored unknown project key %r" % k)
            elif isinstance(v, str) and kl.startswith("adopt_"):
                out[kl] = v
        flat = {ALIASES.get(str(k).lower()): v for k, v in raw.items()
                if isinstance(v, str) and str(k).lower() in ALIASES}
        if flat and project:
            out.setdefault(project, {}).update(flat)
        elif flat and not any(isinstance(v, dict) for v in raw.values()):
            notes.append("this file holds one project's tokens but does not say which - "
                         "re-run with --project <key>")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("infile")
    ap.add_argument("-o", "--out", default="tokens.secret.json")
    ap.add_argument("--project", help="project key, when the file holds one project's tokens")
    a = ap.parse_args()

    if not os.path.exists(a.infile):
        print("No such file: %s" % a.infile); return 1
    text = open(a.infile, encoding="utf-8", errors="replace").read()
    ids, notes = project_ids(), []

    try:
        raw = json.loads(text)
    except Exception:
        raw = None
    out = normalise(raw, ids, (a.project or "").strip().lower(), notes) if raw else {}
    harvest_urls(text, ids, out, notes)

    if not out:
        print("Found no tokens in %s." % a.infile)
        print("Expected a vl_tokens.json, a flat {task/history/constraintLog} map "
              "(with --project), or Power BI feed URLs.")
        for n in notes:
            print("  note: " + n)
        return 1

    for n in notes:
        print("note: " + n)

    print("\n%-11s %-15s %s" % ("PROJECT", "FEED", "VISILEAN SAYS"))
    print("-" * 64)
    bad = 0
    for key in sorted(k for k in out if isinstance(out[k], dict)):
        for slot in SLOTS:
            tok = out[key].get(slot, "")
            if not tok:
                print("%-11s %-15s missing" % (key, slot)); bad += 1; continue
            ok, detail = probe(tok, ids.get(key, ""), slot)
            print("%-11s %-15s %s%s" % (key, slot, "OK  " if ok else "FAILED  ", detail))
            bad += 0 if ok else 1

    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=2, sort_keys=True)
    print("\nWrote %s (%d project%s)." % (a.out, len(out), "" if len(out) == 1 else "s"))
    if bad:
        print("%d feed(s) did not work - fix those before pasting." % bad)
        print("  HTTP 400 'not valid for the requested project' = right token, wrong key.")
        print("  HTTP 500 'API does not exist'                  = token not recognised.")
        return 1
    print("Every token works. Open that file, copy all of it into the VL_TOKENS_JSON")
    print("secret, then delete the file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
