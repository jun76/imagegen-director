# Pitfalls found while building the-world (10,000 images)

Check for these in every test generation. Each one is already guarded by a rule or a schema
feature; the point is to recognize new problems of the same kind and turn them into rules.

| Symptom in the images | Cause | Fix that holds on regeneration |
|---|---|---|
| A phone, camera or CCTV unit appears in the picture | The prompt named the capture device ("Smartphone photo", "DSLR photograph", "security camera still") | Universal rule `no-capture-device`; describe the look instead. Exceptions per project via `overrides` (subjects that *are* devices). |
| Insects, worms, snakes, fish, mold, disembodied ears or hands fill the frame edge to edge; repulsive (trypophobia) | count "crowd or many" on creatures, amplified by "countless". Models ignore "loosely scattered". | `subject_remaps` in axes.yaml (never sample a crowd for those subjects), a `deny_axes` guard rule, and a wording rule for the same group. Universal `no-dense-mass` bans "countless" everywhere. |
| Every image looks polished and alike | Quality incantations | Universal `no-quality-incantations`. |
| Many images share one composition or medium | Weights too skewed, or repeated values within a leaf | `unique_per_leaf` on media; check `out/report.md` max gaps. |
| Axes correlate (e.g. one medium always with one light) | Deterministic rotation, or beta too high | Keep beta around 0.2; check Cramér's V in the report. |
| Subject unrecognizable | Too many axis values honored at once | Subject first; absorb or drop values. |
| A run of near-identical subjects (ten giant mushrooms in a row) | `per_leaf` too high for a narrow leaf: the-world draws each concrete leaf 10 times | Decide images per subject with the user in step 1; for broad sets keep `per_leaf` at 1-3 and add leaves instead. The report's first lines show it. |

## Process lessons

- **Fix the rule, not the prompt.** When a test batch shows a problem, add or tighten a rule
  (or a remap) first, then rewrite the prompts until `assemble.py` passes. Hand-editing only the
  offending prompts lets the problem come back on the next regeneration.
- **Test before the full run.** Generate a few dozen images spread over media and subjects and
  look at them as a contact sheet before generating everything.
- **After changing prompts**, run `scripts/prune_results.py --project <dir> results/<backend>` before resuming a
  batch: it moves images made from old prompts aside so only changed rows are regenerated.
- **Rules outlive rewrite scripts.** A one-off script that bulk-rewrites prompts is project-local
  scratch; the lasting lesson belongs in a rule (or in this file) so it holds for every project.
