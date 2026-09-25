# Dashboard sync — one-time setup

Every dashboard in this repo refreshes itself from VisiLean on a GitHub Actions worker:
the schedule starts a worker, the worker re-fetches every 5 minutes for ~5h40m, and it
publishes the moment VisiLean data (or the template) changes. **Nobody needs to build a
dashboard on a laptop.** The Refresh button on a report reloads into the newest
published build.

That only works if the project's API token is stored as a repository secret. VisiLean
scopes a token to one project:

> This API access token is not valid for the requested project.
> **Each token can only access the project it was generated for.**

One token serves every feed that project's dashboard reads (tasks, history,
constraints). So every project needs exactly **one** token. **This is the only manual
step, and it is done once.**

---

## The whole setup: one secret per project

| Project | Repository secret | Feeds |
|---|---|---|
| NTPC Bikaner Block 8 | `VL_TOKEN_NTPC` | `/v2/`, `/v3/`, and the Adoption + Updates reports |
| SJVN Khavda | `VL_TOKEN_SJVN` | `/sjvn/` |
| Adani S6a | `VL_TOKEN_ADANI` | `/adani/` |
| Adani S7 | `VL_TOKEN_ADANIS7` | `/adani-s7/` |
| Floating Solar | `VL_TOKEN_FLOATING` | `/floating/` |

Each secret holds the raw token and nothing else. The Adoption tracker and Updates
report read the NTPC project, so they use `VL_TOKEN_NTPC`; there is no adoption token.

### The fallback: `VL_TOKENS_JSON`

There is also a single secret **`VL_TOKENS_JSON`** that can carry every project's token
in one flat map:

```json
{
  "ntpc":     "…",
  "sjvn":     "…",
  "adani":    "…",
  "adanis7":  "…",
  "floating": "…"
}
```

Include only the projects you have tokens for. A worker looks for `VL_TOKEN_<KEY>`
first and the JSON entry second, and **if VisiLean rejects the per-project secret it
switches to the JSON entry** and puts a warning on the run naming the secret to fix.
So keeping both set is a safety net for a bad rotation, not a duplication. Either one
alone is enough for a project to sync.

**Got the tokens from someone else?** One command normalises whatever shape they arrive
in — a flat map, Power BI feed URLs, one project's token with `--project`, or even the
old per-feed file — verifies every one against VisiLean, and writes the file to copy
from:

```bash
python scripts/prepare_tokens.py tokens-from-colleague.json
# add --project sjvn if the file holds one project's token without saying which
```

Tokens are never printed to the terminal; the output goes to `tokens.secret.json`, which
you open, copy, and then delete. If one project turns up with two different tokens it
writes nothing and says so, because only one can be current.

**Check the tokens before you paste them.** A wrong token fails quietly in a runner log,
so verify while the file is still in front of you:

```bash
python scripts/check_tokens_json.py tokens.json
```

It tries each project's one token against all three feeds and prints row counts or the
exact error — never a token. `HTTP 400 not valid for the requested project` means a
real token filed under the wrong key; `HTTP 500 API does not exist` means VisiLean
doesn't recognise it at all (mistyped, truncated or revoked). A file in the old nested
`{"sjvn": {"task": …}}` shape is refused with an explanation.

**Setting it:**

- **Browser** — Settings → Secrets and variables → Actions → *New repository secret*,
  name `VL_TOKEN_SJVN`, paste the token. Or name `VL_TOKENS_JSON`, paste the JSON.
- **CLI** — `gh secret set VL_TOKEN_SJVN --repo Vikas-visilean/ntpc-block8-mis-dashboard < sjvn-token.txt`,
  or `gh secret set VL_TOKENS_JSON --repo Vikas-visilean/ntpc-block8-mis-dashboard < tokens.json`
  (then delete the file).

Where the tokens come from: VisiLean generates one PowerBI API token per project.

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
| Project has no token | Run succeeds, loop **skipped**, warning + job summary naming the secret to set | none |
| `VL_TOKEN_<KEY>` rejected, JSON entry works | Run succeeds, a **warning** annotation names the broken secret | none |
| Every token rejected | Cycle fails at once; 6 in a row (~30 min) → run **fails** naming the rejected secrets | yes, and it should |
| VisiLean down | Cycles retry and skip; 6 in a row → run **fails** with the reason | yes |
| `VL_TOKENS_JSON` isn't valid JSON, or is in the old per-feed shape | Run **fails** immediately, quoting the problem | yes |
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

Replace that project's one secret — `VL_TOKEN_<KEY>`, or its entry in `VL_TOKENS_JSON`
— and dispatch that workflow. If both are set, update both; until you do, the worker
will reject the stale one and carry on with the other, with a warning on every run.

## Migrating from the three-token scheme

Before 25-Sep-2026 every project needed three tokens (`VL_TOKEN_TASK`,
`VL_TOKEN_HISTORY`, `VL_TOKEN_CONSTRAINTS`, with `_SJVN` etc. suffixes, and
`VL_TOKEN_ADOPT_*` for adoption) and `VL_TOKENS_JSON` was nested per feed. Nothing reads
any of those names any more. To move over:

1. Get the project's one token from VisiLean and verify it with
   `python scripts/check_tokens_json.py`.
2. Add `VL_TOKEN_NTPC` (and the others). If a `VL_TOKENS_JSON` secret already exists in
   the nested shape, **replace** its contents with the flat map above — do not append to
   it, or every workflow will fail preflight until it is fixed.
3. `gh workflow run refresh-v2.yml -f once=true` and
   `gh workflow run refresh-adoption.yml -f once=true`; the preflight step logs
   "credentials from VL_TOKEN_NTPC".
4. Delete the old secrets: `gh secret delete VL_TOKEN_TASK`, `VL_TOKEN_HISTORY`,
   `VL_TOKEN_CONSTRAINTS`, any suffixed variants, and `VL_TOKEN_ADOPT_TASK` /
   `_HIST` / `_NOTES`.
