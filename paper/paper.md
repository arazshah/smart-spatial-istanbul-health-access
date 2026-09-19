# Which İstanbul mahalle are underserved by hospitals and clinics?

**Status: not started.** This file is a placeholder so the deliverable has a
home, and so nobody mistakes an absent paper for a lost one.

Nothing has been run yet: `data/raw/` is empty, there are no results, and no
sentence of this paper can be written honestly until phases 1–6 in
[`PLAN.md`](PLAN.md) have produced real output. See `CLAUDE.md` —
this repository does not put invented or synthetic numbers in a final
result, and a placeholder that says so is better than a plausible draft that
would have to be unwritten.

Planned structure, per `PLAN.md`:

1. Introduction — health-facility accessibility, the mahalle as the unit
2. Data — OSM via Overpass, AOI, CRS, coverage caveats (`../data/README.md`)
3. Method — the rule-based arm, the LLM-planned arm, the comparison metric
4. Results — the underserved map, the underserved-mahalle table, threshold
   sensitivity, and where the two arms disagree
5. Discussion — Euclidean vs. network distance, the Bosphorus, hospitals vs.
   clinics, population weighting, and what plan-level variability means for
   using an LLM planner in this kind of analysis
6. Limitations
7. Data and code availability
