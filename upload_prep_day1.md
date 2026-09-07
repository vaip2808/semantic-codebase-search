# Upload Preparation: Day 1

Date: 2026-09-07

## 1. Git History and Secrets

- Preferred strategy: fresh git history, as requested for the one-week deadline.
- The previous `.git` directory was removed and a new repository was initialized.
- `.env` is ignored by `.gitignore` and is absent from the staged file list.
- Runtime artifacts are also ignored: databases, `data/`, `scratch/`, and Python caches.
- Credential-shaped scan across tracked text passed:
  - `sk-[A-Za-z0-9_-]{10,}`: none
  - `gsk_[A-Za-z0-9_-]{10,}`: none
  - `AQ\.[A-Za-z0-9_-]{10,}`: none
- Python modules compile successfully with `python -m py_compile`.

Important: the local `.env` still contains credentials that were previously exposed. Those keys must be revoked and replaced in the provider dashboards before publishing. Ignoring the file protects the new Git history, but does not invalidate old keys.

## 2. Live Default Model Smoke Test

`agent.py` now defaults to:

```text
openai/gpt-oss-20b
```

The model is active on Groq and supports tool use/function calling. The agent execution path now uses Groq's OpenAI-compatible chat completion API.

Smoke test:

```text
Question: Where is the main HTTP request sending flow implemented in requests?
Repository: psf/requests (repo_id=1)
Result: status=success
Grounded: true
Turns used: 3
Tool calls: 2
Errors: none
```

Full trace:

### Turn 1: `semantic_search`

Arguments:

```json
{
  "query": "send request flow",
  "repo_id": 1,
  "top_k": 5
}
```

Returned, in rank order:

```text
187  src/requests/sessions.py   Session.send          lines 752-829  similarity 0.6395
21   src/requests/api.py        request              lines 24-71    similarity 0.6279
20   src/requests/adapters.py   HTTPAdapter.send      lines 634-748  similarity 0.6232
168  src/requests/sessions.py   SessionRedirectMixin.send line 132 similarity 0.6192
179  src/requests/sessions.py   Session.request       lines 557-653  similarity 0.6161
```

### Turn 2: `get_file`

Arguments:

```json
{
  "file_path": "src/requests/sessions.py",
  "start_line": 750,
  "end_line": 830,
  "repo_id": 1
}
```

The returned implementation confirms that `Session.send` resolves the adapter and delegates to `adapter.send(request, **kwargs)`, then handles elapsed time, hooks, cookies, redirects, and response content.

### Final answer

The core of the HTTP-request sending logic lives in `Session.send` in `requests/sessions.py`, lines 752-829. It normalises request settings, resolves the adapter, calls `adapter.send`, and handles response timing, hooks, cookies, and redirects. The low-level network operation is implemented by `HTTPAdapter.send` in `requests/adapters.py`, lines 634-748.

## 3. Loose Ends

- `pallets/flask` is present in the local database with `status="ready"`.
- `run_local_agent_simulation` no longer exists in the project.
- `run_degraded_semantic_fallback` exists in `agent.py` and remains the fallback implementation.

## Remaining Blockers Before README/Packaging

1. Revoke and rotate the credentials currently present in the local `.env`.
2. Decide whether benchmark JSON, scratch outputs, and `main (8).*` artifacts belong in the public resume repository. They are currently staged because they are not ignored.
3. Add a dependency manifest and README before publishing. The Groq SDK is now required by the active agent path.
