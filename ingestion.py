import os
import re
import stat
import json
import time
import shutil
import subprocess
from datetime import datetime

MAX_PY_FILES = 500
MAX_REPO_SIZE_MB = 300
TEMP_CLONE_DIR = "data/clones"
METADATA_DIR = "data/metadata"

def remove_readonly(func, path, excinfo):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as e:
        raise e

def safe_rmtree(path, max_retries=5, delay=0.2):
    if not os.path.exists(path):
        return
    for i in range(max_retries):
        try:
            shutil.rmtree(path, onerror=remove_readonly)
            return
        except Exception as e:
            if i == max_retries - 1:
                raise e
            time.sleep(delay)

def parse_github_url(url: str) -> tuple[str, str]:
    url = url.strip().rstrip("/")
    pattern = r"(?:https?://github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?$"
    match = re.match(pattern, url)
    if not match:
        raise ValueError(f"Invalid GitHub URL format: '{url}'. Please provide a valid URL (e.g., https://github.com/owner/repo).")
    owner = match.group(1)
    repo_name = match.group(2)
    return owner, repo_name

def clone_repo(repo_url: str, dest_dir: str) -> None:
    os.makedirs(os.path.dirname(dest_dir), exist_ok=True)
    if os.path.exists(dest_dir):
        safe_rmtree(dest_dir)
    
    cmd = ['git', 'clone', '--depth', '1', repo_url, dest_dir]
    env = os.environ.copy()
    env['GIT_TERMINAL_PROMPT'] = '0'
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore',
        env=env
    )
    
    if result.returncode != 0:
        stderr = result.stderr or ''
        if any(term in stderr for term in ('Repository not found', 'Authentication failed', 'terminal prompts disabled', 'Permission denied')):
            raise ValueError(f"Repository not found or is private (authentication required). Git error: {stderr.strip()}")
        if any(term in stderr for term in ('Could not resolve host', 'Connection timed out', 'Failed to connect')):
            raise ConnectionError(f"Network error: Could not connect to GitHub. Git error: {stderr.strip()}")
        raise RuntimeError(f"Git clone failed with exit code {result.returncode}. Stderr: {stderr.strip()}")

def get_dir_size_bytes(directory: str) -> int:
    total_size = 0
    for dirpath, _, filenames in os.walk(directory):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.exists(fp):
                continue
            try:
                total_size += os.path.getsize(fp)
            except OSError:
                pass
    return total_size

def count_file_lines(file_path: str) -> int:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0

def ingest_repository(repo_url: str) -> dict:
    owner, repo_name = parse_github_url(repo_url)
    clone_path = os.path.join(TEMP_CLONE_DIR, repo_name)
    clone_repo(repo_url, clone_path)
    
    repo_size_bytes = get_dir_size_bytes(clone_path)
    repo_size_mb = repo_size_bytes / 1048576
    
    if repo_size_mb > MAX_REPO_SIZE_MB:
        safe_rmtree(clone_path)
        raise ValueError(f"Repository size ({repo_size_mb:.2f} MB) exceeds the limit of {MAX_REPO_SIZE_MB} MB.")
    
    source_files = []
    excluded_files = []
    PRUNED_DIR_NAMES = {'__pycache__', 'env', '.venv', 'venv'}
    
    for dirpath, dirnames, filenames in os.walk(clone_path):
        # Pruning directories in-place (must modify dirnames)
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d.lower() not in PRUNED_DIR_NAMES]
        
        for filename in filenames:
            if not filename.endswith('.py'):
                continue
            
            abs_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(abs_path, clone_path).replace(os.sep, '/')
            
            try:
                file_size = os.path.getsize(abs_path)
            except OSError:
                file_size = 0
                
            line_count = count_file_lines(abs_path)
            
            file_record = {
                "absolute_path": abs_path.replace(os.sep, '/'),
                "relative_path": rel_path,
                "file_size": file_size,
                "line_count": line_count
            }
            
            path_parts = rel_path.lower().split('/')
            # Check if any parent directory is a test directory (excluding the file itself)
            is_test_dir = any(part in ('test', 'tests') for part in path_parts[:-1])
            is_test_file = filename.startswith('test_') or filename.endswith('_test.py')
            
            if is_test_dir or is_test_file:
                file_record['reason'] = 'test'
                excluded_files.append(file_record)
            else:
                source_files.append(file_record)
                
    if len(source_files) > MAX_PY_FILES:
        safe_rmtree(clone_path)
        raise ValueError(f"Repository contains {len(source_files)} source Python files, which exceeds the limit of {MAX_PY_FILES} files.")
        
    from datetime import UTC
    metadata = {
        "repo_url": repo_url,
        "repo_name": repo_name,
        "clone_path": clone_path.replace(os.sep, '/'),
        "status": "success",
        "error_message": None,
        "timestamp": datetime.now(UTC).isoformat().replace('+00:00', 'Z'),
        "total_size_bytes": repo_size_bytes,
        "source_files": source_files,
        "excluded_files": excluded_files
    }
    
    os.makedirs(METADATA_DIR, exist_ok=True)
    metadata_file_path = os.path.join(METADATA_DIR, f"{repo_name}.json")
    
    with open(metadata_file_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
        
    return metadata
