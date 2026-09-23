# CLAUDE.md

Guidance for Claude Code when working in this repository. Read this first,
every session — it is written so a fresh session needs no re-briefing.

## What this is

A spatial-accessibility case study asking **which Istanbul neighbourhoods
(*mahalle*) are underserved by hospitals and clinics** — where "underserved"
means the nearest hospital/clinic is farther than a walking/driving threshold
(2000 m by default). The same question is answered twice, by two pipelines:

1. a **rule-based** arm, where the operation plan is written explicitly
   (`nearest_neighbor` / `zonal_statistics`, threshold, dissolve), and
2. an **LLM-planned** arm, where the same question is handed to
   `s3geo.query()` / `LLMQuerySpecGenerator` as natural language and the
   planner decides the operations and parameters itself,

and the two are then compared. Method, metric and phases:
[`paper/PLAN.md`](paper/PLAN.md) and
[`paper/comparison_metric.md`](paper/comparison_metric.md).

It is a sibling of
[`smart-spatial-vienna-accessibility`](https://github.com/arazshah/smart-spatial-vienna-accessibility)
and deliberately reuses that repo's structure, comparison metric and
working style — a second city, a second domain (health access rather than
general amenity access), and a newer pin of the same framework.

## THE RULE: `smart_spatial_system` is a pinned dependency

**This repo consumes `smart_spatial_system` as a pinned dependency
(`smart-spatial-system==0.3.0`, see `requirements.txt`). Never edit its
source. If a bug is found in it, write a structured bug report in `bugs/`
instead, following the exact format used in `smart_spatial_system`'s own
`CHANGELOG.md` bug entries — root cause, reproduction, and a proposed
two-part fix (plugin layer + LLM-prompt layer).**

This is not a style preference, it is what makes the case study mean
anything. The experiment measures how a *released, pinned* version of the
framework behaves. A local patch to a vendored copy would make the numbers
unreproducible for anyone who installs the same pin, and would quietly
convert "the framework has this failure mode" into "our fork doesn't."

Concretely, in this repository:

- Never edit anything under the installed `smart_spatial_system` /
  `geochat_sdk` package tree, never vendor a copy of it here, and never
  monkey-patch its internals at runtime to make an experiment pass.
- Reading its source to understand behaviour is not only allowed, it is
  encouraged — most of the Vienna repo's real findings came from reading
  `plugins/*.py` and `orchestrator/planning/*.py` directly. Read freely,
  write never.
- A bug found while running an experiment here is a **finding**, and the
  deliverable for it is a report in `bugs/` (see `bugs/README.md` for the
  required format and file naming). Write the report, then **stop and
  surface it** — do not silently work around it and carry on.
- Prompt-side mitigations (extra `system_hints` in this repo's own
  notebooks) are allowed, but only as a *named, documented* safety net
  recorded in the bug report's "plugin layer + LLM-prompt layer" fix
  proposal — never as an undocumented fudge that hides the failure.
- Bumping the pin is a deliberate act: change `requirements.txt`, say in
  the commit message which upstream release it moves to and which bug
  report it closes, and re-run every phase whose outputs could change.

## Two more things this repository is NOT

- **Not a place for invented or synthetic data as final results.** The
  point is real, citable OpenStreetMap data (see `data/README.md`) and, for
  the LLM arm, a real model called for real, N times. Synthetic data is fine
  *only* for smoke-testing a code path before the real run, and must be
  labelled as such wherever it appears.
- **Not a place to quietly skip a blocked phase.** If the session's network
  policy or a missing key blocks a phase, say so explicitly and stop (see
  "Network and secrets" below). A phase that silently produces nothing is
  worse than one that fails loudly.

## Current state

**Phases 0–2 are done (2026-09-19).** `data/raw/` has 1020 hospitals/clinics
(421 hospital, 599 clinic) and 964 mahalle boundaries (955 Polygon, 9
MultiPolygon) — see `data/README.md` "Fetched" for why the hospital count
differs from an earlier same-day fetch (OSM is live, not a bug). Phase 2
(`notebooks/01_data_and_problem.ipynb`) ran clean end to end on the paper
author's own machine — every sanity check passed (0 null/invalid
geometries, 0 unnamed mahalle, CRS asserted after every reprojection) — and
wrote `data/processed/hospitals.geojson` (1020 features) and
`data/processed/mahalle.geojson` (964 features), both `EPSG:32635`. See
`paper/PLAN.md`'s "Findings" for the full real output, including the 9
mahalle whose centroid falls outside their own polygon (island/irregular
shapes — named there, not a bug).

