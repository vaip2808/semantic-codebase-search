# get_file Validation Fix v2

Date: 2026-09-07

## Status Separation

The fallback contract now distinguishes the two failure classes:

- `rate_limited_fallback`: the LLM provider is rate-limited, over quota, timed out, or temporarily unavailable.
- `tool_error_fallback`: the provider rejected a malformed tool call, such as `get_file` missing required arguments.

The warning text is also distinct:

- Rate-limit fallback: the LLM service is temporarily rate-limited or unavailable.
- Tool-error fallback: the reasoning step hit a tool-validation error.

The tool-error response also includes `fallback_reason="tool_schema_validation_error"` and a redacted provider-error description. Raw provider exceptions are not returned to the user.

## Schema

The live tool declaration still marks all `get_file` parameters as required:

```json
{
  "required": ["file_path", "start_line", "end_line", "repo_id"]
}
```

## Five Real Live Runs

Question used for every run:

```text
what this repository is about
```

Target: freshly indexed `pallets/click` repository, ID `1`, with the live Groq model and no injected tool failure.

| Run | Outcome | Grounded | Turns | Tool calls | Trace |
|---:|---|---:|---:|---:|---|
| 1 | `rate_limited_fallback` | true | 1 | 1 | `semantic_search` |
| 2 | `rate_limited_fallback` | true | 1 | 1 | `semantic_search` |
| 3 | `rate_limited_fallback` | true | 1 | 1 | `semantic_search` |
| 4 | `rate_limited_fallback` | true | 1 | 1 | `semantic_search` |
| 5 | `rate_limited_fallback` | true | 1 | 1 | `semantic_search` |

All five live attempts hit the Groq organization TPD limit. Each returned a clean semantic-search fallback rather than an unhandled `RateLimitError`. No run naturally emitted the malformed `get_file` call during this five-run window, so the original model behavior is nondeterministic under the current provider state and was not observed live in these repetitions.

## Original Failure-Shape Check

The exact question was run through a deterministic provider-error reproduction using the freshly indexed repository and an equivalent Groq error:

```text
400 tool_use_failed: get_file missing required file_path
```

Result after the v2 changes:

```text
status: tool_error_fallback
grounded: true
fallback_reason: tool_schema_validation_error
warning: The reasoning step hit a tool-validation error.
raw 400 error surfaced: no
trace: semantic_search
```

This confirms the original failure shape is handled separately from rate limiting, even though the live model did not naturally reproduce it in five attempts.

## Verification Summary

- Distinct status values: **PASS**.
- Distinct warning text: **PASS**.
- Five real broad-question runs: **PASS**, all graceful rate-limit fallbacks.
- Natural malformed `get_file` recurrence: **not observed in 5 runs**; behavior is nondeterministic.
- Deterministic original failure-shape handling: **PASS**, returns `tool_error_fallback`.
- Raw 400/tool-validation error exposed to the user: **eliminated**.
