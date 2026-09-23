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
study's resolved decisions; revisit if early variance is high). **0.1 is
`LLMQuerySpecGenerator`'s own constructor default and `s3geo.query()`
never overrides it** — confirmed from source, so N=20 calls at 0.1 needs
no explicit temperature handling in the notebook at all. Every run —
success or failure — is saved to `results/llm_runs/run_{i:02d}.json` with an
index in `manifest.csv`. A failure is data, not something to retry away.

**Smoke test first.** One call, print the generated operation sequence,
check that operations chain (each op consuming the previous op's output, not
a stale pre-distance vector), that every layer in a distance call was
individually reprojected, and that the degeneracy check does not fire.
Only then the full loop. The Vienna repo burned three full N=20 batches on
mistakes one call would have caught. `notebooks/03_llm_arm.ipynb`
deliberately stops after the smoke test for a second reason too: `result.output`'s
shape depends on which operation the LLM's plan ends on (`VectorOut`,
`ReportOut`, or a plain dict), and the property name it used for the
underserved flag/distance is unknowable ahead of a real call — the
extraction logic for "which mahalle are underserved" belongs in
`04_comparison_metric.ipynb`, written after seeing real output, not
guessed at here.

**Two more things confirmed by reading `orchestrator/planning/planner.py`
and `llm_spec_generator.py` directly, both load-bearing for how the raw
query in this notebook is worded:**

- `PlannerConfig.allow_implicit_entities` defaults to `True` — any input
  ref the LLM's plan uses that isn't another operation's output becomes
  `$inputs.<that ref>` and is looked up directly in the `layers=` dict, no
  schema/binding step in between. So the raw query names the two layers
  as exact quoted literals (`'hospitals'`, `'mahalle'`) matching the
  `layers=` dict keys — a plan that names them anything else fails at
  execution with an unresolvable reference, not a wrong answer.
