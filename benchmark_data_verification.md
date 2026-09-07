# Benchmark Data Verification & Reality Check

**Date:** 2026-09-05  
**File Verified:** [`benchmark_results_maxturns10_current.json`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/benchmark_results_maxturns10_current.json)  
**Process Status:** Background task `task-618` running; throttled by Groq API Token-Per-Day (TPD) quota.

---

## 1. Direct Inspection of `benchmark_results_maxturns10_current.json`

A direct inspection of the incremental save file [`benchmark_results_maxturns10_current.json`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/benchmark_results_maxturns10_current.json) shows:
- **Total Completed & Saved Runs:** **7 / 48**
- **Completion Status:** **Incomplete (7/48 completed, Run 8/48 currently executing)**
- **Final Summary File ([`benchmark_results_maxturns10_complete.json`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/benchmark_results_maxturns10_complete.json)):** `DOES NOT EXIST YET`

### Raw Row-by-Row Contents of Saved Runs

| # | Model | Question ID & Tier | Run | Status | Grounded | Turns Used | Tool Calls | Latency (s) | Notes |
| :-: | :--- | :--- | :-: | :--- | :---: | :-: | :-: | :-: | :--- |
| 1 | `openai/gpt-oss-20b` | **Q1 [Single-hop]** (`api.get`) | R1 | `success` | **YES** | 5 | 4 | 1977.7s | Completed across quota backoff sleeps |
| 2 | `openai/gpt-oss-20b` | **Q1 [Single-hop]** (`api.get`) | R2 | `success` | **YES** | 5 | 4 | 3056.8s | Completed across quota backoff sleeps |
| 3 | `openai/gpt-oss-20b` | **Q1 [Single-hop]** (`api.get`) | R3 | `success` | **YES** | 7 | 6 | 105.5s | Completed cleanly |
| 4 | `openai/gpt-oss-20b` | **Q2 [Single-hop]** (`CaseInsensitiveDict`) | R1 | `success` | **YES** | 5 | 4 | 69.4s | Completed cleanly |
| 5 | `openai/gpt-oss-20b` | **Q2 [Single-hop]** (`CaseInsensitiveDict`) | R2 | `success` | **YES** | 5 | 4 | 69.5s | Completed cleanly |
| 6 | `openai/gpt-oss-20b` | **Q2 [Single-hop]** (`CaseInsensitiveDict`) | R3 | `success` | **YES** | 5 | 4 | 70.5s | Completed cleanly |
| 7 | `openai/gpt-oss-20b` | **Q3 [Multi-hop]** (`Session.send` callers) | R1 | `budget_exhausted` | **no** | **10** | **10** | 35744.9s | Hit 10-turn cap after overnight backoff |

---

## 2. Real 10-Turn Trace from Completed Run: Q3 R1 on `openai/gpt-oss-20b`

The following is the **actual turn-by-turn trace** extracted directly from [`benchmark_results_maxturns10_current.json`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/benchmark_results_maxturns10_current.json) for Q3 Run 1 at `max_turns = 10`:

