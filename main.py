import os
import sys

# Add parent directory of sementic_cb_search to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import uvicorn
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from datetime import datetime, UTC

try:
    import db, ingestion, parser, embeddings, agent
except ImportError:
    from sementic_cb_search import db, ingestion, parser, embeddings, agent

app = FastAPI(
    title="Semantic Codebase Search Agent",
    description="Ask natural-language questions about codebases grounded in a static call graph and vector embeddings.",
    version="1.0.0"
)

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request / Response Schemas
class RepoIndexRequest(BaseModel):
    url: str

class RepoAskRequest(BaseModel):
    question: str
    disable_fallback: bool = False

STUCK_THRESHOLD_SECONDS = 1800  # 30 minutes threshold for stuck repos

# Background indexing worker task
def background_index_repo(repo_id: int, url: str):
    session = db.get_session()
    current_stage = "cloning"
    try:
        # Step A: Update status to cloning
        repo = session.query(db.Repo).filter(db.Repo.id == repo_id).first()
        if not repo:
            return
        repo.status = "cloning"
        repo.last_progress_at = datetime.now(UTC)
        session.commit()
        print(f"[BACKGROUND TASK] Ingesting & cloning: {url} (ID: {repo_id})")

        # Step 1: Ingestion (Clone + walk + filter)
        metadata = ingestion.ingest_repository(url)
        
        # Step B: Update status to parsing call graph
        current_stage = "parsing"
        repo = session.query(db.Repo).filter(db.Repo.id == repo_id).first()
        repo.status = "parsing"
        repo.last_progress_at = datetime.now(UTC)
        session.commit()
        print(f"[BACKGROUND TASK] Building call graph for ID: {repo_id}")

        # Step 2: Call Graph Extractor & database insertion
        graph_res = parser.build_and_store_call_graph(metadata)

        # Step C: Update status to embedding
        current_stage = "embedding"
        repo = session.query(db.Repo).filter(db.Repo.id == repo_id).first()
        repo.status = "embedding"
        repo.last_progress_at = datetime.now(UTC)
        session.commit()
        print(f"[BACKGROUND TASK] Generating embeddings for ID: {repo_id}")

        # Step 3: Embeddings generation and database storage
        embeddings.generate_embeddings_for_repo(repo_id)

        # Step D: Ready!
        repo = session.query(db.Repo).filter(db.Repo.id == repo_id).first()
        repo.status = "ready"
        repo.last_progress_at = datetime.now(UTC)
        repo.failed_stage = None
        repo.failed_at = None
        repo.error_message = None
        session.commit()
        print(f"[BACKGROUND TASK] Repo ID {repo_id} is fully indexed and ready!")

    except Exception as e:
        session.rollback()
        repo = session.query(db.Repo).filter(db.Repo.id == repo_id).first()
        if repo:
            repo.status = "failed"
            repo.failed_stage = current_stage
            repo.failed_at = datetime.now(UTC)
            repo.last_progress_at = datetime.now(UTC)
            repo.error_message = str(e)
            session.commit()
        print(f"[BACKGROUND TASK ERROR] Failed indexing Repo ID {repo_id}: {e}")
    finally:
        session.close()