**Phase 3 is done (2026-09-19).** `notebooks/02_rule_based_arm.ipynb`
revision 3 ran clean end to end on the author's own machine, no errors
across all 11 code cells — see `paper/PLAN.md` "Findings" for full numbers:
207 mahalle underserved at the 2000 m headline threshold (325 at 1000 m,
251 at 1500 m), dissolving into 6 contiguous regions; 1020/1020 hospitals
matched to a mahalle via `spatial_join_features`; the CRS-mismatch safety
net on `find_nearest_neighbors` (Vienna's candidate Bug 5) **confirmed
present and correct at 0.3.0 by an actual triggered run**, not just
source-reading. `results/rule_based_underserved.csv`,
`results/underserved_regions.geojson`, `results/rule_based_report.json`
are written and current.

Two bugs surfaced and got fixed along the way, worth remembering both kinds
exist:

1. **Upstream**: `bugs/001-vectorout-from-geopandas-timestamp-crash.md` —
   `VectorOut.from_geopandas()` crashing on OSM `check_date`/`start_date`
   columns. Documented, mitigated in `gdf_to_vectorout()` (never edited the
   pinned source), confirmed fixed by the clean revision-2 run. **Fixed
   upstream in `geochat-sdk` 1.0.1** (2026-09-19) — pin bumped, see below.
   `gdf_to_vectorout()`'s cast is now a harmless no-op, not required.
2. **Our own code, not upstream**: revision 2's `centroid_outside_polygon`
   column matched mahalle names against a set of 9 bare names
   (`"Fatih"`, `"Kınalıada"`, ...) copied from this file's own phase-2
   summary, but the real `name` field includes the `Mahallesi` suffix —
   the `.isin()` check silently returned `False` for all 964 rows instead
   of erroring. No `bugs/` report needed (this repo's rule is about
   `smart_spatial_system`, not our own code); fixed in revision 3 by
   recomputing the flag directly with `geometry.contains()`, which the
   revision-3 run confirmed finds **exactly the same 9 mahalle**
   `01_data_and_problem.ipynb` found independently — two different
   computations agreeing is real evidence both are right. Worth
   remembering: a silent-wrong-answer failure mode can just as easily be
   ours as upstream's.

**Phase 4 was blocked on `bugs/002`, now unblocked by an upstream fix
(2026-09-19).** `notebooks/03_llm_arm.ipynb` implements Arm 2
(`s3geo.query()`) and is deliberately structured to stop after a single
smoke-test call before committing to the N=20 batch — see the notebook's
own "## STOP" cell for why. The author ran §1-4 and the smoke test itself
crashed: `s3geo.query()`'s registry build
(`CapabilityRegistry.from_plugin_modules()`, called with no args →
`tolerant=False`) eagerly imports every plugin module including
`plugins/ndvi_analysis.py`, which did an unconditional `import rasterio`
— not installed in this repo's `.venv`, and irrelevant to this 100%
vector query. Full writeup:
`bugs/002-s3geo-query-crashes-without-raster-extras.md`. **Fixed upstream
in `smart_spatial_system` 0.4.1** (2026-09-19, confirmed by cloning the
tag and reading the diff, not taken on the fixer's word): `query()` now
defaults to `tolerant=True`, and `ndvi_analysis.py`'s `rasterio` import
moved to a lazy import inside `process_ndvi()`. **This repo's pin is
bumped**: `requirements.txt` now pins `smart-spatial-system==0.4.1` and
an explicit `geochat-sdk==1.0.1` (was `0.3.0` / implicit `>=1.0.0`) —
closes both `bugs/001` and `bugs/002`. The old `pip install rasterio`
local mitigation is superseded, not required on a fresh install at the
new pin. **Next step: the author reinstalls `requirements.txt` at the
new pin and re-runs the smoke test (§1-4)** before anything else in
Phase 4 proceeds — this has not been empirically confirmed to work yet,
only the upstream fix's source has been read. Verified against 0.3.0
source before writing any code (same discipline as Phase 3), which
surfaced three more facts worth remembering (still true at 0.4.1 — the
`CHANGELOG.md` diff for 0.4.0/0.4.1 touches none of this):

1. `LLMQuerySpecGenerator` already defaults `temperature=0.1` — this
   study's methodology needs no code change to get it.
2. `PlannerConfig.allow_implicit_entities=True` by default means any
   unresolved input ref in the LLM's plan becomes `$inputs.<ref>` — there is
   no formal schema/binding layer, so the raw query's layer names
   ("hospitals", "mahalle") must exactly match the `layers=` dict keys
   passed to `s3geo.query()` or the DAG won't wire correctly.
3. Two generation-time validators already exist in 0.3.0 and are directly
   relevant to this study's own Arm 1 design decisions:
   `_validate_distance_op_crs_symmetry` (Arm 2's own CRS-symmetry guard,
   parallel to Arm 1's `find_nearest_neighbors` runtime check) and
   `_validate_filter_points_in_polygon_usage` (blocks that op when the
   query needs zone identity — its docstring says this was added because
   `gpt-4o-mini` kept making that mistake even with prompt guidance,
   independent corroboration of this repo's own `spatial_join` choice in
   Arm 1). See `paper/PLAN.md` Arm 2 section for the docstring quotes.

`bugs/001` is now fixed upstream too (`geochat-sdk` 1.0.1, pin bumped
alongside `bugs/002`'s fix) — moot either way for Arm 2, since
`s3geo._to_geojson_dict()` never depended on `VectorOut.from_geopandas`
in the first place.

**Re-run at `0.4.1` (2026-09-19): `bugs/002` is gone, a new real bug
showed up on the first actual LLM call.** The smoke test reached the LLM
(71.8s), got a plan back, and failed during execution:
`filter_features() got an unexpected keyword argument 'attribute'`. Root
cause, verified against real 0.4.1 source: `PlannerConfig.strict_params`
defaults to `False` and `s3geo.query()` never overrides it, so an
operation parameter name (`attribute`) not in `filter_attribute`'s real
`param_map` (`where`, not `attribute`) gets passed straight through to
the plugin instead of being rejected at planning time — the exact same
"every test in the framework's own suite uses the safe setting, `s3geo`
alone doesn't" shape as `bugs/002`'s `tolerant` issue. Compounded by a
prompt gap: `_op_input_roles_reference()` auto-generates the *input-role*
part of the LLM's system prompt from `OP_CATALOG` specifically to avoid
undocumented operations (its own docstring names the `distance_to`
incident that motivated it) — but there's no equivalent for *parameters*,
so `filter_attribute`'s real param names were never taught to the model
at all. Full writeup: `bugs/003-planner-silently-passes-through-unknown-op-params.md`.
**Not a Phase 4 blocker** (unlike `bugs/002`): one LLM plan picked a
wrong parameter name on one op, `run_once()` already records this kind
of failure without crashing, and no local mitigation exists anyway
(`s3geo.query()` doesn't expose `strict_params` the way it now exposes
`tolerant`).

**Fixed upstream in `smart_spatial_system` 0.4.2 (2026-09-19)**,
confirmed by cloning the tag and reading the diff directly, not taken on
the fixer's word: `s3geo.query()` now defaults to `strict_params=True`
(also a real parameter now, mirroring `tolerant`), and
`llm_spec_generator.py` gained `_op_param_reference()` — generated from
`OP_CATALOG`'s `param_map` the same way `_op_input_roles_reference()`
already is — wired into the system prompt. Both halves of the two-part
fix this report asked for. **Pin bumped again**: `requirements.txt` now
pins `smart-spatial-system==0.4.2` (was `0.4.1`) — closes `bugs/003`
alongside the already-closed `bugs/001`/`bugs/002`. **Next step: the
author reinstalls at `0.4.2` and re-runs the smoke test (§1-4) once
more** — not yet empirically confirmed clean at this pin, only the
upstream fix's source has been read so far.

**Three environment facts, current as of 2026-09-19, likely to still matter
next session:**

1. Overpass works via the `overpass.kumi.systems` mirror, not the primary
   `overpass-api.de` host (connection reset at TLS). The mirror is a shared
   public instance — expect `504`/timeouts under load and retry with
   patience, not a smaller AOI. **A `200 OK` with a suspiciously small
   `elements` array is not proof of a real empty result** — this session hit
   exactly that once; see `data/README.md` "Fetched" before trusting a
   surprising count.
2. `github.com/arazshah/smart_spatial_system` is readable with a plain
   `git clone` (its GitHub *API* is still blocked — don't rely on `gh` or
   the API for it, clone it). **PyPI is still blocked** (`403`), so the
   package can be *read* from a git clone but not actually *installed* from
   here — `pip install` fails on build dependencies it can't fetch. Phases
   2+ still can't execute in this environment; the plan below is now
   verified against real 0.3.0 source, but nothing has run it yet.
3. **`git push` to this repo's own GitHub remote is blocked** — a separate
   authorization from data network access ("not in this session's
   authorized repository set"). Confirmed still blocked after the network
   grant that fixed #1/#2. Commits exist locally / delivered as a bundle;
   check whether `origin/main` actually has them before assuming a push
   succeeded.

**Check `paper/PLAN.md`'s phase table and the actual contents of `data/`
and `results/` before assuming anything above is still current; this file
is not updated every session.**

## Verified against 0.3.0 source (2026-09-19) — corrections to the plan

Read directly from `github.com/arazshah/smart_spatial_system` at tag
`v0.3.0` (`orchestrator/planning/op_catalog.py` is the ground truth for
every planner-reachable operation name):

- `crs_transform`, `spatial_nearest` (`nearest_neighbor` is a confirmed
  alias), `score_features`, `rank_features`, `build_report`,
  `filter_points_in_polygon`, `spatial_join` are all real.
- **`zonal_statistics` is wrong for this study** — confirmed
  raster-over-polygon (`calculate_zonal_statistics`, takes a `raster`
  input). Use `filter_points_in_polygon` or `spatial_join` to count
  hospitals per mahalle instead. See `paper/PLAN.md` Arm 1 step 3.
- **`dissolve_features` exists as a plugin capability but is not in
  `OP_CATALOG`**, so `s3geo.query()`/`QuerySpec` planning can never produce
  it — only Arm 1, calling the plugin directly, can dissolve. This is a
  structural asymmetry between the two arms, not a bug; name it in the
  paper. See `paper/PLAN.md` Arm 1 step 5.
- `s3geo.query(raw_query, *, layers, context=None, system_hints=None)` is
  real and new in 0.3.0 (`s3geo/__init__.py`) — use it for Arm 2 rather than
  wiring the five underlying classes by hand (that manual path, from the
  Vienna study's 0.2.x notes, still works but is no longer the documented
  entry point). Don't confuse it with `orchestrator/llm_intent_planner.py`,
  an older/separate planning path used by a different REST-API-facing flow
  — out of scope here, and the one place `dissolve_features` actually is
  reachable, for context.
- Not yet checked: whether Vienna's candidate CRS-mismatch bug still exists
  at 0.3.0. The nearest-neighbour op's own param docstring claims passing
  `source_crs`+`target_crs` makes it raise instead of silently computing
  nonsense — verify this by deliberately triggering it before trusting it.

## Layout

```
data/README.md        the exact Overpass queries, the AOI, and licensing
data/raw/             Overpass output (gitignored - regenerate, don't commit)
data/processed/       small derived GeoJSON actually fed to the system
notebooks/01_..05_    one numbered notebook per phase, run in order
scripts/              data download + Overpass->GeoJSON conversion helpers
results/              rankings, per-run LLM specs, metrics, figures
paper/PLAN.md         research question, phases, methodology, estimate
paper/comparison_metric.md  the three-layer metric - read before comparing
paper/paper.md        the deliverable write-up
bugs/                 structured upstream bug reports (see bugs/README.md)
claude-notes/         session notes that don't belong in the paper
```

## Analysis conventions

- **CRS.** Source data is EPSG:4326. Every metric operation (distance,
  threshold, area) happens in **EPSG:32635** (WGS 84 / UTM zone 35N),
  which covers Istanbul either side of the Bosphorus. Reproject *every*
  layer that takes part in a distance call, individually — the Vienna repo
  lost three full N=20 batches to plans that reprojected one layer and
  silently compared it against another still in degrees (its upstream
  candidate Bug 5). Assert the CRS of every input immediately before a
  distance op, in both arms.
- **Threshold.** 2000 m nearest-facility distance is the default
  "underserved" cutoff; it is a parameter, not a finding. Report the
  underserved set at 1000 / 1500 / 2000 m so the headline number is
  visibly sensitive to it.
- **Distance semantics.** `nearest_neighbor` is polygon-to-point: a mahalle
  containing a hospital gets distance `0.0`. That is correct GIS behaviour,
  not a bug, but it means dense mahalles tie at the top. Report both the
  polygon-boundary distance and a **centroid-based** distance — for a
  health-access question the centroid figure is the more honest one, and
  the tie structure is itself worth a paragraph (Vienna tied 21 of 23
  districts this way).
- **The LLM arm chooses its own parameters.** The natural-language query
  handed to the LLM arm must *not* contain the 2000 m threshold or the CRS
  — picking those is exactly what is being measured. Keep the raw query
  string identical across all N runs, in one place, and commit it.
- **A degenerate result is a result.** Run a `ranking_is_degenerate()`-style
  check (all scores equal, all zero, or every mahalle flagged) automatically
  in both arms and record it as its own column, separate from
  "execution succeeded". Vienna hid three failed batches behind a clean
  100% success rate before adding this.
- **Smoke-test before any N-run batch.** One LLM call, printed plan, eyes
  on the operation sequence and the per-layer CRS, *then* the full loop.
  Vienna spent three full N=20 batches (~60 API calls) on mistakes a
  single-call smoke test would have caught.

## Network and secrets

- Data download (Overpass/OSM) and the LLM arm both need real internet.
  Test before assuming:
  `curl -sS -o /dev/null -w '%{http_code}\n' --max-time 8 https://overpass-api.de/api/status`
  If it is blocked, say so explicitly rather than silently skipping — the
  user needs to know to run that phase locally or open a session with a
  wider egress policy. Do not route around an egress denial.
- Three known ways to get `data/raw/` populated when the sandbox is
  blocked: (a) run the phase on a machine with normal internet;
  (b) run the queries from inside a real desktop browser via the Chrome
  integration, which uses the user's own network rather than the sandbox's
  (this is how the Vienna repo's data was fetched); (c) paste/attach the
  raw Overpass JSON into the session and convert it with
  `scripts/overpass_to_geojson.py`. All three end at the same converter,
  so the downstream phases don't care which was used.
- Installing the pin needs either PyPI (if `0.3.0` was published there) or
  read access to `github.com/arazshah/smart_spatial_system` — see
  `requirements.txt`.
- The LLM key goes in `.env` (copy `.env.example`), never hardcoded, never
  committed. Only the LLM arm needs it — don't ask for it, or fail earlier
  phases for its absence.

## Working style for this repo

- Notebooks are numbered and run in order; each phase's notebook is that
  phase's deliverable, not a scratch file — keep them readable enough for
  an advisor to open.
- Commit every output a later phase depends on (`data/processed/`,
  `results/llm_runs/`, `results/metrics.csv`) so nobody has to re-run an
  expensive step — especially the LLM arm — to reproduce a later one.
- When a phase finishes, update "Current state" above **in the same
  commit**. This file is how the next session picks up without a briefing.
- Keep `paper/PLAN.md`'s "Open decisions" current: resolve items there when
  they're decided rather than leaving them stale.
