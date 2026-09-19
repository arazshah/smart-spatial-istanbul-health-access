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

**Phase 0 (repository skeleton) is done. Nothing has been run yet — there
are no results in this repo, and `data/raw/` is empty.**

Phase 1 (data acquisition) is blocked in the cloud session this repo was
scaffolded from: `overpass-api.de` is refused by the egress proxy (HTTP
403 on CONNECT), as are `nominatim.openstreetmap.org` and `pypi.org`.
Phases 2+ are additionally blocked on installing the pin — `0.3.0` is not
on PyPI, and `github.com/arazshah/smart_spatial_system` needs credentials
that session did not have. See "Network and secrets" for the three ways
around this. **Check `paper/PLAN.md`'s phase table and the actual contents
of `data/` and `results/` before assuming anything above is still current;
this file is not updated every session.**

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
