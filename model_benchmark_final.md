# Final Model Benchmark and Production Decision Report

**Date:** 2026-09-04  
**Project:** `sementic_cb_search`  
**Scope:** Reconciled Model Benchmark, Turn-Budget Analysis (`max_turns=10` vs `max_turns=6`), Turn-by-Turn Failure Traces, and Production Model Recommendation.

---

## 1. Executive Summary & Production Recommendation

Following empirical evaluation on the 8 standardized evaluation queries on `psf/requests` (Repo ID `1`), **`openai/gpt-oss-20b`** is confirmed as the **active production default model** in [`agent.py:L335`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/agent.py#L335).

### Key Production Takeaways
1. **Active Endpoint Reality:** Groq has permanently decommissioned legacy Llama models (`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `llama3-70b-8192`), returning HTTP `404 model_not_found`.
2. **Best Available Active Candidate:** Among the active tool-calling models on Groq's endpoint (`openai/gpt-oss-20b` vs `openai/gpt-oss-120b`), **`openai/gpt-oss-20b`** achieves **nearly 3x higher grounded accuracy** (33.3% vs 12.5%), **17% lower latency** (78.17s vs 94.33s), and operates at significantly lower token compute costs.
3. **Turn Budget & Stopping Behavior:** Raising `max_turns` from 6 to 10 provides headroom for multi-hop graph traversal, but trace analysis reveals that failure to synthesize on complex queries is fundamentally driven by **model stopping calibration** and **prompt pacing** rather than turn budget constraints alone.

---

## 2. Multi-Model Comparative Performance Matrix

The table below presents a unified comparison across all models evaluated throughout the lifecycle of the project against the standardized 8-question benchmark on `psf/requests` (Repo ID `1`):

| Metric / Dimension | `llama-3.1-8b-instant` *(Historical Baseline)* | `llama-3.3-70b-versatile` *(Historical Baseline)* | `openai/gpt-oss-20b` *(Active Default)* | `openai/gpt-oss-120b` *(Active Candidate)* |
| :--- | :---: | :---: | :---: | :---: |
| **Groq API Status** | ❌ Decommissioned (`404`) | ❌ Decommissioned (`404`) | ✅ **Active Production** | ✅ **Active Candidate** |
| **Grounded Accuracy Rate** | 10 / 24 (**41.7%**) | **23 / 24 (95.8%)** | 8 / 24 (**33.3%**) | 3 / 24 (**12.5%**) |
| **Success Rate** | 10 / 24 (41.7%) | **23 / 24 (95.8%)** | 8 / 24 (**33.3%**) | 3 / 24 (12.5%) |
| **Budget Exhausted Rate** | 5 / 24 (20.8% cap hits) | **0 / 24 (0.0% cap hits)** | 16 / 24 (66.7%) | 21 / 24 (87.5%) |
| **Avg Tool Calls per Query** | 8.1 | **4.3** | 5.25 | 5.58 |
| **Avg Latency per Run** | ~18s | ~9.3s | **78.17s** *(w/ 15s sleeps)* | 94.33s *(w/ 15s sleeps)* |
| **Relative Token Cost** | Low | High | **Low (Baseline)** | ~6.0x higher |
| **Q1 (Single-Hop: `api.get`)** | **3/3 (100%)** | **3/3 (100%)** | **3/3 (100%)** | **3/3 (100%)** |
| **Q2 (Single-Hop: `CaseInsensitiveDict`)** | **3/3 (100%)** | **3/3 (100%)** | **3/3 (100%)** | 0/3 (0%) |
| **Q3 (Multi-Hop: `Session.send` Callers)** | 0/3 (0%) | **3/3 (100%)** | 0/3 (0%) | 0/3 (0%) |
| **Q4 (Multi-Hop: `post` -> `Adapter.send`)** | 1/3 (33.3%) | **3/3 (100%)** | 0/3 (0%) | 0/3 (0%) |
| **Q5 (Multi-Hop: `extract_cookies_to_jar`)** | **3/3 (100%)** | 2/3 (66.7%) | **2/3 (66.7%)** | 0/3 (0%) |
| **Q6 (Broad: Error Handling Flow)** | 0/3 (0%) | **3/3 (100%)** | 0/3 (0%) | 0/3 (0%) |
| **Q7 (Broad: Authentication Flow)** | 0/3 (0%) | **3/3 (100%)** | 0/3 (0%) | 0/3 (0%) |
| **Q8 (Broad: Streaming Downloads)** | 0/3 (0%) | **3/3 (100%)** | 0/3 (0%) | 0/3 (0%) |

---

## 3. Tool-Call Budget Analysis: `max_turns=6` vs `max_turns=10`

### 3.1 Budget Mechanics & The Sequential Dispatch Constraint
In [`agent.py`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/agent.py), two separate limiters govern execution:
1. `max_turns`: The maximum iterations of the outer LLM conversation loop.
2. `MAX_TOTAL_TOOL_CALLS = 10`: The cumulative tool call cap across all turns.

Because Groq tool-calling operates sequentially (1 tool call dispatched per assistant message turn), setting `max_turns = 6` imposes an effective limit of **at most 6 tool calls**. Setting `max_turns = 10` enables the agent to utilize up to the full `MAX_TOTAL_TOOL_CALLS = 10` ceiling.

### 3.2 Impact of Turn Headroom by Query Complexity

| Complexity Tier | Required Tool Sequence | Tool Calls Needed | `max_turns=6` Behavior | `max_turns=10` Headroom Effect |
| :--- | :--- | :---: | :--- | :--- |
| **Single-Hop (Q1, Q2)** | `semantic_search` -> `get_file` -> synthesize | **2 to 3** | ✅ 100% Success on `20b` (avg 4.0 turns) | No difference needed; finishes in 3–4 turns. |
| **Multi-Hop (Q3, Q4, Q5)** | `semantic_search` -> `get_callers` -> `get_file` -> synthesize | **4 to 6** | ⚠️ Tight (Q5 succeeded in 3 calls; Q3/Q4 hit turn 6) | Provides 4 additional turns of margin for graph lookups. |
| **Ambiguous / Broad (Q6, Q7, Q8)** | Multiple `semantic_search` + multiple `get_file` | **6+** | ❌ 100% Budget Exhausted | Allows extra turns, but triggers search loops without prompt pacing. |

---

## 4. In-Depth Turn-by-Turn Trace Inspection

### Trace A: `openai/gpt-oss-120b` on Q2 (Single-Hop Over-Exploration)
- **Prompt:** `"What does CaseInsensitiveDict do in requests.structures?"`
- **Result:** `status = "budget_exhausted"`, `grounded = False`, `turns = 6`, `latency = 88.22s`

```
Turn 1: semantic_search(query='CaseInsensitiveDict requests.structures', repo_id=1, top_k=10)
        -> Direct match to src/requests/structures.py:L49-L57
Turn 2: get_file(file_path='src/requests/structures.py', start_line=1, end_line=200, repo_id=1)
        -> Returned lines 1 to 200 (contains the entire CaseInsensitiveDict class!)
Turn 3: get_file(file_path='src/requests/structures.py', start_line=200, end_line=400, repo_id=1)
        -> Reads lines 200-400 (unrelated LookupDict)
Turn 4: get_file(file_path='src/requests/structures.py', start_line=130, end_line=260, repo_id=1)
        -> Overlapping slice
Turn 5: get_file(file_path='src/requests/structures.py', start_line=30, end_line=150, repo_id=1)
        -> Overlapping slice
Turn 6: get_file(file_path='src/requests/structures.py', start_line=40, end_line=250, repo_id=1)
        -> Overlapping slice
Exit:   Loop hits turn cap. Returns "budget_exhausted".
```

**Diagnostic Analysis:**  
`gpt-oss-120b` had the complete class definition in hand on Turn 2. Unlike `gpt-oss-20b` (which stopped and wrote the answer on Turn 3), `120b` continued reading the file in overlapping chunks across turns 3–6. **This is a model calibration failure, not a budget constraint.**

---

### Trace B: `openai/gpt-oss-20b` on Q6 (Semantic-Search Loop)
- **Prompt:** `"How does error handling work in this codebase when an HTTP request fails?"`
- **Result:** `status = "budget_exhausted"`, `grounded = False`, `turns = 6`, `latency = 88.67s`

```
Turn 1: semantic_search(query='HTTP request error handling', repo_id=1, top_k=5)
        -> Returns matches in exceptions.py and models.py (raise_for_status)
Turn 2: semantic_search(query='raise_for_status()', repo_id=1, top_k=5)
        -> Returns raise_for_status in models.py
Turn 3: semantic_search(query='raise_for_status(', repo_id=1, top_k=5)
        -> Repeats search with punctuation variation
Turn 4: semantic_search(query='raise_for_status()', repo_id=1, top_k=10)
        -> Repeats search with top_k=10
Turn 5: semantic_search(query='HTTPError', repo_id=1, top_k=5)
        -> Searches HTTPError in exceptions.py
Turn 6: semantic_search(query='raise_for_status()', repo_id=1, top_k=5)
        -> Repeats search for the 4th time
Exit:   Loop hits turn cap. Returns "budget_exhausted".
```

**Diagnostic Analysis:**  
`gpt-oss-20b` fell into an **infinite semantic search loop**. Because search results contain function metadata without source code bodies, the model repeatedly re-searched with minor string variations instead of calling `get_file` to read the implementation. Expanding `max_turns` to 10 without prompt modifications simply allows the model to continue looping on search terms.

---

### Trace C: `openai/gpt-oss-120b` on Q3 (Call Graph Exploration)
- **Prompt:** `"What functions in requests call or depend on Session.send?"`
- **Result:** `status = "budget_exhausted"`, `grounded = False`, `turns = 6`, `latency = 87.60s`

```
Turn 1: semantic_search(query='Session.send', repo_id=1, top_k=20)
        -> Finds Session.send (ID 187), Session.request (ID 179)
Turn 2: get_callers(function_id=187)
        -> Returns callers: Session.request, Session.send
Turn 3: get_callers(function_id=179)
        -> Returns 7 callers (api.request, api.get, api.post, etc.)
Turn 4: get_file(file_path='src/requests/sessions.py', start_line=540, end_line=660, repo_id=1)
        -> Reads Session.send implementation
Turn 5: get_callers(function_id=179)  <-- [Redundant repeated tool call]
Turn 6: get_file(file_path='src/requests/sessions.py', start_line=740, end_line=830, repo_id=1)
Exit:   Loop hits turn cap. Returns "budget_exhausted".
```

**Diagnostic Analysis:**  
The model gathered all the necessary call-graph edges by Turn 3 (`get_callers(187)` and `get_callers(179)`). On Turn 5, it repeated `get_callers(179)` redundantly, and on Turn 6 read unrelated code. The failure was caused by lack of stopping discipline rather than missing graph data.

---

## 5. Root Cause Synthesis: Model Capability Ceiling vs Prompt / Tool-Design Confounds

| Factor | Description & Empirical Evidence |
| :--- | :--- |
| **Model Stopping Calibration** | `llama-3.3-70b` had superior innate stopping judgment (avg 4.3 tool calls). `gpt-oss-20b` and `120b` tend to over-explore or loop on tools unless explicitly forced to synthesize. |
| **Zero Budget-Awareness in System Prompt** | `SYSTEM_INSTRUCTION` demands extensive code tracing ("Trace the Code", "Minimize source code fetching") but provides **no pacing instructions** (e.g., *"Synthesize after 2–3 retrieval steps"*). |
| **Semantic Search Looping Vulnerability** | `semantic_search` outputs only function names and file locations. When models seek more detail on broad queries, they repeatedly re-query search rather than dispatching `get_file`. |
| **API Infrastructure Limits (TPD)** | Groq's free-tier organization enforces a strict **200,000 Tokens-Per-Day (TPD)** ceiling per model. Multi-turn agent loops (~2,000 tokens/turn) rapidly exhaust daily quotas during intensive batch evaluation. |

---

## 6. Final Production Configuration & Decision

### 1. Selected Production Model: `openai/gpt-oss-20b`
- **Default Parameter in Code:** Configured in [`agent.py:L335`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/agent.py#L335):
  ```python
  def ask_agent(
      question: str, 
      repo_id: int, 
      max_turns: int = 10, 
      disable_fallback: bool = False, 
      model_name: str = "openai/gpt-oss-20b"
  ) -> dict:
  ```
- **Rationale:** Delivers 100% accuracy on single-hop queries, resolves multi-hop graph lookups (Q5), is 16.16s faster than 120b, and operates at ~80% lower token compute cost.

### 2. Honest Fallback Architecture: `run_degraded_semantic_fallback`
- Configured in [`agent.py:L170-L244`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/agent.py#L170-L244).
- If Groq returns `429`, quota exhaustion, or connection timeout, the agent executes an honest, database-backed `semantic_search` query and outputs candidate functions with file paths, line ranges, and similarity scores under a transparent `[DEGRADED FALLBACK WARNING]` banner.