# API Endpoints
@app.post("/api/repos", status_code=status.HTTP_201_CREATED)
def index_repository(payload: RepoIndexRequest, background_tasks: BackgroundTasks):
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Repository URL cannot be empty.")
    
    try:
        owner, repo_name = ingestion.parse_github_url(url)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    session = db.get_session()
    try:
        now_utc = datetime.now(UTC)
        from datetime import timedelta
        from sqlalchemy import or_, and_
        stale_cutoff = now_utc - timedelta(seconds=STUCK_THRESHOLD_SECONDS)

        # Atomic Attempt 1: Try recovering a STUCK repository (stale progress heartbeat > 30m)
        stuck_updated = session.query(db.Repo).filter(
            db.Repo.url == url,
            db.Repo.status.in_(["pending", "cloning", "parsing", "embedding"]),
            or_(
                db.Repo.last_progress_at < stale_cutoff,
                and_(db.Repo.last_progress_at.is_(None), db.Repo.ingested_at < stale_cutoff)
            )
        ).update({
            "status": "pending",
            "failed_stage": None,
            "failed_at": None,
            "error_message": None,
            "last_progress_at": now_utc,
            "ingested_at": now_utc
        }, synchronize_session=False)

        if stuck_updated > 0:
            session.commit()
            repo = session.query(db.Repo).filter(db.Repo.url == url).first()
            background_tasks.add_task(background_index_repo, repo.id, url)
            return {
                "repo_id": repo.id,
                "name": repo.name,
                "status": "pending",
                "message": f"Stuck repository recovery triggered (heartbeat stale > {int(STUCK_THRESHOLD_SECONDS)}s). Indexing restarted."
            }

        # Atomic Attempt 2: Try recovering a FAILED repository
        failed_updated = session.query(db.Repo).filter(
            db.Repo.url == url,
            db.Repo.status == "failed"
        ).update({
            "status": "pending",
            "failed_stage": None,
            "failed_at": None,
            "error_message": None,
            "last_progress_at": now_utc,
            "ingested_at": now_utc
        }, synchronize_session=False)

        if failed_updated > 0:
            session.commit()
            repo = session.query(db.Repo).filter(db.Repo.url == url).first()
            background_tasks.add_task(background_index_repo, repo.id, url)
            return {
                "repo_id": repo.id,
                "name": repo.name,
                "status": "pending",
                "message": "Retrying index for failed repository."
            }

        # Case 3: Repo already exists and is ACTIVE/PROGRESSING (or another concurrent request already reset it)
        existing_repo = session.query(db.Repo).filter(db.Repo.url == url).first()
        if existing_repo:
            ref_time = existing_repo.last_progress_at or existing_repo.ingested_at
            if ref_time and ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=UTC)
            time_since_progress = (now_utc - ref_time).total_seconds() if ref_time else 0
            return {
                "repo_id": existing_repo.id,
                "name": existing_repo.name,
                "status": existing_repo.status,
                "message": f"Repository indexing is active in '{existing_repo.status}' state (last progress heartbeat {int(time_since_progress)}s ago)."
            }

        # Case 4: Create new Repo record
        new_repo = db.Repo(
            name=repo_name,
            url=url,
            status="pending",
            last_progress_at=now_utc,
            ingested_at=now_utc
        )
        session.add(new_repo)
        session.commit()
        session.refresh(new_repo)

        # Trigger background task
        background_tasks.add_task(background_index_repo, new_repo.id, url)

        return {
            "repo_id": new_repo.id,
            "name": new_repo.name,
            "status": "pending",
            "message": "Repository indexing started in background."
        }
    finally:
        session.close()

@app.get("/api/repos")
def list_repositories():
    session = db.get_session()
    try:
        repos = session.query(db.Repo).order_by(db.Repo.ingested_at.desc()).all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "url": r.url,
                "status": r.status,
                "failed_stage": r.failed_stage,
                "failed_at": r.failed_at.isoformat() if r.failed_at else None,
                "last_progress_at": r.last_progress_at.isoformat() if r.last_progress_at else None,
                "error_message": r.error_message,
                "ingested_at": r.ingested_at.isoformat() if r.ingested_at else None
            }
            for r in repos
        ]
    finally:
        session.close()

@app.get("/api/repos/{repo_id}/status")
def get_repository_status(repo_id: int):
    session = db.get_session()
    try:
        repo = session.query(db.Repo).filter(db.Repo.id == repo_id).first()
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found.")
        return {
            "id": repo.id,
            "name": repo.name,
            "url": repo.url,
            "status": repo.status,
            "failed_stage": repo.failed_stage,
            "failed_at": repo.failed_at.isoformat() if repo.failed_at else None,
            "last_progress_at": repo.last_progress_at.isoformat() if repo.last_progress_at else None,
            "error_message": repo.error_message
        }
    finally:
        session.close()

