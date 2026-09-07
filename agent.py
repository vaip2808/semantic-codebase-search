import os
import json
import time
import re
from groq import Groq

try:
    from db import get_session, Repo, Function, CallEdge
except ImportError:
    from sementic_cb_search.db import get_session, Repo, Function, CallEdge

SYSTEM_INSTRUCTION = """
You are a highly precise semantic codebase search agent.
Your goal is to answer natural-language questions about a specific code repository.

Follow these strict guidelines:
- **Always Start with `semantic_search`**: You must call `semantic_search` in Turn 1. Never call other tools (like `get_callers`) or guess/fabricate function IDs in Turn 1.
- **Synthesis Pacing & Stopping Discipline**: Once you have identified the target function(s) and their immediate callers/callees/implementation code, STOP calling tools and synthesize your final answer immediately. Do not repeat a `semantic_search` or `get_file` call with only minor variations (different punctuation, trailing parentheses like `foo()` vs `foo(`, or different `top_k`) if a previous call already returned relevant results — treat that as sufficient and move directly to answering.
- **Tool Budget Cue**: You have a maximum budget of 10 tool calls, but you should aim to reach your final synthesized answer within 3 to 5 tool calls for most questions. Do not continue exploring once you have sufficient context to answer.
- **Minimize Source Code Fetching Range**: When calling `get_file`, only retrieve the specific lines you need to see (e.g. 10 to 40 lines of code). Avoid fetching large ranges or whole files, as it consumes too many tokens and triggers API rate limits. Locate target locations using `semantic_search` or graph queries first.
- **Grounded Answers**: Base all claims, descriptions, and answers strictly on the code returned by the `get_file` tool or facts from the other tools. Do NOT make assumptions, guess, or fabricate behavior.
- **Trace the Code**: If a question asks "how X works" or about a flow, don't just rely on the first semantic search result. Call `get_callers`/`get_callees` to trace the actual call path across files, then read the target functions using `get_file` to understand the flow.
- **Citations**: You MUST cite the file name and exact line numbers (e.g., `src/main.py:L10-L25`) for every claim you make about where code is implemented or how it behaves.
- **Not Found Handling**: If you cannot locate the relevant implementation using semantic search, or if the similarity scores are extremely low, or if the call path is untraceable, state clearly that you could not confidently find or trace the behavior. Do not force an answer.
- **No Nested Tool Calls**: Never pass a tool call as an argument to another tool call in the same turn.
- **No Hallucinations**: Never fabricate code, comments, file paths, or line numbers.
"""

def semantic_search(query: str, repo_id: int, top_k: int = 5) -> list[dict]:
    """Find functions in the repository that are semantically similar to the query.
    
    Args:
        query: The natural language search query.
        repo_id: The ID of the repository to search.
        top_k: The maximum number of results to return (default 5).
    """
    try:
        import embeddings
    except ImportError:
        from sementic_cb_search import embeddings
    return embeddings.semantic_search(repo_id, query, top_k)

def get_callers(function_id: int, **kwargs) -> list[dict]:
    """Find all functions that call the specified function in the static call graph.
    
    Args:
        function_id: The database ID of the callee function.
    """
    session = get_session()
    try:
        results = (
            session.query(Function, CallEdge.call_line)
            .join(CallEdge, Function.id == CallEdge.caller_function_id)
            .filter(CallEdge.callee_function_id == function_id)
            .all()
        )
        return [
            {
                "function_id": f.id,
                "file_path": f.file_path,
                "name": f.name,
                "class_name": f.class_name,
                "start_line": f.start_line,
                "end_line": f.end_line,
                "kind": f.kind,
                "call_line": call_line
            }
            for f, call_line in results
        ]
    finally:
        session.close()

def get_callees(function_id: int, **kwargs) -> list[dict]:
    """Find all functions that are called by the specified function in the static call graph.
    
    Args:
        function_id: The database ID of the caller function.
    """
    session = get_session()
    try:
        results = (
            session.query(Function, CallEdge.call_line)
            .join(CallEdge, Function.id == CallEdge.callee_function_id)
            .filter(CallEdge.caller_function_id == function_id)
            .all()
        )
        return [
            {
                "function_id": f.id,
                "file_path": f.file_path,
                "name": f.name,
                "class_name": f.class_name,
                "start_line": f.start_line,
                "end_line": f.end_line,
                "kind": f.kind,
                "call_line": call_line
            }
            for f, call_line in results
        ]
    finally:
        session.close()

