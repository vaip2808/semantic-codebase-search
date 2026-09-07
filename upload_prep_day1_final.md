# Upload Preparation: Day 1 Final

Date: 2026-09-07

## Environment Keys

The three current `.env` values were checked locally without printing them into this report.

| Key | Compared with compromised value supplied for this audit | Current verification |
|---|---|---|
| `GEMINI_API_KEY` | Does not match | Rotated-looking value present; the referenced `env_keys_fixed_report.md` was not available in the workspace for literal comparison |
| `GROQ_API_KEY` | Does not match | Current value was used successfully by the live Groq smoke test with `openai/gpt-oss-20b` |
| `LANGSEARCH_API_KEY` | Does not match | Rotated-looking value present; the referenced rotation report was not available in the workspace for literal comparison |

The original compromised values are not used. No key was re-written because none matched the supplied compromised values. The local `.env` remains ignored and is not tracked in the fresh Git history.

## Stray Files Removed

Deleted from disk and removed from the new Git snapshot:

- `main (8).aux`
- `main (8).log`
- `main (8).out`

The project scan found no other `.bak`, `.old`, editor swap files, or duplicate files with `(1)`, `(2)`, etc. in their names.

## Benchmark and Scratch Artifact Review

### Keep

- `model_benchmark_final.md`: polished model-selection evidence and production recommendation.
- `model_benchmark_reconciled.md`: useful methodology and benchmark reconciliation, if the resume narrative needs detail.
- `production_model_decision.md`: concise rationale for selecting the active Groq model.
- `benchmark_data_verification.md`: keep only if revised to remove stale running-task language and internal quota details.
- `stopping_behavior_fix_report.md`: keep only after editing out internal task IDs, local file URLs, and stale in-progress wording.
- `stopping_fix_retest_verified.md`: keep only after the same cleanup; otherwise exclude.

### Exclude

These are raw or intermediate artifacts and should stay out of a polished public resume repository:

- `benchmark_results_complete.json`
- `benchmark_results_current.json`
- `benchmark_results_maxturns10_current.json`
- `scratch_check_c_24runs.json`
- `scratch_check_c_70b.json`
- `scratch_check_c_midtier.json`
- `scratch_check_c_prefix.json`
- `scratch_metrics.json`
- `scratch_q1_trace.json`
- `scratch_q5_10runs_temp0.json`
- `scratch_q6_5runs.json`
- `eval_pipeline.json`
- `eval_section_a.json`
- `eval_section_b.json`
- `eval_section_c.json`

These files are currently in the fresh commit because the original `.gitignore` did not exclude them. They should be removed from tracking before the public upload, while retaining any useful conclusions in a short polished benchmark summary.

## Final Status

- Fresh Git history: complete.
- Credential-shaped tracked-file scan: passed.
- Local `.env` excluded: confirmed.
- Clear disk strays: removed.
- Key comparison limitation: the referenced rotation reports were not present locally, so Gemini and LangSearch were verified as non-matching the compromised values, not report-matched.
- Packaging blocker remaining: remove raw benchmark/evaluation artifacts and produce the README/dependency manifest during Day 2.
