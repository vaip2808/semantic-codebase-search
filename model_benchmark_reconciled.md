# Reconciled Model Benchmark and Capability Analysis

**Date:** 2026-09-04  
**Project:** `sementic_cb_search`  
**Focus:** Tool-Budget Reconciliation, Full Turn-by-Turn Trace Inspection, and Historical Baseline Comparison.

---

## 1. Tool-Call Budget Reconciliation & Benchmark Configurations

A critical distinction exists between the **cumulative tool-call cap** (`MAX_TOTAL_TOOL_CALLS`) and the **agent loop turn budget** (`max_turns`):

```
┌────────────────────────────────────────────────────────────────────────┐
│ ask_agent Execution Model:                                             │
│                                                                        │
│  for turn in range(max_turns):  <── Outer Turn Loop (max_turns)        │
│      response = call_groq_api()                                        │
│      if response.has_tool_calls:                                       │
│          for tool_call in tool_calls:                                  │
│              total_tool_calls += 1                                     │
│              if total_tool_calls > MAX_TOTAL_TOOL_CALLS:               │
│                  return status="tool_limit_reached"                    │
│              execute_tool()                                            │
│      else:                                                             │
│          return final_synthesized_answer                               │
│                                                                        │
│  return status="budget_exhausted" (Loop exhausted without synthesis)   │
└────────────────────────────────────────────────────────────────────────┘
```

### Configuration Comparison Across Project Milestones

