# Production Model Decision Record

> **SUPERSEDED NOTICE (2026-09-04)**  
> **Status:** SUPERSEDED  
> **Original Recommendation:** `llama-3.3-70b-versatile` / `llama-3.1-8b-instant`  
> **Superseded By:** `openai/gpt-oss-20b` (Verified on Groq Active Endpoint Tier)  
> **Superseding Reason:** Legacy Llama models (`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `llama3-70b-8192`) have been decommissioned on the Groq API endpoint (returning HTTP `404 model_not_found`). A comprehensive 48-run empirical re-benchmark was conducted across active tool-calling models (`openai/gpt-oss-120b` vs `openai/gpt-oss-20b`) on the populated `psf/requests` repository.

---

## 1. Executive Summary & Production Recommendation

Following empirical evaluation on the 8 standardized evaluation queries (3 runs each, 24 runs per candidate, 48 runs total), **`openai/gpt-oss-20b`** is designated as the active production default model for `sementic_cb_search`.

### Core Metrics Summary

| Model Candidate | Grounded Rate | Success Rate | Budget Exhausted Rate | Avg Latency | Relative Cost | Production Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **`openai/gpt-oss-20b`** | **33.3% (8/24)** | **33.3% (8/24)** | **66.7% (16/24)** | **78.17s** | **1.0x (Baseline - Lowest Cost)** | ✅ **SELECTED AS DEFAULT** |
| `openai/gpt-oss-120b` | 12.5% (3/24) | 12.5% (3/24) | 87.5% (21/24) | 94.33s | ~6.0x higher | ❌ Rejected (Budget burn & high latency) |
| `llama-3.3-70b-versatile` | N/A | N/A | N/A | N/A | N/A | ⚠️ **SUPERSEDED (404 Decommissioned)** |

---

## 2. Empirical Benchmark Methodology

- **Repository Under Test:** `psf/requests` (Repo ID `1`, 261 indexed functions, 261 embeddings, 888 call graph edges).
- **Execution Config:** `max_turns = 6`, `MAX_TOTAL_TOOL_CALLS = 10`, `disable_fallback = True`, 15s inter-turn pacing.
- **Evaluation Set:** 8 representative codebase questions across 3 complexity tiers (Single-hop, Multi-hop, Ambiguous/Broad), 3 repeated runs each.

### Detailed Per-Question Benchmark Breakdown

| Question ID & Tier | Query | `openai/gpt-oss-120b` Grounded | `openai/gpt-oss-20b` Grounded | 20b Status Breakdown | Avg Latency (20b) |
| :--- | :--- | :---: | :---: | :--- | :---: |
| **Q1 (Single-hop)** | *"What does the function requests.api.get do?"* | 3/3 (100%) | **3/3 (100%)** | 3 Success, 0 BudgetExhausted | 67.0s |
| **Q2 (Single-hop)** | *"What does CaseInsensitiveDict do in requests.structures?"* | 0/3 (0%) | **3/3 (100%)** | 3 Success, 0 BudgetExhausted | 66.5s |
| **Q3 (Multi-hop)** | *"What functions in requests call or depend on Session.send?"* | 0/3 (0%) | **0/3 (0%)** | 0 Success, 3 BudgetExhausted | 86.2s |
| **Q4 (Multi-hop)** | *"Trace how requests.post flows down to HTTPAdapter.send."* | 0/3 (0%) | **0/3 (0%)** | 0 Success, 3 BudgetExhausted | 84.3s |
| **Q5 (Multi-hop)** | *"Which functions call extract_cookies_to_jar?"* | 0/3 (0%) | **2/3 (66.7%)** | 2 Success, 1 BudgetExhausted | 62.5s |
| **Q6 (Ambiguous)** | *"How does error handling work in this codebase when an HTTP request fails?"* | 0/3 (0%) | **0/3 (0%)** | 0 Success, 3 BudgetExhausted | 88.2s |
| **Q7 (Ambiguous)** | *"How does authentication work in requests?"* | 0/3 (0%) | **0/3 (0%)** | 0 Success, 3 BudgetExhausted | 85.9s |
| **Q8 (Ambiguous)** | *"How does requests handle streaming large file downloads?"* | 0/3 (0%) | **0/3 (0%)** | 0 Success, 3 BudgetExhausted | 84.7s |

---

## 3. Key Findings & Rationale for `openai/gpt-oss-20b`

1. **Nearly 3x Higher Grounded Accuracy:** `gpt-oss-20b` achieved 33.3% grounded accuracy compared to `gpt-oss-120b`'s 12.5%.
2. **Single-Hop Perfection:** `gpt-oss-20b` achieved 100% (6/6) grounded success on single-hop queries (Q1 and Q2), whereas `gpt-oss-120b` failed completely on Q2 (0/3) due to repeatedly fetching overlapping file segments and exhausting its turn budget.
3. **Multi-Hop Capability:** `gpt-oss-20b` was the only model capable of successfully resolving multi-hop call graph queries within budget (2/3 success on Q5 `extract_cookies_to_jar` callers using `get_callers`).
4. **Latency & Token Efficiency:** `gpt-oss-20b` averaged **78.17s** per run (including inter-turn sleeps) vs **94.33s** for `gpt-oss-120b`, generating more concise tool call arguments and avoiding tool call loops.
5. **Cost-Effectiveness:** `gpt-oss-20b` operates at a fraction of the compute cost and token pricing of the 120b variant, making it ideal for multi-turn agentic loops.

---

## 4. Implementation in Codebase

The default parameter in [`agent.py`](file:///c:/Users/Vaibhav%20Pawar/Desktop/sementic_cb_search/agent.py) is explicitly set:
```python
def ask_agent(
    question: str, 
    repo_id: int, 
    max_turns: int = 10, 
    disable_fallback: bool = False, 
    model_name: str = "openai/gpt-oss-20b"
) -> dict:
```
