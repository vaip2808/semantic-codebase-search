# Stopping Behavior and Loop Mitigation Fix Report

**Date:** 2026-09-05  
**Project:** `sementic_cb_search`  
**Focus:** Stopping Calibration Fix, Synthesis Pacing Guidance, and Code-Level Duplicate-Call Guard.

---

## 1. Executive Summary

Trace analysis from previous benchmarks identified a systematic failure pattern across both `openai/gpt-oss-20b` and `openai/gpt-oss-120b`: models frequently gathered all necessary code and call-graph data within 2–4 turns, but continued making redundant or near-duplicate tool calls (e.g. `Session.send(`, `Session.send()`, repeated `get_callers(179)`, and overlapping file slices) until exhausting their turn budget.

To resolve this issue without relying solely on prompt adherence, a **dual-layer mitigation** was implemented in [`agent.py`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/agent.py):
1. **Prompt-Level Synthesis Pacing:** Added explicit stopping discipline and budget-awareness guidance to `SYSTEM_INSTRUCTION`.
2. **Code-Level Duplicate-Call Guard:** Implemented physical interception in [`agent.py`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/agent.py) that detects identical or near-identical tool calls (query normalization, graph function ID deduplication, and file slice overlap detection) and injects a synthesis directive rather than re-executing the redundant call.

---

## 2. Implementation Details

### 2.1 Prompt-Level Synthesis Pacing in `SYSTEM_INSTRUCTION`
Updated [`agent.py:L16-L18`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/agent.py#L16-L18):
```python
SYSTEM_INSTRUCTION = """
You are a highly precise semantic codebase search agent.
Your goal is to answer natural-language questions about a specific code repository.

Follow these strict guidelines:
- **Always Start with `semantic_search`**: You must call `semantic_search` in Turn 1. Never call other tools (like `get_callers`) or guess/fabricate function IDs in Turn 1.
- **Synthesis Pacing & Stopping Discipline**: Once you have identified the target function(s) and their immediate callers/callees/implementation code, STOP calling tools and synthesize your final answer immediately. Do not repeat a `semantic_search` or `get_file` call with only minor variations (different punctuation, trailing parentheses like `foo()` vs `foo(`, or different `top_k`) if a previous call already returned relevant results — treat that as sufficient and move directly to answering.
- **Tool Budget Cue**: You have a maximum budget of 10 tool calls, but you should aim to reach your final synthesized answer within 3 to 5 tool calls for most questions. Do not continue exploring once you have sufficient context to answer.
...
"""
```

---

### 2.2 Code-Level Duplicate-Call Guard Implementation
Added helper functions [`normalize_query_str`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/agent.py#L249-L251) and [`is_duplicate_tool_call`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/agent.py#L253-L289):

```python
import re

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
```

### 2.3 Interception Action in `ask_agent`
When a duplicate or near-duplicate tool call is detected during the agent turn loop:
1. Physical tool execution against the database or filesystem is bypassed.
2. The agent response records the interception and returns:
   ```json
   {
     "warning": "[DUPLICATE CALL INTERCEPTED] You have already executed 'tool_name' with equivalent arguments in this session. You have gathered sufficient code and call-graph context from this codebase. STOP calling tools and synthesize your final grounded answer immediately based on the data already retrieved."
   }
   ```
3. The interception is recorded in trace metadata: `"duplicate_guard_triggered": True`.

---

## 3. Unit-Test Verification Against Historical Failure Modes

A deterministic unit test suite ([`test_duplicate_guard_unit.py`](file:///C:/Users/Vaibhav%20Pawar/.gemini/antigravity-ide/brain/e92220c5-ed97-4dc7-b239-6faa17b221c3/scratch/test_duplicate_guard_unit.py)) was executed against the exact failure patterns seen in prior traces:

| Failure Pattern Tested | Input Args | Past Execution History | Interception Result | Test Status |
| :--- | :--- | :--- | :---: | :---: |
| **Q3 Search Variant** | `query="Session.send("` | `query="Session.send"` | **INTERCEPTED (True)** | ✅ **PASS** |
| **Q6 Punctuation Variant** | `query="raise_for_status()"` | `query="raise_for_status("` | **INTERCEPTED (True)** | ✅ **PASS** |
| **Q3 Redundant Caller Call** | `get_callers(function_id=179)` | `get_callers(function_id=179)` | **INTERCEPTED (True)** | ✅ **PASS** |
| **Q2 Overlapping Slice** | `get_file(structures.py:L30-150)` | `get_file(structures.py:L1-200)` | **INTERCEPTED (True)** | ✅ **PASS** |
| **Legitimate Different Call** | `get_file(sessions.py:L1-200)` | `get_file(structures.py:L1-200)` | **ALLOWED (False)** | ✅ **PASS** |
| **Legitimate New Function** | `get_callers(function_id=71)` | `get_callers(function_id=179)` | **ALLOWED (False)** | ✅ **PASS** |

---

## 4. Live 12-Run Retest Status & Infrastructure Reality

### Retest Configuration
- **Scope:** 12 runs total (Q3 and Q6 × 3 runs each across `openai/gpt-oss-20b` and `openai/gpt-oss-120b`).
- **Target Suite:** [`retest_stopping_behavior.py`](file:///C:/Users/Vaibhav%20Pawar/.gemini/antigravity-ide/brain/e92220c5-ed97-4dc7-b239-6faa17b221c3/scratch/retest_stopping_behavior.py) running as task-703.

### Free-Tier Token Quota Bottleneck
- **Status:** Task-703 executed Turn 1 (`semantic_search`) and Turn 2 (`get_callers(187)`) on Run 1, but entered a 692-second backoff at Turn 3 because the Groq free-tier organization is currently at **199,814 of its 200,000 Tokens-Per-Day (TPD) ceiling**.
- **Assessment:** The script is actively managing retries via `agent.py`'s built-in 429 handler and will persist results to [`stopping_fix_retest_results.json`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/stopping_fix_retest_results.json) as token chunks clear.

---

## 5. Architectural Assessment: Expected Impact of the Fix

1. **Direct Loop Elimination:** The combination of normalized query matching and function ID deduplication makes it physically impossible for the agent to consume turns on punctuation variations (the Q6 failure mode) or repeated graph queries (the Q3 failure mode).
2. **Forced Synthesis:** When intercepted, the LLM receives an explicit directive in its tool context stating that context is complete and that it must synthesize immediately, preventing turn exhaustion.
3. **Preservation of Legitimate Multi-Hop Exploration:** Legitimate distinct queries (e.g. querying `get_callers` on a different caller ID, or inspecting a different source file) remain uninhibited.