- `llm_spec_generator.py` already has two hard, generation-time
  validators directly relevant to this study, both raising
  `LLMSpecGenerationError` (not just prompt guidance) before a bad plan
  ever executes: `_validate_distance_op_crs_symmetry` (catches a
  distance op whose two inputs were reprojected to different CRSs, or
  asymmetrically — this is Arm 2's own version of the Vienna Bug 5
  concern, generation-time rather than Arm 1's runtime
  `find_nearest_neighbors` hint check, though it only fires when it can
  trace *both* refs to a `crs_transform` output — a plan that never
  reprojects either layer at all isn't caught by this validator, so that
  failure mode is still worth watching for in real output) and
  `_validate_filter_points_in_polygon_usage` (blocks `filter_points_in_polygon`
  when the raw query asks "which zone" a point falls into — its
  docstring says this was added because prompt guidance alone didn't
  stop `gpt-4o-mini` from repeating exactly the mistake this repo's
  Arm 1 step 3 analysis independently flagged: using
  `filter_points_in_polygon` for a question that needs to know *which*
  polygon matched, not just whether one did. Independent corroboration,
  from a different source, of the `spatial_join` decision above).

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
| 3 | Rule-based arm | `notebooks/02_rule_based_arm.ipynb`, `results/rule_based_*.{csv,json}` — **DONE (2026-09-19)**, executed on the author's own machine; see "Findings" below | no | no |
| 4 | LLM arm (N=20) | `notebooks/03_llm_arm.ipynb`, `results/llm_runs/` — **at 0.4.2 (2026-09-19)**: `bugs/002` and `bugs/003` both confirmed fixed by a real re-run (the error changed shape exactly as their fixes predicted); a related third gap found, `bugs/004` (param *value* shapes still undocumented to the LLM). Not a blocker, same reasoning as `bugs/003`. Next: the N=20 batch. | **yes** | **yes** |
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
- `results/rule_based_underserved.csv` — one row per mahalle: name,
  boundary distance, centroid distance, facility count, `underserved` at
  each of the three thresholds. **No `ilçe` (district) column** — the
  fetched admin_level=8 relations don't carry a parent-district tag
  (verified against `data/raw/mahalle_boundaries.geojson`'s real
  properties: `osm_id`, `osm_type`, `admin_level`, `boundary`, `name`,
  plus incidental tags like `postal_code`/`wikidata`, no district field).
  Would need its own admin_level=6 fetch + spatial join to add.
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
- **✅ Resolved 2026-09-19 (by design, execution pending): `spatial_join`,
  not `filter_points_in_polygon`, for step 3.** Read both plugins' full
  source (`plugins/spatial_predicate.py`, `plugins/spatial_join.py`).
  `filter_points_in_polygon` takes the target polygons as one
  undifferentiated containment mask and reports only whether each point
  fell inside *any* of them — no polygon identity survives into the
  output, so it cannot produce a per-mahalle breakdown without one call
  per mahalle (964 calls). `spatial_join_features` attaches the matched
  mahalle (`_target_index`, and with `include_target_properties=True` the
  mahalle's own properties) to each hospital in a single call, which a
  `groupby` then turns into per-mahalle counts. Implemented in
  `notebooks/02_rule_based_arm.ipynb` §5 with the reasoning inline. Also
  found while reading `spatial_join.py`: unlike `find_nearest_neighbors`,
  `spatial_join_features` has no `target_crs` param and never validates
  `source_crs` against anything — it is a passive hint only, not a
  mismatch check. Not a bug (its docstring never claims otherwise), just a
  reason both layers must already be reprojected to the same CRS before
  calling it, not an operation this repo can lean on for CRS safety.
  Also confirmed by the real `spatial_join_features` run (§5, below): 1020
  hospitals in, 1020 matched, 0 unmatched — no coastline/boundary edge
  cases lost.
- **✅ Fully resolved 2026-09-19, now empirically confirmed (real run,
  `notebooks/02_rule_based_arm.ipynb` §3): the CRS-mismatch safety net on
  `find_nearest_neighbors` (Vienna's candidate Bug 5) is present and
  correct at 0.3.0, with a caveat.** `plugins/distance_calculator.py`'s
  `_raise_if_crs_mismatch()`
  (imported into `nearest_neighbor.py`) raises when *both* `source_crs`
  and `target_crs` are supplied and the two strings don't match — read the
  full function body, not just its docstring. **Caveat**: it is a
  normalized *string* comparison of the hints the caller passes, not an
  inspection of the actual coordinates — it catches mismatched labels, not
  mislabelled-but-consistent data (e.g. both layers claimed as
  `EPSG:32635` when one was never actually reprojected). So it's real
  protection against the specific mistake Vienna hit (chaining a call
  across a still-4326 layer with mismatched hints), but not a substitute
  for actually calling `crs_transform` and using its output.
  `notebooks/02_rule_based_arm.ipynb` §3's smoke test confirmed this on a
  real run: the mismatched-hint call raised the exact message quoted in
  source, the matching-hint call succeeded. Not a bug — matches the
  documented behavior exactly.

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

**Phase 3 (`notebooks/02_rule_based_arm.ipynb`), executed 2026-09-19, real
output — first run hit `bugs/001` (see there), revision 2 (with the
mitigation) ran clean end to end:**

- **`transform_vector_crs` vs. `geopandas.to_crs()` cross-check passed**:
  max bounds difference 0.9 m across all four corners of the mahalle
  layer — the framework's own reprojection op and phase 2's independent
  geopandas reprojection agree.
- **CRS-mismatch smoke test passed exactly as source predicted**: the
  deliberately-mismatched-hint call raised
  `find_nearest_neighbors: source_crs='EPSG:4326' and target_crs='EPSG:32635' do not match...`;
  the matching-hint call succeeded. Vienna's candidate Bug 5 does not
  reproduce at 0.3.0 — confirmed empirically, not just by reading source.
- **458 / 964 mahalle (47.5%) contain at least one facility**
  (`dist_boundary_m == 0.0`), matching exactly the 458 mahalle
  `spatial_join_features` found with `facility_count >= 1` — the two
  independent op calls (nearest-neighbor and spatial-join) agree on which
  mahalle have a facility inside them, a real internal-consistency check
  this notebook doesn't currently print explicitly but which held.
- **`spatial_join_features`: 1020 / 1020 hospitals matched to a mahalle, 0
  unmatched** — no coastline/boundary edge cases lost. 506 mahalle (52.5%)
  have zero facilities; among the 458 that have ≥1, mean 2.23, max 32
  (one dense central mahalle).
- **Underserved counts, all three thresholds** (centroid distance):
  1000 m → 325 (33.7%), 1500 m → 251 (26.0%), **2000 m → 207 (21.5%)**.
  `dist_centroid_m`: mean 1762 m, median 610 m, max 17,295 m (right-skewed
  — dense urban core near facilities, rural/exurban fringe far away).
- **207 underserved mahalle at 2000 m dissolve into 6 contiguous regions**
  (`dissolve_features(group_by=None)` + `.explode()`) — plausible for
  İstanbul's outer, less-built-up periphery; worth a map (phase 6) to
  confirm this visually rather than trusting the count alone.
- **`build_report`'s default `report_spec` truncates its own table to 50
  rows** even though `summary.total_count` correctly reports 207 — a real
  usability rough edge of the default real-estate-oriented spec (not a
  bug: `results/rule_based_underserved.csv`, written independently, has
  the full 964 rows and is the actual source of truth for the paper).
- **A real bug in this notebook's own code, not the framework, was found
  and fixed while reviewing this run**: revision 2's `centroid_outside_polygon`
  column was computed by matching `dist_df["name"]` against a hardcoded
  set of 9 names copied from this file's own Phase 2 findings above
  (`"Fatih"`, `"Kınalıada"`, ...) — but the real `name` field is
  `"Fatih Mahallesi"` etc. (includes the `Mahallesi` suffix), so the
  `.isin()` check silently matched nothing and every one of the 964 rows
  came back `False`. `01_data_and_problem.ipynb` must have stripped that
  suffix only for its own printed summary. Revision 3 recomputes this
  directly with `geometry.contains()` instead of trusting a copied name
  list — self-contained, not dependent on another notebook's stdout
  formatting. **Confirmed fixed by the revision-3 re-run**: recomputed
  directly with `geometry.contains()`, it found **exactly the same 9
  mahalle** `01_data_and_problem.ipynb` found independently (Mimar
  Kemalettin, Fatih, Orhanlı, Malkoçoğlu, Şamlar, Kınalıada, Maden,
  Esenkent, Karaburun) — two different computations (this notebook's
  `geometry.contains()` vs. phase 2's own check) agreeing is good evidence
  both are right. Every other number in this section was already
  unaffected by this bug (it only ever touched that one diagnostic
  column) and is unchanged in the revision-3 run.
- **Phase 3 is fully done.** Revision 3 of `notebooks/02_rule_based_arm.ipynb`
  ran clean end to end with no errors across all 11 code cells, all
  numbers above are from that real run, and `results/rule_based_underserved.csv`
  (964 rows, all columns including the corrected `centroid_outside_polygon`),
  `results/underserved_regions.geojson` (6 regions), and
  `results/rule_based_report.json` are written and current.

**Phase 4 (`notebooks/03_llm_arm.ipynb`), attempted 2026-09-19, real
output — the smoke test call (§4) itself crashed, not this repo's code:**

- `s3geo.query()`'s first call raised `ModuleNotFoundError: No module
  named 'rasterio'` before the LLM's plan ever ran — on a query that is
  100% vector (hospital points, mahalle polygons, nearest-facility
  distance) and never mentions raster/NDVI anywhere. Traced to real 0.3.0
  source, not guessed: `s3geo.query()` builds its plugin registry via
  `CapabilityRegistry.from_plugin_modules()` with no arguments, which
  defaults to `tolerant=False` and eagerly imports *all* 38 modules in
  `DEFAULT_SAFE_PLUGIN_MODULES` — including `plugins/ndvi_analysis.py`,
  which does an unconditional top-level `import rasterio` (an optional
  extra per `pyproject.toml`'s own `raster = ["rasterio"]`, not installed
  in this repo's `.venv`). Full writeup: `bugs/002-s3geo-query-crashes-without-raster-extras.md`.
- This is a hard framework bug, not a planning/prompt issue — the
  registry build happens before the plan's operations are even inspected,
  so no query, however well-formed, could avoid it in an environment
  without `rasterio` installed. `orchestrator/service.py`'s own
  `OrchestratorService` builds the exact same registry with
  `tolerant=True` for exactly this reason (documented in `pyproject.toml`
  itself); `s3geo.query()` — new in 0.3.0 — just didn't follow that
  established pattern, and doesn't expose a way for a caller to pass
  `tolerant=True` through.
- **Fixed upstream in `smart_spatial_system` 0.4.1** (2026-09-19),
  confirmed by cloning the tag and reading the diff directly, not taken
  on the fixer's word: `s3geo.query()` now defaults to `tolerant=True`
  (and exposes it as a real parameter), and `ndvi_analysis.py`'s
  `import rasterio` moved to a lazy import inside `process_ndvi()`. This
  repo's pin moved `smart-spatial-system==0.3.0` → `==0.4.1` (0.4.0 sits
  in between and is purely additive per its own `CHANGELOG.md`, so no
  intervening behavior change to worry about); `bugs/002`'s "Resolution"
  section has the full diff. The interim local mitigation
  (`pip install rasterio`) is superseded, not needed on a fresh install
  at the new pin. Waiting on the author to reinstall at `==0.4.1` and
  re-run the smoke test (§1-4) before Phase 4's N=20 batch runs.
- Symmetric to `bugs/001` in an interesting way for the paper's
  discussion: Arm 1 hit a crash Arm 2's code path avoids
  (`VectorOut.from_geopandas`'s datetime bug), and Arm 2 hit a crash
  Arm 1's code path avoids (this one — Arm 1 imports specific plugin
  functions directly and never calls `CapabilityRegistry.from_plugin_modules()`
  at all, so it was never exposed to this). Worth naming as evidence that
  "which arm breaks first" in this framework version has as much to do
  with which internal code path each arm happens to exercise as with the
  research question itself.

**Phase 4, re-attempted 2026-09-19 at `smart-spatial-system==0.4.1`, real
output — the `bugs/002` crash is gone; a different, real failure showed
up on the very first LLM call:**

- Smoke test result: `success: False`, `latency: 71.8s`,
  `error_stage: execution`, `error: "Node n4_filter_attribute failed:
  filter_features() got an unexpected keyword argument 'attribute'"`.
  The LLM's plan used a `filter_attribute` operation with an `attribute`
  parameter; the real parameter name (per `op_catalog.py`'s
  `param_map`) is `where` (a structured field/op/value condition, e.g.
  `{"field": "amenity", "op": "eq", "value": "hospital"}` or the shortcut
  `{"amenity": "hospital"}` — read directly from
  `plugins/spatial_query_filter.py`).
- Root-caused to real 0.4.1 source, not guessed — full writeup:
  `bugs/003-planner-silently-passes-through-unknown-op-params.md`. Two
  compounding gaps: (1) `PlannerConfig.strict_params` defaults to
  `False`, and `s3geo.query()` never overrides it, so an unrecognized
  parameter name is passed straight through to the plugin function
  instead of being rejected at planning time with a clear error — every
  test in the framework's own suite that builds a `PlannerConfig` passes
  `strict_params=True` explicitly, so this is the same "precedent exists
  elsewhere, `s3geo` just didn't follow it" shape as `bugs/002`. (2) the
  LLM prompt has an `_op_input_roles_reference()` that auto-generates the
  *input-role* section of the system prompt from `OP_CATALOG` — its own
  docstring explains it exists because a hand-written example
  (`distance_to`) once went undocumented and the LLM kept getting it
  wrong — but there is no equivalent auto-generated reference for
  *parameters*, so `filter_attribute`'s real param names are exactly as
  undocumented to the LLM today as `distance_to`'s inputs were before
  that fix was made.
- **Not treated as a Phase 4 blocker**, unlike `bugs/002`: this is one
  LLM plan choosing a wrong parameter name on one operation, not a crash
  on every call regardless of content, and `run_once()` already records
  it faithfully (`error_stage="execution"`) without crashing the
  notebook — exactly the kind of outcome the N=20 batch exists to
  characterize the rate of. No local mitigation is available (`s3geo.query()`
  doesn't expose `strict_params` the way it now exposes `tolerant`), so
  none was applied.
- **Fixed upstream in `smart_spatial_system` 0.4.2** (2026-09-19),
  confirmed by cloning the tag and reading the diff directly, not taken
  on the fixer's word: `s3geo.query()` now takes `strict_params: bool =
  True` and builds `DeterministicPlanner(PlannerConfig(strict_params=strict_params))`;
  `llm_spec_generator.py` gained `_op_param_reference()`, generated from
  `OP_CATALOG`'s `param_map` the same way `_op_input_roles_reference()`
  already was, wired into the system prompt. Both halves of the proposed
  fix, exactly as asked. This repo's pin moved `==0.4.1` → `==0.4.2`;
  `bugs/003`'s "Resolution" section has the full diff.
- **Re-run at 0.4.2, real output, confirms the `bugs/003` fix is
  genuinely working** — the error changed in kind, not just wording:
  `success: False`, `latency: 126.6s`, `error_stage: execution`,
  `error: "Node underserved_mahalle failed: where must be a dict/object
  or None."` The LLM's plan now uses the *correct* parameter name
  (`where`) for `filter_attribute` — proof `_op_param_reference()` is
  doing its job — but the *value* it supplied for `where` isn't a dict,
  which `plugins/spatial_query_filter.py::_eval_where` correctly
  rejects. New finding, `bugs/004-where-clause-shape-never-taught-to-llm.md`:
  `where`'s real shape (`{field, op, value}` conditions, `and`/`or`/`not`
  combinators, or a shortcut dict — all documented in `_eval_where`'s own
  docstring) is never surfaced to the LLM anywhere — `_op_param_reference()`
  lists only parameter *keys*, not *value shapes*, for any structured
  parameter. Same underlying class of gap as `bugs/003`, one level
  deeper. Not a blocker, same reasoning as `bugs/003` — this is exactly
  the kind of per-run outcome the N=20 batch exists to characterize; next
  step is running it.