| Benchmark Phase | Target Models | `max_turns` | `MAX_TOTAL_TOOL_CALLS` | Effective Max Tool Calls | Rationale / Context |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Historical Baseline (Check C)** | `llama-3.1-8b-instant`, `llama-3.3-70b-versatile` | **8** | **10** | **8 to 10** | Standard 8-turn budget used in original Check C validation. |
| **Active Candidate Re-Benchmark** | `openai/gpt-oss-120b`, `openai/gpt-oss-20b` | **6** | **10** | **6** | Stricter 6-turn loop used to conserve API rate limits on free-tier endpoints. |
| **Production Runtime Config** | `openai/gpt-oss-20b` | **10** | **10** | **10** | Default parameter in [`agent.py:L335`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/agent.py#L335). |

> [!IMPORTANT]
> **The Effective Budget Impact:** Because the Groq endpoint executes tool calls sequentially (returning exactly 1 tool call per turn), setting `max_turns = 6` in the candidate benchmark created a hard ceiling of **at most 6 tool calls**. For complex multi-hop queries requiring 1 semantic search + 2 call-graph queries + 2 source file reads (= 5 tool calls), a 6-turn limit leaves exactly **1 turn margin** for the model to stop exploring and synthesize its answer.

---

## 2. Direct Comparison Against Historical Baselines

The following table brings together all four models evaluated across the project's standardized 8-question suite on `psf/requests` (Repo ID `1`), comparing the active models directly against the decommissioned historical baselines:

| Metric / Dimension | `llama-3.1-8b-instant` *(Historical Baseline)* | `llama-3.3-70b-versatile` *(Historical Baseline)* | `openai/gpt-oss-20b` *(Active Default)* | `openai/gpt-oss-120b` *(Active Candidate)* |
| :--- | :---: | :---: | :---: | :---: |
| **Groq Endpoint Status** | ❌ Decommissioned (`404`) | ❌ Decommissioned (`404`) | ✅ **Active** | ✅ **Active** |
| **Grounded Accuracy Rate** | 10 / 24 (**41.7%**) | **23 / 24 (95.8%)** | 8 / 24 (**33.3%**) | 3 / 24 (**12.5%**) |
| **Budget Exhausted Rate** | 5 / 24 (20.8% cap hits) | **0 / 24 (0.0% cap hits)** | 16 / 24 (66.7%) | 21 / 24 (87.5%) |
| **Average Tool Calls per Run** | 8.1 | **4.3** | 5.25 | 5.58 |
| **Average Latency per Run** | ~18s | ~9.3s | 78.17s *(w/ 15s sleeps)* | 94.33s *(w/ 15s sleeps)* |
| **Q1 (Single-Hop: `api.get`)** | **3/3 (100%)** | **3/3 (100%)** | **3/3 (100%)** | **3/3 (100%)** |
| **Q2 (Single-Hop: `CaseInsensitiveDict`)** | **3/3 (100%)** | **3/3 (100%)** | **3/3 (100%)** | 0/3 (0%) |
| **Q3 (Multi-Hop: `Session.send` Callers)** | 0/3 (0%) | **3/3 (100%)** | 0/3 (0%) | 0/3 (0%) |
| **Q4 (Multi-Hop: `post` -> `Adapter.send`)** | 1/3 (33.3%) | **3/3 (100%)** | 0/3 (0%) | 0/3 (0%) |
| **Q5 (Multi-Hop: `extract_cookies_to_jar`)** | **3/3 (100%)** | 2/3 (66.7%) | **2/3 (66.7%)** | 0/3 (0%) |
| **Q6 (Broad: Error Handling Flow)** | 0/3 (0%) | **3/3 (100%)** | 0/3 (0%) | 0/3 (0%) |
| **Q7 (Broad: Authentication Flow)** | 0/3 (0%) | **3/3 (100%)** | 0/3 (0%) | 0/3 (0%) |
| **Q8 (Broad: Streaming Large Downloads)** | 0/3 (0%) | **3/3 (100%)** | 0/3 (0%) | 0/3 (0%) |

---

## 3. Full Turn-by-Turn Trace Inspection for Budget-Exhausted Runs

### Trace 1: `openai/gpt-oss-120b` on Q3 (Multi-Hop Call Graph)
- **Prompt:** `"What functions in requests call or depend on Session.send?"`
- **Result:** `status = "budget_exhausted"`, `grounded = False`, `turns = 6`, `latency = 87.60s`

```
Turn 1:
  Action: semantic_search(query='Session.send', repo_id=1, top_k=20)
  Result: Returned 20 functions, including Session.send (ID 187), Session.request (ID 179)

Turn 2:
  Action: get_callers(function_id=187)
  Result: Returned 2 callers: Session.request (line 538), Session.send (line 643)

Turn 3:
  Action: get_callers(function_id=179)
  Result: Returned 7 callers: api.request, api.get, api.options, api.head, api.post, api.put, api.patch, api.delete

Turn 4:
  Action: get_file(file_path='src/requests/sessions.py', start_line=540, end_line=660, repo_id=1)
  Result: Code slice containing Session.send and Session.request implementation

Turn 5:
  Action: get_callers(function_id=179)  <-- [REDUNDANT REPEAT CALL]
  Result: Same 7 callers returned

Turn 6:
  Action: get_file(file_path='src/requests/sessions.py', start_line=740, end_line=830, repo_id=1)
  Result: Code slice containing Session.merge_environment_settings

Loop Termination:
  Turn loop reaches max_turns=6 limit. No text response generated.
  Returned status='budget_exhausted'.
```

**Diagnostic Finding for Trace 1:**  
`gpt-oss-120b` successfully gathered all required caller graph data by Turn 3 (`get_callers(187)` and `get_callers(179)`) and read the implementation on Turn 4. However, on Turn 5 it emitted a redundant `get_callers` call for function 179, and on Turn 6 it dispatched another `get_file` call. It exhausted its 6-turn limit while still gathering data, never executing a synthesis step.

---

### Trace 2: `openai/gpt-oss-20b` on Q6 (Ambiguous / Architectural)
- **Prompt:** `"How does error handling work in this codebase when an HTTP request fails?"`
- **Result:** `status = "budget_exhausted"`, `grounded = False`, `turns = 6`, `latency = 88.67s`

```
Turn 1:
  Action: semantic_search(query='HTTP request error handling', repo_id=1, top_k=5)
  Result: Returned top matches in exceptions.py and models.py (raise_for_status)

Turn 2:
  Action: semantic_search(query='raise_for_status()', repo_id=1, top_k=5)
  Result: Returned raise_for_status in models.py

Turn 3:
  Action: semantic_search(query='raise_for_status(', repo_id=1, top_k=5)
  Result: Returned same matches with trailing parenthesis

Turn 4:
  Action: semantic_search(query='raise_for_status()', repo_id=1, top_k=10)
  Result: Returned 10 matches including HTTPError

Turn 5:
  Action: semantic_search(query='HTTPError', repo_id=1, top_k=5)
  Result: Returned HTTPError definitions in exceptions.py

Turn 6:
  Action: semantic_search(query='raise_for_status()', repo_id=1, top_k=5)
  Result: Returned raise_for_status again

Loop Termination:
  Turn loop reaches max_turns=6 limit. No text response generated.
  Returned status='budget_exhausted'.
```

**Diagnostic Finding for Trace 2:**  
`gpt-oss-20b` entered an **infinite semantic search loop**. Because `semantic_search` returns metadata without the full code body, the model attempted to find "better" search results by tweaking search punctuation (`raise_for_status()`, `raise_for_status(`, `HTTPError`) instead of transitioning to `get_file` to read the code or transitioning to text synthesis.

---

### Trace 3: `openai/gpt-oss-120b` on Q2 (Single-Hop: `CaseInsensitiveDict`)
- **Prompt:** `"What does CaseInsensitiveDict do in requests.structures?"`
- **Result:** `status = "budget_exhausted"`, `grounded = False`, `turns = 6`, `latency = 88.22s`

```
Turn 1:
  Action: semantic_search(query='CaseInsensitiveDict requests.structures', repo_id=1, top_k=10)
  Result: Pointed directly to src/requests/structures.py:L49-L57

Turn 2:
  Action: get_file(file_path='src/requests/structures.py', start_line=1, end_line=200, repo_id=1)
  Result: Returned lines 1 to 200 (contains CaseInsensitiveDict class definition and docstrings)

Turn 3:
  Action: get_file(file_path='src/requests/structures.py', start_line=200, end_line=400, repo_id=1)
  Result: Returned lines 200 to 400 (LookupDict and other structures)

Turn 4:
  Action: get_file(file_path='src/requests/structures.py', start_line=130, end_line=260, repo_id=1)
  Result: Overlapping slice of structures.py

Turn 5:
  Action: get_file(file_path='src/requests/structures.py', start_line=30, end_line=150, repo_id=1)
  Result: Overlapping slice of structures.py

Turn 6:
  Action: get_file(file_path='src/requests/structures.py', start_line=40, end_line=250, repo_id=1)
  Result: Overlapping slice of structures.py

Loop Termination:
  Turn loop reaches max_turns=6 limit. Returned status='budget_exhausted'.
```

**Diagnostic Finding for Trace 3:**  
On Q2, `gpt-oss-120b` received the entire `CaseInsensitiveDict` definition in Turn 2 (`structures.py:L1-200`). Instead of stopping to synthesize the answer (as `gpt-oss-20b` did on Turn 3), `gpt-oss-120b` systematically attempted to read every other line of `structures.py` in overlapping slices, burning through all remaining turns.

---

## 4. Root Cause Analysis: Model Capability Ceiling vs Prompt / Tool-Design Confounds

The investigation reveals two distinct root causes:

### 1. Inherent Model Stopping Judgment (Model Capability Ceiling)
- **The 70B Advantage:** `llama-3.3-70b-versatile` demonstrated exceptional stopping judgment: it averaged **4.3 tool calls**, knowing precisely when it had acquired sufficient context to answer, never exceeding 6 calls even on hard architectural questions.
- **The OSS Model Over-Exploration Tendency:** Both `gpt-oss-120b` and `gpt-oss-20b` exhibit poor self-termination calibration in agentic loops. When given tools, they prioritize continued tool exploration over text synthesis unless explicitly guided to terminate.

### 2. Prompt and Tool-Design Confounds
- **Zero Budget Awareness in Prompt:** The `SYSTEM_INSTRUCTION` in `agent.py` explicitly commands the agent to *"Trace the Code"*, *"Minimize source code fetching"*, and *"Always Start with semantic_search"*, but provides **no budget-awareness instruction** (e.g., *"You have a strict budget. Once you locate the target function and its immediate callers/code, stop calling tools and synthesize your answer immediately"*).
- **Search-Loop Vulnerability:** `semantic_search` results do not include function source code. When `gpt-oss-20b` searches for broad topics, it receives 5-10 function signatures without implementations. Lacking explicit instructions to call `get_file` after searching, it re-queries `semantic_search` with variations of the function name.
- **Turn Cap Mismatch:** Multi-hop queries naturally require 4–6 tool calls. At `max_turns = 6`, zero margin exists for exploratory steps or retries.

---

## 5. Honest Framing & Production Assessment

### Is 33.3% the Best Currently Achievable?
1. **On the Active Groq Endpoint Roster:** Given that Groq has decommissioned all Llama 70B/8B models on the active free tier, **`openai/gpt-oss-20b` (33.3% at 6 turns)** is unequivocally the strongest model currently available on the active endpoint. It outperforms `openai/gpt-oss-120b` (12.5%) by nearly **3x**, operates at **17% lower latency**, and exhibits significantly lower compute costs.
2. **With Turn Budget Headroom (`max_turns = 10`):** In production runtime ([`agent.py:L335`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/agent.py#L335)), `max_turns` is set to **10**, giving `gpt-oss-20b` the headroom needed to complete multi-hop graph traversals.
3. **Closing the Gap to 70B Performance:** To bridge the gap from 33.3% toward the historical 70B standard (95.8%), future enhancements should focus on:
   - Adding a budget-pacing directive to `SYSTEM_INSTRUCTION` instructing the model to synthesize after 2–3 retrieval steps.
   - Adding a loop-detector guard in `agent.py` that blocks repeated `semantic_search` calls with similar queries and forces code inspection.
