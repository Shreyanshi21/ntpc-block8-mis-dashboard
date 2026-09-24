# Dashboard sync — one-time setup

Every dashboard in this repo refreshes itself from VisiLean on a GitHub Actions worker:
the schedule starts a worker, the worker re-fetches every 5 minutes for ~5h40m, and it
publishes the moment VisiLean data (or the template) changes. **Nobody needs to build a
dashboard on a laptop.** The Refresh button on each report reloads into the newest
published build.

That only works if the project's API tokens are stored as repository secrets. VisiLean
scopes a token to one project:

> This API access token is not valid for the requested project.
> **Each token can only access the project it was generated for.**

So every project needs its own three tokens. This is a one-time action per project.

## Status

| Dashboard | Path | Workflow | Secrets |
|---|---|---|---|
| NTPC Bikaner Block 8 · 200 MW | `/v2/`, `/v3/` | `refresh-v2.yml` | ✅ configured |
| SJVN Khavda · 200 MW | `/sjvn/` | `refresh-sjvn.yml` | ❌ missing |
| Adani Green S6a · 234 MW | `/adani/` | `refresh-adani.yml` | ❌ missing |
| Adani Green S7 · 300 MW | `/adani-s7/` | `refresh-adani-s7.yml` | ❌ missing |
| Floating Solar, Kadana Dam · 110 MW | `/floating/` | `refresh-floating.yml` | ❌ missing |
| Adoption tracker | `/adoption/`, `/updates/` | `refresh-adoption.yml` | ❌ missing |

A workflow whose secrets are missing **fails loudly** — a red run named
"… sync is not configured", listing the exact secrets. It no longer loops quietly in
green, which is how four dashboards went stale for up to 15 days unnoticed.

## Adding the secrets

Get each project's three PowerBI tokens from VisiLean (the token is generated per
project), then run these. Each command prompts for the value, so the token is never
typed into a chat, a file, or a commit:

```bash
# SJVN Khavda
gh secret set VL_TOKEN_TASK_SJVN        --repo Vikas-visilean/ntpc-block8-mis-dashboard
gh secret set VL_TOKEN_HISTORY_SJVN     --repo Vikas-visilean/ntpc-block8-mis-dashboard
gh secret set VL_TOKEN_CONSTRAINTS_SJVN --repo Vikas-visilean/ntpc-block8-mis-dashboard

# Adani Green S6a
gh secret set VL_TOKEN_TASK_ADANI        --repo Vikas-visilean/ntpc-block8-mis-dashboard
gh secret set VL_TOKEN_HISTORY_ADANI     --repo Vikas-visilean/ntpc-block8-mis-dashboard
gh secret set VL_TOKEN_CONSTRAINTS_ADANI --repo Vikas-visilean/ntpc-block8-mis-dashboard

# Adani Green S7
gh secret set VL_TOKEN_TASK_ADANIS7        --repo Vikas-visilean/ntpc-block8-mis-dashboard
gh secret set VL_TOKEN_HISTORY_ADANIS7     --repo Vikas-visilean/ntpc-block8-mis-dashboard
gh secret set VL_TOKEN_CONSTRAINTS_ADANIS7 --repo Vikas-visilean/ntpc-block8-mis-dashboard

# Floating Solar, Kadana Dam
gh secret set VL_TOKEN_TASK_FLOATING        --repo Vikas-visilean/ntpc-block8-mis-dashboard
gh secret set VL_TOKEN_HISTORY_FLOATING     --repo Vikas-visilean/ntpc-block8-mis-dashboard
gh secret set VL_TOKEN_CONSTRAINTS_FLOATING --repo Vikas-visilean/ntpc-block8-mis-dashboard

# Adoption tracker
gh secret set VL_TOKEN_ADOPT_TASK  --repo Vikas-visilean/ntpc-block8-mis-dashboard
gh secret set VL_TOKEN_ADOPT_HIST  --repo Vikas-visilean/ntpc-block8-mis-dashboard
gh secret set VL_TOKEN_ADOPT_NOTES --repo Vikas-visilean/ntpc-block8-mis-dashboard
```

No `gh` CLI? Same thing in the browser:
**Settings → Secrets and variables → Actions → New repository secret**, using the names above.

## Then start them

```bash
gh workflow run refresh-sjvn.yml
gh workflow run refresh-adani.yml
gh workflow run refresh-adani-s7.yml
gh workflow run refresh-floating.yml
gh workflow run refresh-adoption.yml
```

Add `-f once=true` to run a single cycle instead of starting a worker — useful for
checking a token without waiting.

From then on the schedule keeps each one alive and no further action is needed.

## Checking it worked

```bash
# every dashboard's build age, straight from the published pages
python scripts/check_sync.py
```

Or look at the dashboards themselves: past 26 hours old, a page asks GitHub about its
own workflow and shows a banner saying whether the sync is merely quiet (VisiLean has
published no changes) or actually failing, with a link to the failing run. Under that
threshold it shows nothing — a healthy dashboard stays uncluttered.

## Why a sync can go quiet legitimately

The workers publish only when something **changes** — data or template. A build stamped
three days ago on a project nobody has touched for three days is correct, not broken.
That is why the banner checks the workflow's own state rather than guessing from age.

## If a token is revoked or expires

The run goes red by itself: six failed cycles in a row (~30 minutes) fail the job with
"… sync is failing". VisiLean answers a bad token with HTTP 400 and the message quoted
at the top, which appears in the cycle log. Re-set that project's three secrets and
dispatch the workflow again.
