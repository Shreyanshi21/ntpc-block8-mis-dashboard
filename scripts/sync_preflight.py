# -*- coding: utf-8 -*-
"""Resolve this project's VisiLean credentials before the refresh loop runs.

    python scripts/sync_preflight.py <ntpc|sjvn|adani|adanis7|floating|adopt>

Two jobs:

1  Materialise `scripts/vl_tokens.json` from the single `VL_TOKENS_JSON` secret, if it
   is set. A VisiLean token only works for the project it was generated for, so every
   project needs its own three - but carrying them as fifteen separate repository
   secrets makes setup tedious and rotation worse. The builders already fall back to a
   `vl_tokens.json` keyed by project, so one secret holding that file serves every
   dashboard. Per-project `VL_TOKEN_*_<KEY>` secrets still win if they are set, so
   nothing that already works changes.

   The file is gitignored, and the builds assert no token reaches the published HTML.

2  Say whether this project is configured, as `configured=true|false` on the step
   output, so the workflow can SKIP the loop rather than fail.

   Why skip and not fail: a workflow that cannot authenticate is not a broken build, it
   is one that was never set up - and failing it every half hour mails everybody on the
   repo, dozens of times a day, for a condition nobody can fix by retrying. Not
   configured is a warning and a clean skip. Anything else - a rejected token, a
   VisiLean outage, a build error - still fails loudly, and the daily sync-health run
   reports what is not configured once a day rather than once a cycle.
"""
import io, json, os, sys

SCR = os.path.dirname(os.path.abspath(__file__))
TOKENS_FILE = os.path.join(SCR, "vl_tokens.json")

# project key -> (human name, the three env names, how vl_tokens.json holds them)
PROJECTS = {
    "ntpc":     ("NTPC Bikaner Block 8", "VL_TOKEN_%s", ("task", "history", "constraintLog")),
    "sjvn":     ("SJVN Khavda", "VL_TOKEN_%s_SJVN", ("task", "history", "constraintLog")),
    "adani":    ("Adani S6a", "VL_TOKEN_%s_ADANI", ("task", "history", "constraintLog")),
    "adanis7":  ("Adani S7", "VL_TOKEN_%s_ADANIS7", ("task", "history", "constraintLog")),
    "floating": ("Floating Solar", "VL_TOKEN_%s_FLOATING", ("task", "history", "constraintLog")),
}
SLOTS = ("TASK", "HISTORY", "CONSTRAINTS")
ADOPT = ("Adoption tracker",
         ("VL_TOKEN_ADOPT_TASK", "VL_TOKEN_ADOPT_HIST", "VL_TOKEN_ADOPT_NOTES"),
         ("adopt_task", "adopt_hist", "adopt_notes"))


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


def write_token_file():
    """Turn the one VL_TOKENS_JSON secret into the file the builders already read.

    With no secret set, fall back to whatever vl_tokens.json is already on disk - that
    is how a developer's machine is set up, and reporting it as "not configured" would
    be a lie."""
    blob = os.environ.get("VL_TOKENS_JSON", "").strip()
    if not blob:
        if os.path.exists(TOKENS_FILE):
            try:
                return json.load(io.open(TOKENS_FILE, encoding="utf-8"))
            except Exception:
                return None
        return None
    try:
        parsed = json.loads(blob)
    except Exception as e:
        print("::error title=VL_TOKENS_JSON is not valid JSON::%s" % e)
        summary(["### VL_TOKENS_JSON is not valid JSON", "",
                 "```", str(e), "```", "",
                 "Fix the secret's contents - see SYNC-SETUP.md for the expected shape."])
        sys.exit(1)
    if not isinstance(parsed, dict):
        print("::error title=VL_TOKENS_JSON must be a JSON object::got %s" % type(parsed).__name__)
        sys.exit(1)
    # Only ever write the file on a runner. Locally this would silently overwrite a
    # developer's own tokens, which is not a trade a preflight check should make.
    if os.environ.get("GITHUB_ACTIONS") == "true" or not os.path.exists(TOKENS_FILE):
        io.open(TOKENS_FILE, "w", encoding="utf-8").write(json.dumps(parsed))
        print("wrote %s from VL_TOKENS_JSON (%d top-level keys)" % (TOKENS_FILE, len(parsed)))
    else:
        print("VL_TOKENS_JSON set, but %s already exists - leaving it alone (not CI)" % TOKENS_FILE)
    return parsed


def from_file(parsed, key, slots):
    """What the token file offers for this project, mirroring the builders' own lookup."""
    if not parsed:
        return {}
    if key == "adopt":
        return {s: parsed.get(s, "") for s in slots}
    sub = parsed.get(key)
    if isinstance(sub, dict):
        return {s: sub.get(s, "") for s in slots}
    # a flat file (the legacy NTPC shape) only speaks for NTPC
    if key == "ntpc":
        return {s: parsed.get(s, "") for s in slots}
    return {}


def main():
    key = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if key != "adopt" and key not in PROJECTS:
        raise SystemExit("usage: sync_preflight.py <%s|adopt>" % "|".join(PROJECTS))

    parsed = write_token_file()

    if key == "adopt":
        label, envs, slots = ADOPT
    else:
        label, pat, slots = PROJECTS[key]
        envs = tuple(pat % s for s in SLOTS)

    have = from_file(parsed, key, slots)
    missing = []
    for env_name, slot in zip(envs, slots):
        if os.environ.get(env_name, "").strip():
            continue                      # an explicit per-project secret wins
        if have.get(slot, "").strip():
            continue                      # supplied by VL_TOKENS_JSON
        missing.append(env_name)

    if not missing:
        print("%s: credentials resolved" % label)
        emit("configured", "true")
        return 0

    # Not set up. Warn, skip, and do NOT fail - see the module docstring.
    print("::warning title=%s sync is not configured::Skipping. Missing: %s"
          % (label, " ".join(missing)))
    summary([
        "### %s — sync not configured, skipped" % label,
        "",
        "No VisiLean credentials for this project, so there is nothing to refresh.",
        "The dashboard keeps showing its last published build, and says so on the page",
        "once that build is over a day old.",
        "",
        "Provide them **either** in the single `VL_TOKENS_JSON` secret:",
        "",
        "```json",
        '{ "%s": { "task": "…", "history": "…", "constraintLog": "…" } }'
        % (key if key != "adopt" else "adopt_task\": \"…\", \"adopt_hist\": \"…\", \"adopt_notes"),
        "```",
        "",
        "**or** as individual secrets: " + ", ".join("`%s`" % m for m in missing),
        "",
        "See [SYNC-SETUP.md](../blob/master/SYNC-SETUP.md).",
    ])
    emit("configured", "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
