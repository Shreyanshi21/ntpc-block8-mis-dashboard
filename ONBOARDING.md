# KP dashboards — working on this repo

Everything here is one repo serving several live MIS dashboards, each fed straight from
the VisiLean PowerBI APIs by a GitHub Actions worker. **No dashboard should ever need to
be built on someone's laptop.** If you find yourself doing that, something is broken —
fix the sync rather than the symptom.

```
git clone https://github.com/Vikas-visilean/ntpc-block8-mis-dashboard
```

| Dashboard | Published at | Built by | Workflow |
|---|---|---|---|
| NTPC Bikaner Block 8 · 200 MW | `/v2/` and `/v3/` | `ntpc_dash_data_v2.py` + `build_ntpc_dash_v2/v3.py` | `refresh-v2.yml` |
| SJVN Khavda · 200 MW | `/sjvn/` | `dash_data.py sjvn` + `build_dash.py sjvn` | `refresh-sjvn.yml` |
| Adani Green S6a · 234 MW | `/adani/` | `… adani` | `refresh-adani.yml` |
| Adani Green S7 · 300 MW | `/adani-s7/` | `… adanis7` | `refresh-adani-s7.yml` |
| Floating Solar · Kadana Dam · 110 MW | `/floating/` | `… floating` | `refresh-floating.yml` |
| Adoption / Updates | `/adoption/`, `/updates/` | `adoption_data.py` + `build_adoption.py` | `refresh-adoption.yml` |

`/` (the root `index.html`) is the **locked v1.0 baseline**, tag
`v1.0-baseline-2026-08-17`. Don't edit it.

## Where things stand

Run this first — it reads the *published* pages, so it tells you what a reader sees:

```bash
python scripts/check_sync.py
```

As of 25-Sep-2026: **NTPC syncs; the other five do not**, because their VisiLean tokens
were never added as repository secrets. Their folders have only ever moved when someone
built locally and pushed. The fix is one secret — see **[SYNC-SETUP.md](SYNC-SETUP.md)**.

A VisiLean token only works for the project it was generated for ("Each token can only
access the project it was generated for"), which is why every project needs its own.
`VL_TOKENS_JSON` carries all of them in one secret.

## Things that will bite you

These are all real failures from this repo, not hypotheticals.

- **A template change must be made in BOTH `ntpc_dash_template_v2.html` and
  `_v3.html`.** Nothing enforces it; the builds don't compare them.
- **The workers publish on `.datahash` OR `.tplhash`.** Data-only gating meant template
  fixes never reached the published pages until the data happened to change.
- **The dashboards run inside VisiLean's Custom Analytics iframe**, where
  `navigator.clipboard` is blocked and `100vh` / `innerHeight` can be the whole
  scrollable page rather than the visible band. There are worked-around helpers for both
  — don't "simplify" them away.
- **Verify layout by measuring `getBoundingClientRect()` after a real scroll or hover,
  never by reading the stylesheet.** Two separate bugs passed a CSS read and failed in
  the browser.
- **Never commit tokens.** `scripts/vl_tokens.json` and `tokens*.json` are gitignored and
  the builds assert no `accessToken` reaches the HTML. Use
  `scripts/prepare_tokens.py` to hand tokens over — it verifies them and writes to a
  file instead of printing them.

## Working at the same time

The refresh worker commits to `v2/`, `v3/`, `sjvn/` … every few minutes, so you will hit
conflicts on build outputs constantly. They are never interesting — take your own build
and move on:

```bash
gh run cancel <the in_progress run>        # optional, stops it racing you
git checkout --theirs v2/index.html v2/meta.json v2/.datahash    # …and v3/, etc.
git add v2 v3 && git rebase --continue
git push origin master
gh workflow run refresh-v2.yml             # restart the worker you cancelled
```

**After any rebase or stash touching a published folder, grep for `<<<<<<<`.**
Conflict markers have been committed into `index.html` and `meta.json` before, which
serves a broken page.

Source changes go in `scripts/`. Don't hand-edit anything under `v2/`, `v3/`, `sjvn/`
etc. — those are build outputs and the worker will overwrite them.

## Reference

- **[SPEC.md](SPEC.md)** — section 10A is the authoritative description of the live
  system: data contract, weightage model, counting rules that reconcile with VisiLean,
  the post-baseline revision rule, the drill engine. Sections 1–9 describe the locked
  v1.0 and are historical.
- **[SYNC-SETUP.md](SYNC-SETUP.md)** — tokens, secrets, starting the workers.
- `scripts/check_sync.py` — is every dashboard being fed?
- `scripts/check_tokens_json.py` — do these tokens actually work?

## Open items

1. **Planned %** — VisiLean publishes 13.78%, the dashboard computes ~9%. No formula
   over the task endpoint reproduces theirs (~25 tried). Needs a definition from the
   VisiLean product team.
2. ~2,500 NTPC activities carry no weightage; ~105 have no baseline.
3. VisiLean's own "Critical Activity" flag is set on almost nothing, so that column and
   filter are near-empty. Criticality on the dashboard is float-based.
4. `scripts/vl_relations.json` is a static capture from the MSP — regenerate it whenever
   the schedule is re-imported, and watch `meta.logicCoverage`.