def get_file(file_path: str, start_line: int, end_line: int, repo_id: int, **kwargs) -> dict:
    """Read the source code lines from a file in the repository.
    
    Args:
        file_path: The relative path of the file in the repository.
        start_line: The starting line number (1-indexed, inclusive).
        end_line: The ending line number (1-indexed, inclusive).
        repo_id: The database ID of the repository.
    """
    session = get_session()
    try:
        repo = session.query(Repo).filter(Repo.id == repo_id).first()
        if not repo:
            return {"error": f"Repository with ID {repo_id} not found."}
        
        abs_path = os.path.join(repo.clone_path, file_path)
        if not os.path.exists(abs_path):
            # Normalization & Fuzzy Resolution: match against indexed repo paths
            normalized = file_path.replace("\\", "/").strip("/")
            matched_path = None
            
            repo_funcs = session.query(Function.file_path).filter(Function.repo_id == repo_id).distinct().all()
            indexed_paths = [f[0] for f in repo_funcs if f[0]]
            
            for ip in indexed_paths:
                norm_ip = ip.replace("\\", "/").strip("/")
                if norm_ip.endswith(normalized) or normalized.endswith(norm_ip) or norm_ip.split("/")[-1] == normalized.split("/")[-1]:
                    matched_path = ip
                    break
            
            if not matched_path:
                for root, dirs, files in os.walk(repo.clone_path):
                    for fn in files:
                        rel = os.path.relpath(os.path.join(root, fn), repo.clone_path).replace("\\", "/")
                        if rel.endswith(normalized) or rel.split("/")[-1] == normalized.split("/")[-1]:
                            matched_path = rel
                            break
                    if matched_path:
                        break
                        
            if matched_path:
                print(f"[PATH RESOLVER] Resolved '{file_path}' -> '{matched_path}'")
                file_path = matched_path
                abs_path = os.path.join(repo.clone_path, file_path)
            else:
                return {"error": f"File {file_path} not found at {abs_path}."}
            
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError as e:
            return {"error": f"Failed to read file: {e}"}

        # Surround with 3 lines of padding if available
        padded_start = max(1, start_line - 3)
        padded_end = min(len(lines), end_line + 3)
        
        code_slice = lines[padded_start - 1 : padded_end]
        code_text = "".join(code_slice)
        
        return {
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "padded_start": padded_start,
            "padded_end": padded_end,
            "code": code_text
        }
    finally:
        session.close()

def run_degraded_semantic_fallback(question: str, repo_id: int, reason: str = "rate_limit") -> dict:
    """Honest, repo-aware, non-LLM fallback when LLM API is rate-limited or unavailable.
    Queries the actual codebase index using semantic_search and presents raw matches."""
    trace = []
    is_tool_error = reason == "tool_schema_validation_error"
    fallback_status = "tool_error_fallback" if is_tool_error else "rate_limited_fallback"
    warning = (
        "[DEGRADED FALLBACK WARNING: The reasoning step hit a tool-validation error. "
        if is_tool_error
        else "[DEGRADED FALLBACK WARNING: The LLM service is temporarily rate-limited or unavailable. "
    )
    try:
        res_search = semantic_search(query=question, repo_id=repo_id, top_k=5)
        trace.append({
            "turn": 1,
            "tool": "semantic_search",
            "args": {"query": question, "repo_id": repo_id, "top_k": 5},
            "result": res_search
        })
    except Exception as e:
        res_search = []
        trace.append({
            "turn": 1,
            "tool": "semantic_search",
            "args": {"query": question, "repo_id": repo_id, "top_k": 5},
            "result": {"error": f"Semantic search failed: {e}"}
        })

    if not res_search or (isinstance(res_search, list) and len(res_search) == 0):
        answer = (
            warning
            + "Attempted non-LLM semantic search fallback, but no matching functions were found in this repository.]\n\n"
            f"**Repository ID:** {repo_id}\n"
            f"**Search Query:** \"{question}\"\n\n"
            "Please retry your request in a few moments when LLM capacity becomes available."
        )
        return {
            "status": fallback_status,
            "grounded": False,
            "has_called_semantic_search": True,
            "answer": answer,
            "trace": trace,
            "turns_used": 1,
            "total_tool_calls": 1
        }

    # Format honest, repo-aware matches
    matches_text = []
    for idx, item in enumerate(res_search, start=1):
        fp = item.get("file_path", "unknown")
        fn = item.get("name", "unknown")
        cls = f" (class `{item.get('class_name')}`)" if item.get("class_name") else ""
        s_line = item.get("start_line", "?")
        e_line = item.get("end_line", "?")
        score = item.get("similarity_score", 0.0)
        kind = item.get("kind", "function")
        matches_text.append(
            f"{idx}. `{fn}`{cls} - `{fp}:L{s_line}-L{e_line}` ({kind}, similarity: {score:.4f})"
        )

    answer = (
        warning
        + "The following are raw semantic search index matches from the codebase without LLM synthesis or call-graph tracing.]\n\n"
        f"**Repository ID:** {repo_id}\n"
        f"**Search Query:** \"{question}\"\n\n"
        "**Top Candidate Functions in Repository:**\n"
        + "\n".join(matches_text)
        + "\n\n*Please retry your question when the LLM service is no longer rate-limited for full multi-turn analysis and code synthesis.*"
    )

    is_grounded = check_is_grounded_v2(answer, repo_id=repo_id, has_called_ss=True)

    return {
        "status": fallback_status,
        "grounded": is_grounded,
        "has_called_semantic_search": True,
        "answer": answer,
        "trace": trace,
        "turns_used": 1,
        "total_tool_calls": 1
    }

