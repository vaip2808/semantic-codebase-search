# Cleanup Report

## Moved to `un_ness/`

The following files and local-only directories were moved without deletion:

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
- `upload_prep_day1.md`
- `upload_prep_day1_final.md`
- `upload_prep_keys_final.md`
- `env_keys_updated_report.md`
- `fresh_clone_verification.md`
- `fresh_clone_verification_v2.md`
- `get_file_validation_fix_report.md`
- `get_file_validation_fix_v2.md`
- `markdown_rendering_fix_report.md`
- `ui_fixes_report.md`
- `delete_repo_feature_report.md`
- `model_benchmark_reconciled.md`
- `desktop.ini`
- `.env` (local secret configuration, never public)
- `sementic_cb_search.db` and `sementic_cb_search_test.db` (local databases)
- `sementic_cb_search_startup_test.db` (fresh database created during verification)
- `.venv` and `.venv-1` (local virtual environments)
- `data/` (previously cloned repositories and metadata)
- `__pycache__` (Python bytecode cache)

## Deliberately kept at the project root

- `main.py`: FastAPI application entry point and API routes.
- `agent.py`: agent reasoning and repository tools imported at runtime.
- `parser.py`: AST parsing and call-graph construction imported at runtime.
- `embeddings.py`: embedding generation and persistence imported at runtime.
- `db.py`: SQLAlchemy models and database initialization imported at runtime.
- `ingestion.py`: cloning, source filtering, and runtime-directory setup imported at runtime.
- `static/index.html`: browser UI served by `main.py`.
- `README.md`: public setup, architecture, usage, and verification documentation.
- `requirements.txt`: installable runtime dependency list.
- `.env.example`: safe configuration template for new users.
- `.gitignore`: excludes secrets, runtime data, caches, databases, and `un_ness/`.
- `LICENSE`: public MIT license.
- `dashboard_ss.png`: screenshot referenced by the README.
- `model_benchmark_final.md`: retained clean public evaluation report referenced by the README.
- `production_model_decision.md`: retained clean public model-selection report referenced by the README.
- `cleanup_report.md`: this cleanup record.

The empty `data/clones/` and `data/metadata/` directories remain available as
runtime locations. `ingestion.ensure_runtime_directories()` recreates them on
startup, and `.gitignore` keeps their contents out of the public repository.

## Verification

- `un_ness/` is listed in `.gitignore`.
- The application started successfully with `python main.py` after the move.
- `GET http://127.0.0.1:8000/api/repos` returned HTTP 200 from the clean root
  and initialized a fresh empty SQLite database.
- No core import or runtime file was moved.

