# 004 — `filter_attribute`'s `where` value shape is never taught to the LLM

- **Status:** open
- **Found:** 2026-09-19, phase 4 (`notebooks/03_llm_arm.ipynb`, §4, the
  smoke test — first real LLM call after `bugs/003` was fixed and the pin
  moved to 0.4.2)
- **Affects:** smart-spatial-system 0.4.2
  (`orchestrator/planning/llm_spec_generator.py::_op_param_reference`/`_domain_guidance`,
  `plugins/spatial_query_filter.py::_eval_where`)
- **Severity:** hard failure with a clear underlying message (the plugin's
  own validation error is good; the problem is the LLM had no way to
  produce a valid value in the first place, and the failure still only
  surfaces after a full LLM round trip)

## Symptom

With `bugs/003` fixed (pin at 0.4.2, confirmed: this run's error is
different in kind from `bugs/003`'s, proving the parameter-*name* fix is
working), the smoke test still failed at execution, this time one layer
deeper:

```
success: False  latency: 126.6s
FAILED at stage=execution: Node underserved_mahalle failed: where must be a dict/object or None.
```

The LLM's plan now uses the correct parameter *name* (`where`) for its
`filter_attribute` operation — `bugs/003`'s fix is doing its job — but
whatever *value* it supplied for `where` isn't a dict, and
`plugins/spatial_query_filter.py::_eval_where` rejects anything that
isn't a `dict` or `None`. The exact malformed value isn't captured
(`run_once()` in `notebooks/03_llm_arm.ipynb` only stores `operations`/
`output` on success, same limitation noted in `bugs/003`), but the
mechanism fully explains the failure independent of what the model
specifically guessed.

## Root cause

`where`'s real accepted shape, read directly from
`plugins/spatial_query_filter.py`:

```python
def _eval_where(properties: dict[str, Any], where: Any, *, case_sensitive: bool) -> bool:
    """
    Evaluate full where expression.

    Supported:
        None
        {"field": "name", "op": "contains", "value": "teh"}
        {"and": [cond1, cond2]}
        {"or": [cond1, cond2]}
        {"not": cond}
        {"name": "Tehran", "population": {"gt": 1000}}
    """
    if where is None:
        return True
    if not isinstance(where, dict):
        raise ValueError("where must be a dict/object or None.")
    ...
```

A real, non-trivial structured schema: canonical `{field, op, value}`
conditions, boolean combinators (`and`/`or`/`not`), and a shortcut dict
form. None of this is documented anywhere the LLM can see it.
`_op_param_reference()` (added in the `bugs/003` fix, 0.4.2) generates
only the *parameter key list* per operation from `OP_CATALOG.param_map`:

```python
def _op_param_reference() -> str:
    """
    Every supported operation's accepted params - the exact keys "params"
    may use for that operation - generated directly from OP_CATALOG's
    param_map rather than hand-written per-operation examples.
    ...
    """
    lines = []
    for name in list_supported_ops():
        params = list(get_op(name).param_map)
        param_desc = ", ".join(params) if params else "(none)"
        lines.append(f"- {name}: params keys = {{{param_desc}}}")
    return "\n".join(lines)
```