def normalize_query_str(q: str) -> str:
    """Strip all punctuation and collapse whitespace for duplicate query matching."""
    return re.sub(r"[^\w\s]", "", str(q).lower()).strip()

def is_duplicate_tool_call(tool_name: str, tool_args: dict, past_calls: list) -> bool:
    """Checks if a proposed tool call is identical or near-identical to an already executed tool call."""
    if tool_name == "semantic_search":
        q_norm = normalize_query_str(tool_args.get("query", ""))
        repo = tool_args.get("repo_id")
        for past_name, past_args in past_calls:
            if past_name == "semantic_search" and past_args.get("repo_id") == repo:
                past_q_norm = normalize_query_str(past_args.get("query", ""))
                if q_norm == past_q_norm:
                    return True
                if len(q_norm) > 4 and len(past_q_norm) > 4:
                    if q_norm in past_q_norm or past_q_norm in q_norm:
                        return True
    elif tool_name in ("get_callers", "get_callees"):
        fid = tool_args.get("function_id")
        for past_name, past_args in past_calls:
            if past_name == tool_name and past_args.get("function_id") == fid:
                return True
    elif tool_name == "get_file":
        fp = str(tool_args.get("file_path", "")).replace("\\", "/").lower()
        s1 = tool_args.get("start_line", 0)
        e1 = tool_args.get("end_line", 0)
        repo = tool_args.get("repo_id")
        for past_name, past_args in past_calls:
            if past_name == "get_file" and past_args.get("repo_id") == repo:
                past_fp = str(past_args.get("file_path", "")).replace("\\", "/").lower()
                if fp == past_fp or fp.endswith(past_fp) or past_fp.endswith(fp):
                    s2 = past_args.get("start_line", 0)
                    e2 = past_args.get("end_line", 0)
                    if s1 == s2 and e1 == e2:
                        return True
                    overlap = max(0, min(e1, e2) - max(s1, s2))
                    len1 = max(1, e1 - s1)
                    if overlap / len1 >= 0.7:
                        return True
    return False

