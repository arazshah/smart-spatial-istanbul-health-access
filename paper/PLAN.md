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

**Verified against 0.3.0 source 2026-09-19** (`orchestrator/planning/op_catalog.py`
— every op below is a real, planner-reachable `op_name`; this replaces an
earlier draft of this plan that used a wrong operation for step 3):

1. `crs_transform` **each** layer individually, 4326 → 32635. Assert the CRS
   of every input immediately before any distance call.
2. `spatial_nearest` (mahalle → hospitals; `nearest_neighbor` is a
   confirmed alias, prefer `spatial_nearest` per the catalog's own note) for
   the polygon-boundary distance, and a second pass on mahalle **centroids**
   for the centroid distance. Both are reported; the centroid figure is the
   honest one for a health-access question, because polygon-to-point
   returns `0.0` for any mahalle that happens to contain a facility. Pass
   `source_crs`/`target_crs` explicitly — the catalog notes this lets
   `find_nearest_neighbors` raise on a CRS mismatch instead of silently
   returning a nonsense planar distance (Vienna's candidate Bug 5, if still
   unhandled at 0.3.0 — check `plugins/distance_calculator.py` and file a
   `bugs/` report if it isn't).
3. **Not `zonal_statistics`** — confirmed from source to be a
   raster-over-polygon operation (`calculate_zonal_statistics`, takes a
   `raster` input; "mean NDVI per district" is its own example use case).
   It cannot count point features. For the per-mahalle facility count, use
   `filter_points_in_polygon` (hospitals against mahalle, true point-in-
   polygon, not bbox) or `spatial_join` (predicate `within`/`contains`),
   then aggregate the per-mahalle count in the notebook. This is what
   separates "has one clinic just inside the border" from "is genuinely
   well served".
4. Threshold at 2000 m → boolean `underserved`.
5. Dissolve the underserved mahalle into contiguous underserved regions —
   **⚠️ `dissolve_features` (`plugins/dissolve_aggregator.py`) exists as a
   registered capability but is confirmed absent from `op_catalog.py`'s
   `OP_CATALOG`**, so it is not a planner-reachable `op_name` and
   `s3geo.query()` / `QuerySpec` can never produce it (only a param of
   `buffer`, `dissolve: true`, which merges overlapping *buffers*, not
   arbitrary polygons by attribute). This arm can still call
   `dissolve_aggregator.dissolve_features` **directly as a plugin
   function**, bypassing the planner — that's fine for a rule-based arm
   that is allowed to call plugins directly. But it means **Arm 2 cannot
   ask for this step at all**, structurally, however good its prompt is.
   Name this explicitly in the paper as a capability asymmetry between the
   two arms, not a fair comparison point — don't score the LLM arm down for
   never producing a dissolve it has no way to request. (Separately: this
   reachability gap matches a pattern `op_catalog.py`'s own docstring
   already names for several source-loading plugins — likely known to
   upstream already, worth a quick issue/PR upstream rather than a `bugs/`
   report, which is for behaviour that's wrong, not merely unexposed.)
6. `build_report` → the underserved table.

Repeat 4–6 at **1000 / 1500 / 2000 m** so the headline count is visibly a
function of the threshold rather than a fact.

### Arm 2 — LLM-planned

**Confirmed 2026-09-19: `s3geo.query(raw_query, *, layers, context=None,
system_hints=None)` is real and new in 0.3.0** (`s3geo/__init__.py`) — a
thin wrapper that wires up exactly `OpenAICompatibleLLMClient` +
`LLMQuerySpecGenerator` + `DeterministicPlanner` + `CapabilityRegistry` +
`RegistryCapabilityResolver` + `DagExecutor`, still directly usable
individually (which is what the Vienna repo, on 0.2.x, used before this
wrapper existed — use `s3geo.query()` here since it's now the documented
one-call path and returns `.goal`/`.operations`/`.output` directly, closer
to what phase 4/5's extraction needs). `layers` accepts GeoJSON dicts or
`GeoDataFrame`s directly. Note: there is a *second*, older/separate planning
path in this codebase (`orchestrator/llm_intent_planner.py`, used by
`application/services/llm_intent_adapter.py` for a different, REST-API-
facing flow, not `s3geo.query()`) — do not confuse the two; it has its own
op vocabulary (including, notably, `dissolve_features` — reachable there
but not through `s3geo.query()`, see Arm 1 step 5) and is out of scope here.

It gets a natural-language version of the same question and the same two
layers as input. The raw query string:

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
| 1 | Data acquisition | `data/raw/` — **DONE (2026-09-19)**: 1020 hospitals/clinics, 964 mahalle (see `data/README.md` "Fetched" for the two-fetch history) | **yes** (Overpass) | no |
| 2 | Data prep + problem definition | `notebooks/01_data_and_problem.ipynb`, `data/processed/` — **DONE (2026-09-19)**, executed on the author's own machine (real internet + installed pin) | no | no |
| 3 | Rule-based arm | `notebooks/02_rule_based_arm.ipynb`, `results/rule_based_*.{csv,json}` | no | no |
| 4 | LLM arm (N=20) | `notebooks/03_llm_arm.ipynb`, `results/llm_runs/` | **yes** | **yes** |
| 5 | Comparison metric | `notebooks/04_comparison_metric.ipynb`, `results/metrics.csv` | no | no |
| 6 | Map + figures + table | `notebooks/05_results.ipynb`, `results/figures/` | no | no |
| 7 | Paper | `paper/paper.md` | no | no |

Phases 2, 3, 5, 6, 7 run entirely offline once `data/processed/` exists,
using only the pinned package. Phases 1 and 4 are the only ones needing
network; 4 is the only one needing a key.

**Phase 0 exit note (2026-09-19):** the first session that built this
skeleton could reach neither `overpass-api.de` nor PyPI, and had no
credentials for `github.com/arazshah/smart_spatial_system`. A follow-up
session the same day, after the user widened network access, found:
Overpass reachable via the `overpass.kumi.systems` mirror (the primary
`overpass-api.de` host still resets the connection; the mirror is a shared
public instance and needs retries under load — see `data/README.md`
"Fetched"); `github.com/arazshah/smart_spatial_system` readable via plain
unauthenticated `git clone` (its GitHub *API* stays blocked, but the repo
itself is public over git); **PyPI still blocked** (`403`, both directly
and through the proxy) — `pip install` cannot resolve `smart-spatial-system`
or its build dependencies from here, so the package still is not actually
*installed* anywhere phases 2+ could use it, only read. **Git push to this
repo's own GitHub remote is also still blocked** ("not in this session's
authorized repository set") — a separate authorization from data network
access; phase 1's commits exist locally / as a delivered bundle, not
pushed. See `CLAUDE.md` → "Network and secrets" for what each of these
means for the phases ahead.

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

- **✅ Resolved 2026-09-19: mahalle is `admin_level=8`.** Probed against
  the live database — see `data/README.md` caveat 6. 964 mahalle fetched
  clean (0 skipped rings), so the "unit of analysis needs reconsidering"
  fallback (ilçe at level 6, ~39 units) did not end up needed.
- **✅ Resolved 2026-09-19: operation names verified against 0.3.0 source**
  (`orchestrator/planning/op_catalog.py`, read directly — see Arm 1/Arm 2
  above for the corrections this produced). `zonal_statistics` *was* the
  wrong operation, exactly as flagged; replaced with `filter_points_in_polygon`
  / `spatial_join` + notebook-side aggregation. `dissolve_features` is a
  real capability but not planner-reachable through `s3geo.query()` — a
  structural limit on Arm 2, not a bug to route around.
- **Which counting operation (`filter_points_in_polygon` vs. `spatial_join`)
  to use for step 3 is not yet decided** — both are real, catalog-registered
  operations that could work; pick one when writing `notebooks/02_rule_based_arm.ipynb`
  based on which gives a cleaner per-mahalle count, and say which and why in
  that notebook rather than leaving both as live options in the paper.
- **Whether Vienna's candidate CRS-mismatch bug (its Bug 5, upstream
  `plugins/distance_calculator.py`) is still present at 0.3.0 is unchecked.**
  The op catalog's own docstring for `_NEAREST_PARAM_MAP` claims passing
  `source_crs` *and* `target_crs` lets the op raise on mismatch instead of
  silently computing nonsense — read that claim in the docstring, not yet
  verified by triggering it. Verify with a deliberately-mismatched-CRS smoke
  test before trusting it in Arm 1, and file a `bugs/` report if it doesn't
  hold.

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

**Phase 2 (`notebooks/01_data_and_problem.ipynb`), executed 2026-09-19,
real output — every check in the notebook passed, nothing silently
skipped:**

- Loaded 1020 hospitals/clinics (421 hospital, 599 clinic — see
  `data/README.md` "Fetched" for why this differs from the phase-1 count)
  and 964 mahalle (955 Polygon, 9 MultiPolygon) from `data/raw/`. Both
  layers confirmed `EPSG:4326` on load.
- `amenity` values are exactly `{hospital, clinic}` — the unanchored regex
  (`data/README.md` caveat 4) did not pull in anything unexpected.
- **Zero null geometries, zero invalid mahalle rings, zero unnamed
  mahalle** — the data needed no repair beyond the `buffer(0)` safety net
  (which found nothing to fix).
- Both layers reprojected to `EPSG:32635` individually and asserted;
  `mahalle`'s bounds in the metric CRS (`x: 581527–748500`,
  `y: 4519307–4604146`) are sane for İstanbul in UTM 35N — the
  reprojection-sanity check this repo's CLAUDE.md asks for (after the
  Vienna sibling's CRS-mismatch history) passed on the first real run.
- **9 mahalle have a centroid that falls outside their own polygon**:
  Mimar Kemalettin, Fatih, Orhanlı, Malkoçoğlu, Şamlar, **Kınalıada**,
  Maden, Esenkent, Karaburun. Kınalıada is literally one of the Princes'
  Islands — an island mahalle with an irregular/multi-part coastline is
  exactly the shape where a polygon centroid can land outside the polygon
  (or in the sea next to it). Not a bug; name these nine explicitly if the
  paper's methodology uses centroid distance, since their centroid-based
  distance to the nearest hospital may not mean what it looks like it
  means.
- `data/processed/hospitals.geojson` (1020 features) and
  `data/processed/mahalle.geojson` (964 features) written in `EPSG:32635`,
  spot-checked: CRS block reads `EPSG::32635`, sample coordinates are
  6-digit easting/northing in metres (not degrees), `osm_id` retained on
  every feature for ODbL attribution.