@app.delete("/api/repos/{repo_id}")
def delete_repository(repo_id: int):
    """Delete a repository and all indexed data, including its local clone."""
    session = db.get_session()
    clone_path = None
    try:
        repo = session.query(db.Repo).filter(db.Repo.id == repo_id).first()
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found.")

        active_statuses = {"pending", "cloning", "parsing", "embedding"}
        if repo.status in active_statuses:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete repository while indexing is in progress (status: '{repo.status}')."
            )

        clone_root = os.path.realpath(ingestion.TEMP_CLONE_DIR)
        candidate = repo.clone_path or os.path.join(ingestion.TEMP_CLONE_DIR, repo.name)
        resolved_candidate = os.path.realpath(candidate)
        if os.path.dirname(resolved_candidate) == clone_root:
            clone_path = resolved_candidate

        function_ids = [row[0] for row in session.query(db.Function.id).filter(db.Function.repo_id == repo_id).all()]
        if function_ids:
            session.query(db.FunctionEmbedding).filter(db.FunctionEmbedding.function_id.in_(function_ids)).delete(synchronize_session=False)
            session.query(db.CallEdge).filter(
                (db.CallEdge.caller_function_id.in_(function_ids)) |
                (db.CallEdge.callee_function_id.in_(function_ids))
            ).delete(synchronize_session=False)
            session.query(db.UnresolvedCall).filter(db.UnresolvedCall.caller_function_id.in_(function_ids)).delete(synchronize_session=False)
            session.query(db.Function).filter(db.Function.id.in_(function_ids)).delete(synchronize_session=False)

        session.delete(repo)
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete repository: {exc}")
    finally:
        session.close()

    cleanup_errors = []
    if clone_path:
        try:
            ingestion.safe_rmtree(clone_path)
        except Exception as exc:
            cleanup_errors.append(str(exc))
    metadata_path = os.path.join(ingestion.METADATA_DIR, f"{repo.name}.json")
    try:
        if os.path.isfile(metadata_path):
            os.remove(metadata_path)
    except OSError as exc:
        cleanup_errors.append(str(exc))

    response = {"repo_id": repo_id, "status": "deleted", "message": "Repository and indexed data deleted."}
    if cleanup_errors:
        response["cleanup_warning"] = "Database rows were deleted, but local file cleanup was incomplete: " + "; ".join(cleanup_errors)
    return response

@app.get("/api/repos/{repo_id}/files")
def get_repository_files(repo_id: int):
    session = db.get_session()
    try:
        paths = session.query(db.Function.file_path).filter(db.Function.repo_id == repo_id).distinct().all()
        return [p[0] for p in paths if p[0]]
    finally:
        session.close()

@app.post("/api/repos/{repo_id}/ask")
def ask_repository_agent(repo_id: int, payload: RepoAskRequest):
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question prompt cannot be empty.")

    session = db.get_session()
    try:
        repo = session.query(db.Repo).filter(db.Repo.id == repo_id).first()
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found.")
        
        if repo.status != "ready":
            raise HTTPException(
                status_code=400, 
                detail=f"Repository is not ready for querying yet. Current status: '{repo.status}'."
            )
    finally:
        session.close()

    try:
        result = agent.ask_agent(question, repo_id, disable_fallback=payload.disable_fallback)
        # Return HTTP 500 error if execution fails due to turn limit exhaustion
        if result["status"] == "budget_exhausted":
            raise HTTPException(status_code=500, detail=result["answer"])
            
        return {
            "answer": result["answer"],
            "trace": result["trace"],
            "turns_used": result["turns_used"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent loop error: {e}")

@app.get("/api/repos/{repo_id}/file")
def get_file_content(
    repo_id: int,
    file_path: str = Query(..., description="Relative file path"),
    start_line: int = Query(..., description="Start line number"),
    end_line: int = Query(..., description="End line number")
):
    # Ensure correct parameters type
    try:
        start_line = int(start_line)
        end_line = int(end_line)
    except ValueError:
        raise HTTPException(status_code=400, detail="Lines must be integers.")

    session = db.get_session()
    try:
        repo = session.query(db.Repo).filter(db.Repo.id == repo_id).first()
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found.")
    finally:
        session.close()

    res = agent.get_file(file_path, start_line, end_line, repo_id)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

# Initialize tables and serve Frontend
@app.on_event("startup")
def on_startup():
    ingestion.ensure_runtime_directories()
    db.init_db()

# Serve static directory containing HTML UI at root /
# Ensure 'static' folder exists
STATIC_DIR = os.path.join(APP_ROOT, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