def check_is_grounded_v2(raw_ans: str, repo_id: int, has_called_ss: bool) -> bool:
    if not has_called_ss:
        return False
        
    ans_lower = raw_ans.lower()
    
    # 1. Negative failure phrases override grounding
    if "could not" in ans_lower or "unable to" in ans_lower:
        return False
        
    # 2. Build comprehensive, normalized target set for this repo
    session = get_session()
    file_targets = set()
    try:
        paths = session.query(Function.file_path).filter(Function.repo_id == repo_id).distinct().all()
        for (fp,) in paths:
            if not fp:
                continue
            clean_p = fp.replace("\\", "/").lower()  # e.g. 'src/requests/models.py'
            
            # Full path variants
            file_targets.add(clean_p)                                 # 'src/requests/models.py'
            file_targets.add(clean_p.replace("/", "."))                # 'src.requests.models.py'
            
            # Path without .py extension
            no_ext_path = clean_p[:-3] if clean_p.endswith(".py") else clean_p
            file_targets.add(no_ext_path)                              # 'src/requests/models'
            file_targets.add(no_ext_path.replace("/", "."))            # 'src.requests.models'
            
            # Path stripping leading root prefixes ('src/', 'lib/')
            for prefix in ["src/", "lib/"]:
                if clean_p.startswith(prefix):
                    stripped_p = clean_p[len(prefix):]                 # 'requests/models.py'
                    file_targets.add(stripped_p)
                    file_targets.add(stripped_p.replace("/", "."))     # 'requests.models.py'
                    
                    stripped_no_ext = stripped_p[:-3] if stripped_p.endswith(".py") else stripped_p
                    file_targets.add(stripped_no_ext)                  # 'requests/models'
                    file_targets.add(stripped_no_ext.replace("/", ".")) # 'requests.models'
            
            # Basename variants
            basename = clean_p.split("/")[-1]
            if len(basename) >= 3:
                file_targets.add(basename)                             # 'models.py'
                if basename.endswith(".py"):
                    file_targets.add(basename[:-3])                     # 'models'
    finally:
        session.close()

    # 3. Normalize answer text slashes
    normalized_ans = ans_lower.replace("\\", "/")

    # 4. Target substring match against generated targets
    matched_targets = [t for t in file_targets if len(t) >= 3 and t in normalized_ans]
    if matched_targets:
        return True

    # 5. Scoped Fallback Regex: Must match .py extension AND match an indexed target
    py_matches = re.findall(r"([\w\-/]+\.py)(?::(?:line\s*)?L?\d+)?", normalized_ans, re.IGNORECASE)
    if py_matches:
        for match_path in py_matches:
            match_clean = match_path.lower().replace("\\", "/")
            match_base = match_clean.split("/")[-1]
            if match_clean in file_targets or match_base in file_targets:
                return True

    return False

