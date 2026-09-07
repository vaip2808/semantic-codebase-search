import os
import time
from google import genai
from google.genai import types
try:
    from db import get_session, Repo, Function, FunctionEmbedding, IS_POSTGRES
except ImportError:
    from sementic_cb_search.db import get_session, Repo, Function, FunctionEmbedding, IS_POSTGRES

EMBEDDING_MODEL = "gemini-embedding-2"
BATCH_SIZE = 25

def embed_text_chunks(chunks: list[str], max_retries: int = 7) -> list[list[float]]:
    if not chunks:
        return []
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in environment or .env file.")
    
    client = genai.Client(api_key=api_key)
    
    for attempt in range(max_retries):
        try:
            response = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=chunks,
                config=types.EmbedContentConfig(output_dimensionality=768)
            )
            if not response or not hasattr(response, "embeddings"):
                raise RuntimeError("Failed to get embeddings from Gemini API.")
            return [emb.values for emb in response.embeddings]
        except Exception as e:
            err_msg = str(e).lower()
            if "429" in err_msg or "resource_exhausted" in err_msg or "rate limit" in err_msg:
                sleep_sec = 5 * (attempt + 1)
                print(f"[WARNING] Gemini API rate limit (429). Retrying in {sleep_sec}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(sleep_sec)
                continue
            elif ("400" in err_msg or "413" in err_msg or "too large" in err_msg) and len(chunks) > 1:
                print(f"[WARNING] Batch payload too large ({len(chunks)} items). Splitting batch in half...")
                mid = len(chunks) // 2
                left = embed_text_chunks(chunks[:mid], max_retries)
                right = embed_text_chunks(chunks[mid:], max_retries)
                return left + right
            else:
                raise e
    raise RuntimeError("Gemini API rate limit retries exhausted.")

def read_function_code(clone_path: str, file_path: str, start_line: int, end_line: int) -> str:
    # Resolve absolute path
    abs_path = os.path.join(clone_path, file_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"File not found: {abs_path}")
    
    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    
    # Extract line range (start_line is 1-indexed, inclusive)
    target_lines = lines[start_line - 1 : end_line]
    return "".join(target_lines)

def generate_embeddings_for_repo(repo_id: int, force: bool = False) -> dict:
    session = get_session()
    try:
        from datetime import datetime, UTC
        repo = session.query(Repo).filter(Repo.id == repo_id).first()
        if not repo:
            raise ValueError(f"Repository with ID {repo_id} not found in database.")
        
        # Update status to embedding
        repo.status = "embedding"
        repo.last_progress_at = datetime.now(UTC)
        session.commit()
        
        # Fetch all functions in the repo
        functions = session.query(Function).filter(Function.repo_id == repo_id).all()
        if not functions:
            return {
                "status": "success",
                "functions_processed": 0,
                "embeddings_created": 0,
                "message": "No functions found in this repository."
            }

        # Filter out functions that already have embeddings if not forcing regeneration
        if not force:
            existing_func_ids = {
                fe.function_id for fe in session.query(FunctionEmbedding.function_id)
                .join(Function, Function.id == FunctionEmbedding.function_id)
                .filter(Function.repo_id == repo_id)
                .all()
            }
            functions_to_embed = [f for f in functions if f.id not in existing_func_ids]
        else:
            # Delete old embeddings for this repo
            session.query(FunctionEmbedding).filter(
                FunctionEmbedding.function_id.in_([f.id for f in functions])
            ).delete(synchronize_session=False)
            session.commit()
            functions_to_embed = functions

        if not functions_to_embed:
            return {
                "status": "success",
                "functions_processed": len(functions),
                "embeddings_created": 0,
                "message": "All functions are already embedded (use force=True to regenerate)."
            }

        print(f"[INFO] Preparing to embed {len(functions_to_embed)} functions for repo '{repo.name}'...")
        
        chunks = []
        valid_funcs = []
        failed_count = 0

        for f in functions_to_embed:
            try:
                code_text = read_function_code(repo.clone_path, f.file_path, f.start_line, f.end_line)
                if not code_text.strip():
                    print(f"[WARNING] Empty function body for '{f.name}' in {f.file_path}")
                    failed_count += 1
                    continue
                
                # Context-aware embedding prefix
                header = f"Class: {f.class_name or 'None'} | Function: {f.name} in {f.file_path}\n"
                chunk = header + code_text
                chunks.append(chunk)
                valid_funcs.append(f)
            except Exception as e:
                print(f"[WARNING] Failed to read source for '{f.name}' in {f.file_path}: {e}")
                failed_count += 1

        # Process in batches
        embeddings_created = 0
        start_time = time.time()

        for i in range(0, len(chunks), BATCH_SIZE):
            batch_chunks = chunks[i : i + BATCH_SIZE]
            batch_funcs = valid_funcs[i : i + BATCH_SIZE]
            
            print(f"[INFO] Embedding batch {i // BATCH_SIZE + 1} ({len(batch_chunks)} items)...")
            try:
                vectors = embed_text_chunks(batch_chunks)
                import json
                is_pg = session.bind and session.bind.dialect.name == "postgresql"
                for func, vector in zip(batch_funcs, vectors):
                    db_emb = FunctionEmbedding(
                        function_id=func.id,
                        embedding=vector if is_pg else json.dumps(vector)
                    )
                    session.add(db_emb)
                r_prog = session.query(Repo).filter(Repo.id == repo_id).first()
                if r_prog:
                    r_prog.last_progress_at = datetime.now(UTC)
                session.commit()
                embeddings_created += len(vectors)
                time.sleep(2.0)
            except Exception as e:
                session.rollback()
                print(f"[ERROR] Failed to embed batch starting at index {i}: {e}")
                raise e

        total_time = time.time() - start_time
        return {
            "status": "success",
            "functions_processed": len(functions_to_embed),
            "embeddings_created": embeddings_created,
            "failed_count": failed_count,
            "time_taken_seconds": round(total_time, 2)
        }

    except Exception as e:
        from datetime import datetime, UTC
        session.rollback()
        r = session.query(Repo).filter(Repo.id == repo_id).first()
        if r:
            r.status = "failed"
            r.failed_stage = "embedding"
            r.failed_at = datetime.now(UTC)
            r.error_message = str(e)
            session.commit()
        raise e
    finally:
        session.close()

def semantic_search(repo_id: int, query: str, top_n: int = 5) -> list[dict]:
    session = get_session()
    try:
        repo = session.query(Repo).filter(Repo.id == repo_id).first()
        if not repo:
            raise ValueError(f"Repository with ID {repo_id} not found in database.")
        
        func_count = session.query(Function).filter(Function.repo_id == repo_id).count()
        emb_count = session.query(FunctionEmbedding).join(Function, Function.id == FunctionEmbedding.function_id).filter(Function.repo_id == repo_id).count()
        
        if repo.status != "ready" or (func_count > 0 and emb_count == 0):
            err_msg = f"Repository embeddings are not ready: status='{repo.status}', failed_stage='{repo.failed_stage}', embeddings={emb_count}/{func_count}, error='{repo.error_message}'"
            raise RuntimeError(err_msg)
            
        # Embed the query
        query_vector = embed_text_chunks([query])[0]
        
        is_pg = session.bind and session.bind.dialect.name == "postgresql"
        if is_pg:
            # Cosine distance operator from pgvector
            distance = FunctionEmbedding.embedding.cosine_distance(query_vector)
            
            results = (
                session.query(Function, distance.label("distance"))
                .join(FunctionEmbedding, Function.id == FunctionEmbedding.function_id)
                .filter(Function.repo_id == repo_id)
                .order_by("distance")
                .limit(top_n)
                .all()
            )
            
            output = []
            for func, dist in results:
                score = 1.0 - float(dist)  # Cosine similarity
                output.append({
                    "function_id": func.id,
                    "file_path": func.file_path,
                    "name": func.name,
                    "class_name": func.class_name,
                    "start_line": func.start_line,
                    "end_line": func.end_line,
                    "kind": func.kind,
                    "similarity_score": round(score, 4)
                })
            return output
        else:
            # Python cosine similarity fallback for SQLite
            import json, numpy as np
            q_vec = np.array(query_vector)
            q_norm = np.linalg.norm(q_vec)
            
            rows = (
                session.query(Function, FunctionEmbedding.embedding)
                .join(FunctionEmbedding, Function.id == FunctionEmbedding.function_id)
                .filter(Function.repo_id == repo_id)
                .all()
            )
            
            scored = []
            for func, emb_str in rows:
                if isinstance(emb_str, str):
                    vec = np.array(json.loads(emb_str))
                else:
                    vec = np.array(emb_str)
                v_norm = np.linalg.norm(vec)
                sim = float(np.dot(q_vec, vec) / (q_norm * v_norm)) if (q_norm * v_norm) > 0 else 0.0
                scored.append((func, sim))
                
            scored.sort(key=lambda x: x[1], reverse=True)
            output = []
            for func, score in scored[:top_n]:
                output.append({
                    "function_id": func.id,
                    "file_path": func.file_path,
                    "name": func.name,
                    "class_name": func.class_name,
                    "start_line": func.start_line,
                    "end_line": func.end_line,
                    "kind": func.kind,
                    "similarity_score": round(score, 4)
                })
            return output
    finally:
        session.close()