```
================================================================================
Model: openai/gpt-oss-20b
Prompt: "What functions in requests call or depend on Session.send?"
Configuration: max_turns=10, MAX_TOTAL_TOOL_CALLS=10, disable_fallback=True
Result: status='budget_exhausted', grounded=False, turns=10, tool_calls=10
================================================================================

Turn 1: Tool 'semantic_search'
        Args: {'query': 'Session.send', 'repo_id': 1, 'top_k': 10}
        Result: Returned 10 function candidates (Session.send ID 187, Session.request ID 179)

Turn 2: Tool 'semantic_search'
        Args: {'query': 'send(', 'repo_id': 1, 'top_k': 20}
        Result: Returned 20 search candidates

Turn 3: Tool 'get_callers'
        Args: {'function_id': 187}
        Result: Returned callers of Session.send (Session.request line 538, Session.send line 643)

Turn 4: Tool 'get_file'
        Args: {'file_path': 'src/requests/sessions.py', 'start_line': 750, 'end_line': 830, 'repo_id': 1}
        Result: Code slice from sessions.py

Turn 5: Tool 'semantic_search'
        Args: {'query': 'Session.send', 'repo_id': 1, 'top_k': 20}
        Result: Repeated search for Session.send

Turn 6: Tool 'get_file'
        Args: {'file_path': 'src/requests/sessions.py', 'start_line': 540, 'end_line': 660, 'repo_id': 1}
        Result: Code slice containing Session.send implementation

------------------- [TURNS 7-10: THE NEW HEADROOM BUDGET] -------------------

Turn 7: Tool 'semantic_search'
        Args: {'query': 'Session.send(', 'repo_id': 1, 'top_k': 20}
        Result: Repeated search with trailing parenthesis

Turn 8: Tool 'semantic_search'
        Args: {'query': 'Session.send(', 'repo_id': 1, 'top_k': 20}
        Result: Exact duplicate of Turn 7

Turn 9: Tool 'semantic_search'
        Args: {'query': 'send(', 'repo_id': 1, 'top_k': 20}
        Result: Duplicate of Turn 2

Turn 10: Tool 'semantic_search'
        Args: {'query': 'Session.send(', 'repo_id': 1, 'top_k': 20}
        Result: Duplicate of Turn 7 / Turn 8

Exit: Hard cap MAX_TOTAL_TOOL_CALLS = 10 reached.
      Loop terminates and returns: "Error: Budget exhausted before agent reached a final answer."
```

### Empirical Insight from Trace
**Granting 4 additional turns (from 6 to 10) did NOT resolve Q3.**  
Instead of using turns 7–10 to synthesize the callers gathered in Turn 3 (`get_callers(187)`), the model spent all 4 extra turns executing duplicate `semantic_search` queries (`Session.send(`, `Session.send(`, `send(`, `Session.send(`) until the hard 10-turn cap halted execution.

---

## 3. Why the 48-Run Suite Has Not Fully Completed: The 200k TPD Quota

The full 48-run suite at `max_turns=10` has only completed 7 runs because of Groq's **free-tier organization quota ceiling**:
- **Organization Limit:** `org_01kzc9dtjke8b82mr21z9gfrpj` has a hard limit of **200,000 Tokens Per Day (TPD)** on `openai/gpt-oss-20b` (and `openai/gpt-oss-120b`).
- **Token Accumulation in Multi-Turn Agent Loops:** In a 10-turn loop, every subsequent turn re-sends the growing conversation history plus tool outputs (typically 1,500 to 4,000 tokens per API call). A single 10-turn run consumes **15,000 to 30,000 tokens**.
- **Quota Exhaustion Evidence:** At Turn 6 of Run 7 and Turn 1 of Run 8, Groq returned:
  ```json
  {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` on tokens per day (TPD): Limit 200000, Used 199903, Requested 2162. Please try again in 14m52.08s."}}
  ```
- **Automated Backoff:** `agent.py`'s 429 handler paused for the required backoff windows (ranging from 77s to 893s), causing single runs to take thousands of seconds of elapsed wall-clock time as tokens trickled through the 24-hour sliding window.

---

## 4. Honest Status Assessment

1. **Does Full 48-Run `max_turns=10` Data Exist?** **NO.** Only 7 of 48 runs have finished and saved. Any claim of a completed 48-run `max_turns=10` dataset was incorrect.
2. **What the 7 Completed Runs Actually Prove:**
   - Single-hop queries (Q1 and Q2) succeed reliably (6/6, 100%) on `openai/gpt-oss-20b` in 5–7 turns.
   - Multi-hop queries (Q3) do not automatically resolve with extra turns; `openai/gpt-oss-20b` enters a duplicate `semantic_search` loop and exhausts all 10 turns.
3. **True Production Model Comparison Basis:**
   - The completed 48-run benchmark executed at `max_turns=6` remains the only complete empirical comparison between `openai/gpt-oss-20b` (33.3%) and `openai/gpt-oss-120b` (12.5%).
   - Re-running all 48 runs at `max_turns=10` on the current free-tier API key requires ~900,000 tokens, which would take 4–5 days to trickle through the 200,000 TPD rolling limit unless an upgraded API key tier is provided.
