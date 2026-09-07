# get_file Validation Fix Report

Date: 2026-09-07

## Schema Confirmation

The Groq tool schema in `agent.py` correctly declares the `get_file` arguments:

```json
{
  "required": ["file_path", "start_line", "end_line", "repo_id"]
}
```

The three source-range arguments and the repository identifier are all present in the `properties` object and all four are marked required. The failure was therefore caused by the model emitting an invalid tool call, not by an incomplete schema.

## Fix

The Groq completion call is now wrapped in an error boundary. When the provider reports a tool-schema failure, including `tool_use_failed`, an invalid tool-call message, or a 400 error containing a tool failure, the agent:

1. Does not expose the raw provider exception to the API/UI.
2. Runs `run_degraded_semantic_fallback` against the indexed repository.
3. Returns `status="rate_limited_fallback"` with `fallback_reason="tool_schema_validation_error"`.
4. Includes a clean semantic-search trace and an explicit degraded-mode warning.

Rate-limit, timeout, and unrelated provider exceptions retain their existing handling behavior.

## Reproduction

Repository: freshly indexed `pallets/click` clone, repository ID `1`.

Question:

```text
what this repository is about
```

The `get_file` failure was deterministically reproduced with the equivalent provider error:

```text
400 tool_use_failed: tool call get_file missing required parameter file_path
```

Result after the fix:

```text
status: rate_limited_fallback
grounded: true
fallback_reason: tool_schema_validation_error
provider_error: Groq rejected a tool call because required arguments were invalid or missing.
trace tools: semantic_search
raw 400 error surfaced: no
```

The returned answer begins with the explicit degraded fallback warning and lists real indexed candidate functions with file paths, line ranges, and similarity scores. No fabricated synthesized answer is presented.

The same broad question also ran against the real fresh index without a raw 400 error; on one three-turn run the model repeatedly requested semantic search and reached the normal tool budget, returning the existing `budget_exhausted` status rather than an unhandled provider exception.

## Verification

- Python compilation: passed.
- `get_file` required-field schema inspection: passed.
- Malformed Groq tool-call handling: passed.
- Fresh indexed repository fallback search: passed.
- Raw `tool_use_failed` error exposed to the user: eliminated.
