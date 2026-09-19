# Experiment and paper plan

Working title: *Rule-Based versus LLM-Planned Spatial Query Pipelines for
Health-Facility Accessibility: An İstanbul Mahalle Case Study*

## Research question

**Which İstanbul mahalle (neighbourhoods) are underserved by hospitals and
clinics — i.e. whose nearest facility is farther than a reasonable
walking/driving threshold (2000 m)?**

And, running alongside it as the methodological question this repo shares
with its Vienna sibling: **given that same question in natural language,
does an LLM-backed query planner build the same pipeline, choose comparable
parameters, and identify the same underserved mahalle as an explicitly
written rule-based plan?** Where the two disagree, the disagreement is the
finding — the substantive map and the methodological result are both
deliverables, not one in service of the other.

## Units of analysis

İstanbul Province's *mahalle* (`admin_level=10` in OSM), expected ~950–1000.
Chosen because they are the finest official administrative unit for which
boundaries are citable and complete, they are the unit Turkish municipal
health planning actually uses, and they need no invented data. See
`data/README.md` for the AOI and the exact queries.

## Layers

| Layer | Geometry | Role |
|---|---|---|
| `mahalle` | Polygon / MultiPolygon | the sites being scored |
| `hospitals` | Point (nodes + way centroids) | the facilities distance is measured to |

`amenity` (`hospital` vs. `clinic`) is carried through as a property so the
whole analysis can be re-run hospital-only without re-fetching.

## Methodology

Both arms answer the same question, over the same two layers, in
EPSG:32635, and are then compared. Neither arm is allowed to see the other's
plan.

### Arm 1 — rule-based (deterministic by construction)

An explicit operation plan, written out rather than generated:

1. `crs_transform` **each** layer individually, 4326 → 32635. Assert the CRS
   of every input immediately before any distance call.
2. `nearest_neighbor` (mahalle → hospitals) for the polygon-boundary
   distance, and a second pass on mahalle **centroids** for the
   centroid distance. Both are reported; the centroid figure is the honest
   one for a health-access question, because polygon-to-point returns `0.0`
   for any mahalle that happens to contain a facility.
3. `zonal_statistics` for the per-mahalle facility count (how many
   facilities fall inside, and within the threshold buffer) — this is what
   separates "has one clinic just inside the border" from "is genuinely well
   served".
4. Threshold at 2000 m → boolean `underserved`.
5. Dissolve the underserved mahalle into contiguous underserved regions, so
   the result is a map of *areas*, not a list of isolated polygons.
6. `build_report` → the underserved table.

Repeat 4–6 at **1000 / 1500 / 2000 m** so the headline count is visibly a
function of the threshold rather than a fact.

### Arm 2 — LLM-planned

`s3geo.query()` (or `LLMQuerySpecGenerator` directly, which is what the
Vienna repo used and what makes the generated `QuerySpec` inspectable) gets
a natural-language version of the same question and the same two layers as
input. The raw query string:

- states the question, the two layers and the city;
- **deliberately omits** the 2000 m threshold, the CRS, the centroid-vs-
  boundary choice and the operation list — choosing those is exactly what is
  being measured;
- is identical across all N runs, lives in exactly one place in the
  notebook, and is committed.

