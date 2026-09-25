# Dashboard sync — one-time setup

Every dashboard in this repo refreshes itself from VisiLean on a GitHub Actions worker:
the schedule starts a worker, the worker re-fetches every 5 minutes for ~5h40m, and it
publishes the moment VisiLean data (or the template) changes. **Nobody needs to build a
dashboard on a laptop.** The Refresh button on a report reloads into the newest
published build.

That only works if the project's API tokens are stored as repository secrets. VisiLean
scopes a token to one project:

> This API access token is not valid for the requested project.
> **Each token can only access the project it was generated for.**

So every project needs its own three tokens. **This is the only manual step, and it is
done once.**

---

## The whole setup: one secret

Put every project's tokens into a single repository secret called **`VL_TOKENS_JSON`**,
shaped like this:

```json
{
  "ntpc":     { "task": "…", "history": "…", "constraintLog": "…" },
  "sjvn":     { "task": "…", "history": "…", "constraintLog": "…" },
  "adani":    { "task": "…", "history": "…", "constraintLog": "…" },
  "adanis7":  { "task": "…", "history": "…", "constraintLog": "…" },
  "floating": { "task": "…", "history": "…", "constraintLog": "…" },

  "adopt_task":  "…",
  "adopt_hist":  "…",
  "adopt_notes": "…"
}
```

Include only the projects you have tokens for — anything missing is simply skipped, and
you can add it later by editing the one secret.

**Check the tokens before you paste them.** A wrong token fails quietly in a runner log,
so verify while the file is still in front of you:

```bash
python scripts/check_tokens_json.py tokens.json
```

It asks VisiLean about every feed and prints row counts or the exact error — never a
token. `HTTP 400 not valid for the requested project` means a real token filed under the
wrong key; `HTTP 500 API does not exist` means VisiLean doesn't recognise it at all
(mistyped, truncated or revoked).

**Setting it:**

- **Browser** — Settings → Secrets and variables → Actions → *New repository secret*,
  name `VL_TOKENS_JSON`, paste the JSON.
- **CLI** — `gh secret set VL_TOKENS_JSON --repo Vikas-visilean/ntpc-block8-mis-dashboard < tokens.json`
  (then delete `tokens.json`).

Where the tokens come from: VisiLean generates a PowerBI API token per project. The
three feeds are the task list, the history feed (this is what carries variance reasons)
and the constraints log.

### Individual secrets still work

If you would rather keep them separate, the per-project names below are still honoured
and take precedence over `VL_TOKENS_JSON`. NTPC already uses this form.

| Project | Secrets |
|---|---|
| NTPC | `VL_TOKEN_TASK`, `VL_TOKEN_HISTORY`, `VL_TOKEN_CONSTRAINTS` |
| SJVN | `VL_TOKEN_TASK_SJVN`, `VL_TOKEN_HISTORY_SJVN`, `VL_TOKEN_CONSTRAINTS_SJVN` |
| Adani S6a | `VL_TOKEN_TASK_ADANI`, `VL_TOKEN_HISTORY_ADANI`, `VL_TOKEN_CONSTRAINTS_ADANI` |
| Adani S7 | `VL_TOKEN_TASK_ADANIS7`, `VL_TOKEN_HISTORY_ADANIS7`, `VL_TOKEN_CONSTRAINTS_ADANIS7` |
| Floating | `VL_TOKEN_TASK_FLOATING`, `VL_TOKEN_HISTORY_FLOATING`, `VL_TOKEN_CONSTRAINTS_FLOATING` |
| Adoption | `VL_TOKEN_ADOPT_TASK`, `VL_TOKEN_ADOPT_HIST`, `VL_TOKEN_ADOPT_NOTES` |

---

## Then start them

```bash
gh workflow run refresh-v2.yml
gh workflow run refresh-sjvn.yml
gh workflow run refresh-adani.yml
gh workflow run refresh-adani-s7.yml
gh workflow run refresh-floating.yml
gh workflow run refresh-adoption.yml
```

Or from the Actions tab: pick the workflow → *Run workflow*. Add `-f once=true` (or tick
the box) to run a single cycle instead of starting a worker — handy for checking a token
without waiting.

From then on the schedule keeps each one alive. Nothing further is needed, ever.

---

## What happens when something is wrong

| Situation | What you see | Emails |
|---|---|---|
| Project has no credentials | Run succeeds, loop **skipped**, warning + job summary naming what's missing | none |
| Token rejected / VisiLean down | 6 failed cycles (~30 min) → run **fails** with the reason | yes, and it should |
| `VL_TOKENS_JSON` isn't valid JSON | Run **fails** immediately, quoting the parse error | yes |
| Nothing has changed in VisiLean | Run succeeds, "no data change" | none |

A project that was never set up is not a broken build, so it does not fail the run — it
would otherwise mail everyone on the repo every half hour for something no retry can
fix. The signal lives in two better places instead:

- **`sync-health.yml`** runs daily at 09:05 IST and fails once a day while anything is
  unhealthy, with the full table in the job summary.
- **The dashboards themselves.** Past 26 hours old, a page asks GitHub about its own
  workflow and shows a banner saying whether the sync is merely quiet (VisiLean has
  published no changes) or actually failing, linking the failing run. Below that
  threshold it shows nothing — a healthy dashboard stays uncluttered.

## Checking it worked

```bash
python scripts/check_sync.py
```

Every dashboard's build age and sync state, read from the published pages, so it reports
what a reader actually sees. Exits non-zero if anything is unhealthy. Or just run the
**Dashboard sync health** workflow from the Actions tab.

## Why a sync can go quiet legitimately

The workers publish only when something **changes** — data or template. A build stamped
three days ago on a project nobody has touched for three days is correct, not broken.
That is why the banner and the health check look at the workflow's own state rather than
guessing from age alone.

## Rotating a token

Edit `VL_TOKENS_JSON` (or the one per-project secret) and dispatch that workflow. A
rejected token shows up as HTTP 400 from VisiLean with the message quoted at the top of
this page, in the cycle log.
