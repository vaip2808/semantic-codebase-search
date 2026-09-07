# Fresh Clone Verification v2

Date: 2026-09-07

## Diagnosis

The original failure had two related causes:

1. `ingestion.py` used bare relative paths: `data/clones` and `data/metadata`. Those paths depended on the process working directory and were not initialized during application startup.
2. `main.py` inserted the Desktop parent directory and imported `sementic_cb_search` by package name. In a differently named fresh clone, that resolved to the original sibling project instead of the clone's local modules. This explained the old repository ID and why the clone's own runtime directories were not being created.

The fix anchors ingestion and static paths to `__file__`, creates ingestion directories in the FastAPI startup hook, and makes the application prefer local modules (`db`, `ingestion`, `parser`, `embeddings`, `agent`) before falling back to package imports.

## Clean-Room Run

Verification clone: `C:\Users\Vaibhav Pawar\Desktop\sementic_cb_search_fresh_clone_v3`

The v3 clone was created from the fixed commit with no existing `data/`, database, or virtual environment. A fresh `.venv` was created and `requirements.txt` installed successfully. `.env.example` was copied to `.env`, the three verified provider keys were filled in, and `DATABASE_URL` was left blank as permitted by the README so the test used SQLite.

### Server startup

Command:

```powershell
python main.py
```

Result: **PASS**. Uvicorn started at `http://127.0.0.1:8000` and FastAPI startup completed. Before the first API request, the application created:

```text
data/clones
data/metadata
```

No manual directory creation was performed.

### Repository indexing

The README request shape was used with a new repository:

```powershell
curl -X POST http://127.0.0.1:8000/api/repos \
  -H "Content-Type: application/json" \
  -d '{"url":"https://github.com/pallets/click"}'
```

Result: **PASS**. The API returned repository ID `1` and `status="pending"`. Polling `/api/repos/1/status` progressed through cloning, parsing, and embedding, then returned:

```text
status: ready
failed_stage: null
error_message: null
```

The repository contained 669 functions. Embeddings completed across 27 batches, including normal Gemini 429 backoff/retry cycles. This confirms the rate-limit handling remains functional on a clean install.

### Ask flow

The documented ask endpoint was called over HTTP against the newly indexed repository:

```powershell
curl -X POST http://127.0.0.1:8000/api/repos/1/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the purpose of the command decorator?"}'
```

Result: **PASS**. The endpoint returned HTTP `200` with:

```text
grounded: true
turns_used: 3
trace entries: 2
```

Trace:

```text
Turn 1: semantic_search
  query: command decorator
  top result: src/click/decorators.py, command, lines 168-255

Turn 2: get_file
  file: src/click/decorators.py
  lines: 150-220
```

The answer explained that Click's `command` decorator creates a `Command` object, derives a command name, attaches decorated parameters, supports both decorator syntaxes, and returns a callable command. The answer cited `src/click/decorators.py` and was marked grounded by the API.

## README Fixes Verified

- `DATABASE_URL` is now explicitly documented as optional; leaving it blank uses SQLite, while PostgreSQL/pgvector remains available for persistent deployments.
- README now states that port `8000` must be free and explains how to change it in `main.py`.
- Runtime directories no longer need to be pre-created by a first-time user.

## Final Gate

**PASS.** The complete documented workflow succeeded on a genuinely fresh clone with no pre-existing runtime directories or database:

```text
clone -> fresh setup -> server startup -> automatic data directory creation
-> index new repository -> ready -> ask -> grounded answer with trace
```

The project is upload-ready from this verification perspective.