Run N = 20 times at temperature 0.1 (both carried over from the Vienna
study's resolved decisions; revisit if early variance is high). Every run —
success or failure — is saved to `results/llm_runs/run_{i:02d}.json` with an
index in `manifest.csv`. A failure is data, not something to retry away.

**Smoke test first.** One call, print the generated operation sequence,
check that operations chain (each op consuming the previous op's output, not
a stale pre-distance vector), that every layer in a distance call was
individually reprojected, and that the degeneracy check does not fire.
Only then the full loop. The Vienna repo burned three full N=20 batches on
mistakes one call would have caught.

### Comparison

Per `paper/comparison_metric.md`: Plan Agreement Rate (structural),
parametric agreement (the thresholds/weights the LLM invents), and outcome
agreement — here measured both as rank stability and, because the primary
output is a *set*, as **Jaccard overlap of the underserved-mahalle sets**
between runs and against the rule-based reference.

## Data sources

OpenStreetMap via the Overpass API; exact queries, AOI, CRS justification,
caveats and licensing in [`data/README.md`](../data/README.md).

## Phases

| # | Phase | Output | Network? | LLM key? |
|---|---|---|---|---|
| 0 | Repository skeleton | this repo — **DONE (2026-09-19)** | no | no |
| 1 | Data acquisition | `data/raw/` | **yes** (Overpass) | no |
| 2 | Data prep + problem definition | `notebooks/01_data_and_problem.ipynb`, `data/processed/` | no | no |
| 3 | Rule-based arm | `notebooks/02_rule_based_arm.ipynb`, `results/rule_based_*.{csv,json}` | no | no |
| 4 | LLM arm (N=20) | `notebooks/03_llm_arm.ipynb`, `results/llm_runs/` | **yes** | **yes** |
| 5 | Comparison metric | `notebooks/04_comparison_metric.ipynb`, `results/metrics.csv` | no | no |
| 6 | Map + figures + table | `notebooks/05_results.ipynb`, `results/figures/` | no | no |
| 7 | Paper | `paper/paper.md` | no | no |

Phases 2, 3, 5, 6, 7 run entirely offline once `data/processed/` exists,
using only the pinned package. Phases 1 and 4 are the only ones needing
network; 4 is the only one needing a key.

**Phase 0 exit note (2026-09-19):** the session that built this skeleton
could reach neither `overpass-api.de` (HTTP 403 from the egress proxy) nor
PyPI, and had no credentials for `github.com/arazshah/smart_spatial_system`,
so phase 1 onward is blocked there. Nothing was faked to paper over it and
no result files exist. See `CLAUDE.md` → "Network and secrets" for the three
ways to unblock phase 1, and `requirements.txt` for the pin's install
source.

## Expected outputs

- `data/processed/mahalle.geojson`, `data/processed/hospitals.geojson`
- `results/rule_based_underserved.csv` — one row per mahalle: name, ilçe,
  boundary distance, centroid distance, facility count within threshold,
  `underserved` at each of the three thresholds
- `results/underserved_regions.geojson` — the dissolved underserved areas
- `results/llm_runs/` — N QuerySpecs + N underserved sets + `manifest.csv`
- `results/metrics.csv` — PAR, parametric spread, Jaccard/rank stability,
  success rate, latency
- `results/figures/fig1_underserved_map.png` — the choropleth/dissolve map
- `results/figures/fig2_threshold_sensitivity.png` — underserved count vs.
  threshold
- `results/figures/fig3_arm_disagreement.png` — where the two arms differ
- `paper/paper.md` — map, underserved table, methodology, findings
- `bugs/*.md` — if and only if something upstream misbehaves

## Effort estimate

| Phase | Estimate | Dominated by |
|---|---|---|
| 0 | 0.5 d — **done** | — |
| 1 | 0.5 d | Overpass round-trips and retries; ~1000 relations with full geometry is a slow query |
| 2 | 1 d | ring assembly / invalid-geometry cleanup on ~1000 mahalle, and confirming the counts in `data/README.md`'s caveat list |
| 3 | 1 d | getting the two distance variants and `zonal_statistics` wired correctly; CRS assertions |
| 4 | 1–3 d | **the wide one.** ~20 API calls is an hour; the Vienna sibling needed six rounds of diagnosis before a batch came back non-degenerate. Budget for at least one upstream bug report. |
| 5 | 0.5 d | mostly mechanical once `results/llm_runs/` is populated |
| 6 | 1 d | cartography for ~1000 polygons is fiddly — legible at A4 is the constraint |
| 7 | 2 d | writing |
| | **~8–10 working days** | assuming phase 4 costs one bug-report cycle, not three |

## Open decisions

- **N and temperature.** N=20 at 0.1, inherited from the Vienna study.
  Revisit once early variance is visible — a set-valued output may be more
  or less stable than a ranking, which is an open empirical question.
- **Hospital-only vs. hospital+clinic as the headline definition.** Default
  is both, with the hospital-only re-run reported alongside. Decide which
  leads once the counts are in.
- **Population weighting.** An underserved mahalle of 200 people and one of
  40,000 are not the same finding. TÜİK publishes mahalle-level population;
  whether to bring it in (and whether that makes this a different paper)
  is undecided. The OSM-only pipeline stands on its own either way.
- **Road-network distance vs. Euclidean.** Everything above is straight-line
  distance. In a city cut by the Bosphorus and steep topography that is a
  real limitation, and naming it is mandatory; upgrading to network distance
  is a possible follow-up, not in scope here.
- Target venue and its format, once the advisor weighs in.

## Findings to fold into the paper's discussion/limitations

*(empty — nothing has been run. Add findings here as phases complete, with
the evidence that supports them, the way the Vienna repo's PLAN.md does.)*
