# Fresh Clone Verification

Date: 2026-09-07

Verification clone: `C:\Users\Vaibhav Pawar\Desktop\sementic_cb_search_fresh_clone`

The verification used a fresh local Git clone, a new `.venv`, a new `.env`, and a new database path. No existing virtual environment, database, or indexed repository state was copied into the clone. The current verified provider keys were inserted into the fresh `.env` only for this test and are not included in this report.

## Step-by-Step Log

### 1. Fresh clone

Command:

```powershell
git clone --no-local C:\Users\Vaibhav Pawar\Desktop\sementic_cb_search C:\Users\Vaibhav Pawar\Desktop\sementic_cb_search_fresh_clone
```

Result: **PASS**. The clone was created outside the source working directory. Ignored runtime files such as the original database, `data/`, and `.venv` were absent.

### 2. Fresh virtual environment

Command:

```powershell
python -m venv .venv
```

Result: **PASS**. A new isolated virtual environment was created in the clone.

### 3. Install requirements

Command:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Result: **PASS after one transient tool-session issue**. The first install process output stopped before its final completion line, and the first server attempt reported `ModuleNotFoundError: No module named 'fastapi'`. Re-running the exact install command completed successfully; all pinned packages were then present and importable. This was an execution-session interruption, not a missing dependency in `requirements.txt`.

### 4. Create and populate `.env`

Commands:

```powershell
Copy-Item .env.example .env
```

The three current working API keys were inserted into the fresh `.env`. `DATABASE_URL` remained the template value from `.env.example`.

Result: **PASS**. The fresh clone had no pre-existing secrets or database state.

### 5. Start the server

Command:

```powershell
python main.py
```

Result: **PASS**. Uvicorn started at `http://127.0.0.1:8000`, FastAPI completed startup, and the application fell back to fresh SQLite because the template PostgreSQL endpoint was not running. The only startup warning was FastAPI's `on_event` deprecation warning.

### 6. Index a new repository

README request shape, using a repository not previously indexed in this clone:

```powershell
curl -X POST http://127.0.0.1:8000/api/repos `
  -H "Content-Type: application/json" `
  -d '{"url":"https://github.com/pallets/click"}'
```

Result: **FAIL during cloning**. The API correctly returned a pending repository record, but polling changed it to:

```text
status: failed
failed_stage: cloning
error: Repository not found or is private ... fatal: could not create work tree dir 'data/clones\click': Permission denied
```

The repository is public and a direct manual `git clone` into the same fresh clone's `data\clones` directory succeeded. The failure is therefore associated with the server's background/reloader process context when it creates the relative runtime path. Pre-creating `data\clones` and `data\metadata`, retrying the API request, and restarting `python main.py` did not resolve the background-process permission error.

Because indexing did not reach `ready`, the documented ask request could not be run honestly against this fresh index. No grounded answer or valid agent trace was claimed from this clean-room run.

## README Mismatches / Fixes Needed

1. **Blocking:** The README promises that a first-time user can run `python main.py` and index immediately, but the Windows clean-room run failed when the background indexing process attempted to create `data/clones`. The ingestion path should use an absolute application-root data path and/or create runtime directories during startup, and the Windows background-process behavior should be retested.
2. **Configuration clarity:** `.env.example` includes a PostgreSQL URL even though the local setup does not start PostgreSQL. The README does explain SQLite fallback, but a first-time user may interpret the template URL as a required running service. A clearer local default or an explicit “leave `DATABASE_URL` unset for SQLite” example would reduce confusion.
3. **Port behavior:** `python main.py` uses reload mode and port `8000`. The README should mention that an already-used port must be freed or that the port can be changed for local testing.

## Final Gate

The clean clone passed setup, dependency installation after retry, environment creation, and server startup. It did **not** pass the complete documented index-and-ask workflow because first-run Windows indexing failed in the background clone process. The project is therefore not yet fully verified as upload-ready/resume-safe until the `data/clones` permission/path issue is fixed and the new-repository indexing plus grounded ask flow are rerun successfully.