def get_groq_tools(include_get_file: bool = True) -> list[dict]:
    """Build OpenAI-compatible tool declarations for Groq."""
    declarations = [
        {"type": "function", "function": {"name": "semantic_search", "description": "Find functions in the repository that are semantically similar to the query.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "repo_id": {"type": "integer"}, "top_k": {"type": "integer"}}, "required": ["query", "repo_id"]}}},
        {"type": "function", "function": {"name": "get_callers", "description": "Find all functions that call the specified function in the static call graph.", "parameters": {"type": "object", "properties": {"function_id": {"type": "integer"}}, "required": ["function_id"]}}},
        {"type": "function", "function": {"name": "get_callees", "description": "Find all functions that are called by the specified function in the static call graph.", "parameters": {"type": "object", "properties": {"function_id": {"type": "integer"}}, "required": ["function_id"]}}},
    ]
    if include_get_file:
        declarations.append(
            {"type": "function", "function": {"name": "get_file", "description": "Read source code lines from a repository file.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}, "repo_id": {"type": "integer"}}, "required": ["file_path", "start_line", "end_line", "repo_id"]}}}
        )
    return declarations

def _ask_agent_groq(question: str, repo_id: int, max_turns: int, disable_fallback: bool, model_name: str) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set.")
    client = Groq(api_key=api_key)
    tools_map = {"semantic_search": semantic_search, "get_callers": get_callers, "get_callees": get_callees, "get_file": get_file}
    messages = [{"role": "system", "content": SYSTEM_INSTRUCTION + f"\n\nThe current repository ID is {repo_id}. Use it for all repo_id arguments."}, {"role": "user", "content": question}]
    trace = []
    history = []
    has_called_ss = False
    total_calls = 0
    max_calls = 10
    for turn in range(max_turns):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=get_groq_tools(),
                tool_choice="required" if turn == 0 and not disable_fallback else "auto",
                temperature=0,
            )
        except Exception as exc:
            error_text = str(exc).lower()
            is_schema_error = (
                "tool_use_failed" in error_text
                or ("400" in error_text and "tool" in error_text)
                or "invalid tool call" in error_text
            )
            if is_schema_error:
                print(f"[WARNING] Groq rejected a malformed tool call; using grounded fallback: {exc}")
                fallback = run_degraded_semantic_fallback(question, repo_id, reason="tool_schema_validation_error")
                fallback["provider_error"] = "Groq rejected a tool call because required arguments were invalid or missing."
                fallback["trace"] = trace + fallback.get("trace", [])
                return fallback
            raise
        message = response.choices[0].message
        if not message.tool_calls:
            answer = message.content or ""
            grounded = check_is_grounded_v2(answer, repo_id, has_called_ss)
            if not has_called_ss:
                answer = "[UNGROUNDED ANSWER WARNING: semantic_search was not executed]\n\n" + answer
            return {"status": "success", "grounded": grounded, "has_called_semantic_search": has_called_ss, "answer": answer, "trace": trace, "turns_used": turn + 1, "total_tool_calls": total_calls, "duplicate_guard_triggered": False, "duplicate_guard_count": 0}
        messages.append({"role": "assistant", "content": message.content or "", "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in message.tool_calls]})
        for call in message.tool_calls:
            if total_calls >= max_calls:
                return {"status": "tool_limit_reached", "grounded": False, "has_called_semantic_search": has_called_ss, "answer": "The maximum tool execution budget was reached before a grounded answer was produced.", "trace": trace, "turns_used": turn + 1, "total_tool_calls": total_calls}
            total_calls += 1
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
                if "repo_id" in args: args["repo_id"] = int(args["repo_id"])
                if "function_id" in args: args["function_id"] = int(args["function_id"])
                result = tools_map[name](**args)
                has_called_ss = has_called_ss or name == "semantic_search"
            except Exception as exc:
                result = {"error": str(exc)}
            trace.append({"turn": turn + 1, "tool": name, "args": args if 'args' in locals() else {}, "result": result})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)})
    return {"status": "budget_exhausted", "grounded": False, "has_called_semantic_search": has_called_ss, "answer": "Error: Budget exhausted before agent reached a final answer.", "trace": trace, "turns_used": max_turns, "total_tool_calls": total_calls}

def ask_agent(question: str, repo_id: int, max_turns: int = 10, disable_fallback: bool = False, model_name: str = "openai/gpt-oss-20b") -> dict:
    """Execute the grounded codebase agent using Groq tool calling."""
    return _ask_agent_groq(question, repo_id, max_turns, disable_fallback, model_name)
    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set.")
            
        client = genai.Client(api_key=api_key)

        # Tool lookup registry
        tools_map = {
            "semantic_search": semantic_search,
            "get_callers": get_callers,
            "get_callees": get_callees,
            "get_file": get_file
        }
        
        total_tool_calls_count = 0
        MAX_TOTAL_TOOL_CALLS = 10
        consecutive_missing_files = 0
        has_called_semantic_search = False
        executed_tool_calls_history = []
        duplicate_guard_triggers = 0

        system_instruction_with_repo = (
            SYSTEM_INSTRUCTION.strip()
            + f"\n\nThe current repository ID is {repo_id}. You MUST use this ID ({repo_id}) for all tool calls requiring a repo_id."
        )
        
        contents = [
            types.Content(role="user", parts=[types.Part.from_text(text=question)])
        ]
        trace = []
        
        for turn in range(max_turns):
            if turn > 0:
                print("Sleeping 5 seconds between turns to stay within RPM rate limits...")
                time.sleep(5)
            print(f"[INFO] Gemini Agent Turn {turn + 1}...")
            
            include_get_file = consecutive_missing_files < 2
            if not include_get_file:
                print(f"[RE-GROUNDING GUARD] Omitting get_file from available tools for turn {turn + 1} due to {consecutive_missing_files} consecutive missing file errors.")
            
            gemini_tools = get_gemini_tools(include_get_file=include_get_file)
            
            config = types.GenerateContentConfig(
                system_instruction=system_instruction_with_repo,
                tools=gemini_tools,
                temperature=0.0
            )
            
            # Retry loop for 429 rate limits or transient errors
            max_retries = 8
            resp = None
            for attempt in range(max_retries):
                try:
                    resp = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=config
                    )
                    break
                except Exception as e_api:
                    e_msg = str(e_api).lower()
                    code = getattr(e_api, "code", None)
                    if code in (429, 503) or "429" in e_msg or "503" in e_msg or "unavailable" in e_msg or "resource_exhausted" in e_msg or "quota" in e_msg or "rate limit" in e_msg:
                        # Extract exact retryDelay if provided by Gemini
                        delay_match = re.search(r"retry in ([\d\.]+)s", str(e_api), re.IGNORECASE)
                        if delay_match:
                            sleep_seconds = float(delay_match.group(1)) + 1.5
                        else:
                            sleep_seconds = 8.0 * (attempt + 1)
                        print(f"[WARNING] Gemini API rate limit or transient error ({code}). Retrying in {sleep_seconds:.2f} seconds (attempt {attempt+1}/{max_retries})...")
                        time.sleep(sleep_seconds)
                        continue
                    raise e_api
            
            if resp is None or not resp.candidates:
                raise RuntimeError("Gemini API request failed or rate limit retries exhausted.")
                
            candidate = resp.candidates[0]
            func_calls = [p.function_call for p in candidate.content.parts if p.function_call]
            
            # Turn 1 Fallback Retry: If turn 0 produces no tool call, force required tool choice
            if not func_calls and turn == 0 and not disable_fallback:
                print("[INFO] Turn 1 yielded no tool calls. Triggering fallback retry with required tool mode...")
                fallback_config = types.GenerateContentConfig(
                    system_instruction=system_instruction_with_repo,
                    tools=gemini_tools,
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(mode="ANY")
                    ),
                    temperature=0.0
                )
                try:
                    resp_fb = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=fallback_config
                    )
                    if resp_fb.candidates:
                        candidate = resp_fb.candidates[0]
                        func_calls = [p.function_call for p in candidate.content.parts if p.function_call]
                except Exception as e_fb:
                    print(f"[WARNING] Fallback required tool call attempt failed: {e_fb}")
            
            if not func_calls:
                # No tool calls, evaluate grounding status
                raw_ans = resp.text or ""
                
                is_grounded = check_is_grounded_v2(raw_ans, repo_id=repo_id, has_called_ss=has_called_semantic_search)
                
                status = "success"
                if total_tool_calls_count >= MAX_TOTAL_TOOL_CALLS and not is_grounded:
                    status = "tool_limit_reached"
                
                final_ans = raw_ans
                if not has_called_semantic_search:
                    final_ans = "[UNGROUNDED ANSWER WARNING: This response was generated without running semantic_search on the codebase index]\n\n" + raw_ans
                
                return {
                    "status": status,
                    "grounded": is_grounded,
                    "has_called_semantic_search": has_called_semantic_search,
                    "answer": final_ans,
                    "trace": trace,
                    "turns_used": turn + 1,
                    "total_tool_calls": total_tool_calls_count,
                    "duplicate_guard_triggered": duplicate_guard_triggers > 0,
                    "duplicate_guard_count": duplicate_guard_triggers
                }
            
            # Check total tool calls cap
            if total_tool_calls_count + len(func_calls) > MAX_TOTAL_TOOL_CALLS:
                allowed_calls = MAX_TOTAL_TOOL_CALLS - total_tool_calls_count
                if allowed_calls <= 0:
                    print(f"[WARNING] Hard cap of {MAX_TOTAL_TOOL_CALLS} total tool calls reached. Halting tool loop.")
                    return {
                        "status": "tool_limit_reached",
                        "grounded": False,
                        "has_called_semantic_search": has_called_semantic_search,
                        "answer": (
                            f"The maximum tool execution budget ({MAX_TOTAL_TOOL_CALLS} tool calls) was reached while attempting to trace this codebase. "
                            "The answer could not be fully grounded in verified code. Please refine your query."
                        ),
                        "trace": trace,
                        "turns_used": turn + 1,
                        "total_tool_calls": total_tool_calls_count,
                        "duplicate_guard_triggered": duplicate_guard_triggers > 0,
                        "duplicate_guard_count": duplicate_guard_triggers
                    }
                func_calls = func_calls[:allowed_calls]

            # Append model candidate response with tool calls to conversation contents
            contents.append(candidate.content)
            
            # Execute tool calls and prepare response parts
            tool_parts = []
            for fc in func_calls:
                total_tool_calls_count += 1
                tool_name = fc.name
                tool_args = dict(fc.args) if fc.args else {}
                
                print(f"  Calling tool '{tool_name}' (Call {total_tool_calls_count}/{MAX_TOTAL_TOOL_CALLS}) with args {tool_args}...")
                
                if tool_name == "semantic_search":
                    has_called_semantic_search = True
                    consecutive_missing_files = 0
                
                # Check duplicate call guard
                if is_duplicate_tool_call(tool_name, tool_args, executed_tool_calls_history):
                    duplicate_guard_triggers += 1
                    print(f"[DUPLICATE CALL GUARD] Intercepted duplicate/near-duplicate tool call '{tool_name}' with args {tool_args}.")
                    result = {
                        "warning": (
                            f"[DUPLICATE CALL INTERCEPTED] You have already executed '{tool_name}' with equivalent arguments in this session. "
                            "You have gathered sufficient code and call-graph context from this codebase. STOP calling tools and synthesize your final grounded answer immediately based on the data already retrieved."
                        )
                    }
                elif tool_name == "get_file" and consecutive_missing_files >= 2:
                    print(f"[RE-GROUNDING GUARD] Consecutive file missing errors ({consecutive_missing_files}). Blocking guessed path '{tool_args.get('file_path')}' and forcing semantic_search.")
                    result = {"error": "Path guessing is disabled due to repeated missing file errors. You MUST call semantic_search to locate valid relative file paths."}
                    consecutive_missing_files += 1
                elif tool_name not in tools_map:
                    result = {"error": f"Tool '{tool_name}' not supported."}
                else:
                    executed_tool_calls_history.append((tool_name, dict(tool_args)))
                    try:
                        if "repo_id" in tool_args:
                            tool_args["repo_id"] = int(tool_args["repo_id"])
                        if "function_id" in tool_args:
                            tool_args["function_id"] = int(tool_args["function_id"])
                        if "top_k" in tool_args:
                            tool_args["top_k"] = int(tool_args["top_k"])
                        if "start_line" in tool_args:
                            tool_args["start_line"] = int(tool_args["start_line"])
                        if "end_line" in tool_args:
                            tool_args["end_line"] = int(tool_args["end_line"])
                            
                        result = tools_map[tool_name](**tool_args)
                        
                        if tool_name == "get_file":
                            if isinstance(result, dict) and "error" in result:
                                consecutive_missing_files += 1
                            else:
                                consecutive_missing_files = 0
                    except Exception as e:
                        result = {"error": f"Tool execution failed: {e}"}
                
                # Record trace entry
                trace.append({
                    "turn": turn + 1,
                    "tool": tool_name,
                    "args": tool_args,
                    "result": result
                })
                
                # Append tool response part
                tool_parts.append(types.Part.from_function_response(name=tool_name, response={"result": result}))
            
            # Append tool outputs to contents (role='user' is universal across all Gemini models)
            contents.append(types.Content(role="user", parts=tool_parts))
            
            # If consecutive missing file threshold hit, inject explicit directive to re-ground
            if consecutive_missing_files >= 2:
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text="[SYSTEM INSTRUCTION] You have received multiple 'file not found' errors by guessing file paths. Stop guessing file paths. You MUST call semantic_search to locate valid relative file paths in this repository.")]
                ))
                
        # Budget exhausted
        raw_ans = "Error: Budget exhausted before agent reached a final answer."
        return {
            "status": "budget_exhausted",
            "grounded": False,
            "has_called_semantic_search": has_called_semantic_search,
            "answer": raw_ans,
            "trace": trace,
            "turns_used": max_turns,
            "total_tool_calls": total_tool_calls_count,
            "duplicate_guard_triggered": duplicate_guard_triggers > 0,
            "duplicate_guard_count": duplicate_guard_triggers
        }
    except Exception as e:
        e_str = str(e).lower()
        if not disable_fallback and ("429" in e_str or "quota" in e_str or "resource_exhausted" in e_str or "rate limit" in e_str or "timeout" in e_str):
            print(f"[WARNING] Gemini API rate limit or error ({e}). Falling back to repo-aware degraded semantic search...")
            return run_degraded_semantic_fallback(question, repo_id)
        raise e
