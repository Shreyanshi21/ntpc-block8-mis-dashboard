# -*- coding: utf-8 -*-
"""Say whether this project's VisiLean credentials exist before the refresh loop runs.

    python scripts/sync_preflight.py <ntpc|sjvn|adani|adanis7|floating|adopt>

VisiLean issues one API token per project, and it serves every feed a dashboard reads
(tasks, history, constraints). The token is looked up in this order - see vl_token.py:

  1. the per-project repository secret          VL_TOKEN_<KEY>       e.g. VL_TOKEN_SJVN
  2. that project's entry in VL_TOKENS_JSON     {"sjvn": "<token>", "ntpc": "<token>"}
  3. locally, the same flat map in the gitignored scripts/vl_tokens.json

Every candidate found is available to the builders. If VisiLean rejects the first they
switch to the next and flag the broken secret on the run, so setting both is a safety
net, not a duplication. The adoption tracker and Updates report read the NTPC project,
so `adopt` resolves the ntpc token.

The verdict goes to the step output as `configured=true|false`, so the workflow can
SKIP the loop rather than fail.

   Why skip and not fail: a workflow that cannot authenticate is not a broken build, it
   is one that was never set up - and failing it every half hour mails everybody on the
   repo, dozens of times a day, for a condition nobody can fix by retrying. Not
   configured is a warning and a clean skip. Anything else - a rejected token, a
   VisiLean outage, a build error - still fails loudly, and the daily sync-health run
   reports what is not configured once a day rather than once a cycle.

A secret that exists but cannot be used (not JSON, or the old three-tokens-per-project
shape) is a different thing: that fails the run immediately, because it is a mistake
somebody can fix right now and every workflow shares it.
"""
import io, os, sys

SCR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCR)
from vl_token import KEYS, LABELS, TokenError, candidates, env_name, tokens_from_env  # noqa: E402

# workflow argument -> project key whose token it needs
ARGS = {k: k for k in KEYS}
ARGS["adopt"] = "ntpc"
LABEL_OVERRIDE = {"adopt": "Adoption tracker + Updates (NTPC project)"}


def emit(name, value):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with io.open(out, "a", encoding="utf-8") as f:
            f.write("%s=%s\n" % (name, value))


def summary(lines):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with io.open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    arg = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if arg not in ARGS:
        raise SystemExit("usage: sync_preflight.py <%s>" % "|".join(ARGS))
    key = ARGS[arg]
    label = LABEL_OVERRIDE.get(arg, LABELS[key])

    try:
        cands = candidates(key)
        json_map = tokens_from_env()
    except TokenError as e:
        print("::error title=VisiLean token secret is not usable::%s" % e)
        summary(["### VisiLean token secret is not usable", "",
                 "```", str(e), "```", "",
                 "Fix the secret - see [SYNC-SETUP.md](../blob/master/SYNC-SETUP.md)."])
        return 1

    if cands:
        sources = [s for _, s in cands]
        line = "%s: credentials from %s" % (label, sources[0])
        if len(sources) > 1:
            line += "; fallback " + ", ".join(sources[1:])
        print(line)
        if sources[0] != env_name(key):
            print("::notice title=%s has no %s secret::Using the VL_TOKENS_JSON entry only, "
                  "so there is no fallback if VisiLean rejects it." % (label, env_name(key)))
        emit("configured", "true")
        return 0

    # Not set up. Warn, skip, and do NOT fail - see the module docstring.
    if os.environ.get("VL_TOKENS_JSON", "").strip():
        have = sorted(json_map)
        print('VL_TOKENS_JSON is set but has no "%s" entry (it has: %s)'
              % (key, ", ".join(have) if have else "nothing"))
        unknown = sorted(k for k in json_map if k not in KEYS)
        if unknown:
            print("ignored unknown keys in VL_TOKENS_JSON: %s" % ", ".join(unknown))
    print('::warning title=%s sync is not configured::Skipping. Set the %s secret, or add '
          '"%s" to VL_TOKENS_JSON.' % (label, env_name(key), key))
    summary([
        "### %s — sync not configured, skipped" % label,
        "",
        "No VisiLean token for this project, so there is nothing to refresh.",
        "The dashboard keeps showing its last published build, and says so on the page",
        "once that build is over a day old.",
        "",
        "VisiLean issues one API token per project; it serves the task, history and",
        "constraints feeds. Provide it **either** as the repository secret `%s`," % env_name(key),
        "**or** as an entry in the single `VL_TOKENS_JSON` secret:",
        "",
        "```json",
        '{ "%s": "<token>" }' % key,
        "```",
        "",
    ] + (["The adoption tracker and Updates report read the NTPC project, so they use",
          "the NTPC token.", ""] if arg == "adopt" else []) + [
        "See [SYNC-SETUP.md](../blob/master/SYNC-SETUP.md).",
    ])
    emit("configured", "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
