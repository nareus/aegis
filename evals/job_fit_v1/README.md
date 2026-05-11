# job_fit_v1

Evaluates the Researcher → Analyst → Critic pipeline end-to-end on real job
descriptions. The score is the fraction of cases whose final analysis satisfies
every assertion in their `expected` block.

## Files

- `cases/*.yaml` — one case per file. Source of truth.
- Mirrored into the `eval_golden_cases` table by `scripts/seed_evals.py`.
- Run with `scripts/run_eval.py job_fit_v1`. Each run writes one row to
  `eval_runs`.

## Case shape

```yaml
case_id: <stable-slug>          # filename without .yaml
eval_name: job_fit_v1
notes: |
  Free-form description of why this case exists and what it should verify.

input:
  url_or_text: |
    <full JD text or a URL>

expected:
  # All keys are optional. The runner only checks keys that are present.
  recommendation: apply | review_more | skip
  fit_score: {min: 0.0, max: 1.0}
  must_include_skills: [python, postgresql]   # case-insensitive
  must_not_have_deal_breakers: true           # asserts deal_breakers_present == []
```

## Adding cases

Aim for a mix:

- **Obvious-pass** (`*_apply.yaml`) — strong fit; recommendation should be `apply`.
- **Obvious-fail** (`*_skip.yaml`) — outside profile; recommendation should be `skip`.
- **Ambiguous** (`*_review.yaml`) — borderline; useful for catching prompt regressions.

When you hit a production failure in `agent_traces`, copy the JD into a new
case file with the *correct* expected output, then re-run the eval.