That produces `- filter_attribute: params keys = {where, case_sensitive,
sort_by, sort_order, limit, offset, bbox, bbox_mode, geometry_type,
metadata}` — the key `where` is now correctly listed, but nothing says
what a valid *value* for `where` looks like. Searching
`_domain_guidance()`'s full body for `where` finds exactly one mention,
and it's about a completely different operation
(`query_database`/PostGIS's own `where`, a raw-ish clause string in that
context, not `filter_attribute`'s structured dict) — actively confusing
if the model generalizes from it. `filter_attribute`'s `where` shape
(`field`/`op`/`value`, `and`/`or`/`not`, or the shortcut form) appears
nowhere in the prompt.

This is the same underlying problem `bugs/003` diagnosed and half-fixed:
the LLM is taught operation names and, as of 0.4.2, parameter *names* —
but for any operation whose parameter *value* is itself structured (not
a plain string/number/bool), there is still no worked example or shape
description, so the model has nothing to generalize from beyond the bare
key name. `filter_attribute`'s `where` is the first one this study hit,
but the same gap likely affects any other structured param in
`OP_CATALOG` (e.g. `bbox`'s `list[float] | dict[str, float]` union,
`score_features`'s factor specs, etc. — not independently confirmed here,
flagged for whoever picks this up).

## Reproduction

Independent of the LLM, directly against the plugin (mirroring
`bugs/003`'s style of isolating the mechanism, not just the one observed
crash):

```python
from plugins.spatial_query_filter import filter_features

filter_features(features={"type": "FeatureCollection", "features": []},
                 where="amenity = hospital")
# ValueError: where must be a dict/object or None.

# What the plugin actually wants instead:
filter_features(features={"type": "FeatureCollection", "features": []},
                 where={"field": "amenity", "op": "eq", "value": "hospital"})
# (succeeds - empty result set here, but no shape error)
```

This repo's real trigger: `notebooks/03_llm_arm.ipynb` §4's smoke test,
same raw query as `bugs/002`/`bugs/003` (`data/raw/hospitals.geojson` +
`data/raw/mahalle_boundaries.geojson`), `filter_attribute` node named
`underserved_mahalle` by the LLM's own `output` ref.

## Proposed fix

### Plugin layer (deterministic)

Two independent options, not mutually exclusive:

1. Add a generation-time validator in `llm_spec_generator.py`, in the
   same family as the existing `_validate_distance_op_crs_symmetry` and
   `_validate_filter_points_in_polygon_usage`, that structurally checks
   any `filter_attribute`/`sort_limit` operation's `where` value (when
   present) is a `dict` before the plan is accepted — turning this into
   a clear `LLMSpecGenerationError` at generation time instead of a
   `RuntimeError` after a full DAG build and partial execution.
2. `filter_features`'s own `ValueError` message is already reasonably
   clear (`"where must be a dict/object or None."`) — the DAG executor
   could catch and pass through plugin-raised `ValueError`s with the
   node id and operation name prefixed (it already does this for the
   node id per the `"Node {id} failed: {message}"` format observed
   here), which is already happening; the remaining gap is purely that
   it happens at execution time rather than generation/planning time.

### LLM-prompt layer (generative)

Extend `_op_param_reference()` (or add a sibling function) to include a
short worked shape example for any operation parameter whose type isn't
a plain scalar — at minimum `filter_attribute`'s `where`, using the
docstring in `_eval_where` itself as the source of truth (it's already
written, just not surfaced to the model):
```
- filter_attribute.where: {"field": "<property>", "op": "eq|gt|lt|contains|in|...", "value": <value>}
  or shortcut {"<property>": <value>}, or {"and": [...]}/{"or": [...]}/{"not": ...}
```
This is exactly the same fix shape `bugs/003` already established
(derive prompt guidance from the real source of truth rather than a
hand-written example that can silently drift) — applied one level
deeper, to parameter *values* rather than just parameter *keys*.

## Local mitigation in this repo, if any

None available through `s3geo.query()`'s public API — there's no
`system_hints` content this repo could add that would reach
`_op_param_reference()`'s auto-generated section (that part of the
prompt isn't influenced by the caller's `system_hints` string, it's
built from `OP_CATALOG` internally). `system_hints` *could* in principle
carry a hand-written note about `where`'s shape as a workaround, but
that reintroduces exactly the hand-maintained-example fragility this
framework's own `_op_input_roles_reference()`/`_op_param_reference()`
docstrings say they were built to avoid — not applied here for that
reason. Not treated as a Phase 4 blocker for the same reasoning as
`bugs/003`: one LLM plan producing an invalid parameter value is a
legitimate, informative outcome for the N=20 batch to characterize the
rate of, not a hard block.

## Resolution

Not yet resolved upstream. Reported here as of 2026-09-19; update this
section with the upstream version that fixes it and the commit that bumps
the pin, once available.
