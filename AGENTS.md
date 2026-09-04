# AGENTS.md — Autonomous Indian PayDay & Mandate Retry Engine

## Project Overview

An AI-augmented, fintech-safe autonomous retry engine for failed recurring payment and mandate transactions in India. The system classifies payment failures using a structured LLM, applies deterministic Python policy logic to decide whether and when to retry, executes retries through a mock Razorpay layer, and records every decision in an immutable audit trail.

This project is a submission for the **Razorpay AI Buildathon**.

---

## Architecture

| Layer | Technology |
|---|---|
| Language | Python 3.13 |
| API Framework | FastAPI |
| Database | SQLite (WAL mode) |
| Schema Validation | Pydantic v2 |
| LLM Classification | PydanticAI (structured outputs) |
| Policy Engine | Deterministic Python |
| Scheduler | Autonomous background scheduler |
| Payment Executor | Mock Razorpay layer (no real transactions) |
| Audit | Immutable append-only log table |
| Dashboard | React (added after backend is complete) |

---

## Critical Trust Boundary

The LLM is a **read-only classifier**. It receives a failure code and returns a structured failure category. That is its entire role.

### The LLM MUST NEVER:
- Execute or initiate payments
- Call any payment API (real or mock)
- Modify transaction amounts
- Decide retry counts or retry limits
- Override or bypass policy rules
- Write to or modify database records directly
- Schedule retries directly

### The LLM MAY ONLY:
- Classify a failure code into one of the defined failure categories
- Return a confidence score and a human-readable rationale string
- Produce output that is validated by a Pydantic model before use

All retry scheduling, retry execution, and audit logging are performed exclusively by deterministic Python code.

---

## Failure Categories

| Category | Meaning | Example Codes |
|---|---|---|
| `LIQUIDITY_TEMPORARY` | Insufficient funds, likely to recover | `BANK_RESP_51_NO_FUNDS` |
| `BANK_SURGE_TEMPORARY` | Bank/NPCI infrastructure congestion | `NPCI_SURGE_TIMEOUT` |
| `HARD_DECLINE` | Permanent failure, never retry | `MANDATE_EXPIRED`, `ACCOUNT_FROZEN` |

Any failure code that cannot be mapped with sufficient confidence defaults to `HARD_DECLINE` to prevent unsafe retries.

---

## Mandatory Safety Rules

These rules are enforced by the deterministic policy engine and cannot be overridden by the LLM or any external input.

1. **Maximum retries**: No transaction may be retried more than **3 times**.
2. **Minimum amount**: Transactions below **₹100** must not be retried.
3. **Hard declines**: Transactions classified as `HARD_DECLINE` must never be retried.
4. **Idempotency**: Duplicate webhooks must be detected and rejected; the same failure event must never trigger two retry schedules.
5. **Auditability**: Every retry decision — approve, reject, or defer — must produce an audit log entry with a timestamp, reason, and policy rule applied.
6. **Mock-only execution**: The executor layer must never connect to real Razorpay APIs. All payment execution is simulated.
7. **Pydantic validation**: All LLM outputs must pass Pydantic schema validation before the policy engine acts on them. Invalid outputs are treated as `HARD_DECLINE`.
8. **No secrets in source**: API keys, tokens, and credentials must be loaded from environment variables or a `.env` file. They must never appear in committed source code.
9. **Benchmark honesty**: All benchmark results must be clearly labelled as **synthetic simulation results**. No claims about real-world production performance.

---

## Benchmark Design

A deterministic synthetic dataset of **1,000 failed recurring-payment records** is used to compare two strategies:

| Strategy | Description |
|---|---|
| **Baseline (A)** | Fixed 24-hour retry window, retry all non-hard-decline failures once |
| **Autonomous Engine (B)** | AI-classified failure category + policy-optimised retry window |

### Reported Metrics

- Recovery rate (%)
- Total recovered amount (₹)
- Invalid retries prevented (amount below ₹100 threshold)
- Hard-decline retries prevented
- Average retries per recovered transaction
- Retry success rate per failure category
- Audit log completeness (decisions with full trail / total decisions)

All output is labelled: **"SYNTHETIC SIMULATION — NOT REAL-WORLD DATA"**

---

## Engineering Standards

### Code Quality
- **Type hints** on every function signature and class attribute
- **Small, single-responsibility modules** — no file should mix API routing, business logic, and database access
- **No placeholder implementations** — every function must do real work or raise `NotImplementedError` with a clear message
- **Explicit error handling** — no bare `except` clauses; catch specific exceptions and log them

### Module Separation
- Business logic must live in `services/` — not in route handlers
- LLM classification logic must live in `llm/` — not in services or routes
- Policy and guardrail logic must live in `policy/` — isolated and independently testable
- Database access must go through repository functions in `db/` — no raw SQL in routes or services

### Testing
- Unit tests for all policy rules (pytest, deterministic inputs)
- Integration tests for API workflows (FastAPI `TestClient`)
- No test may depend on a live LLM call — use fixtures or mocked structured outputs
- Tests must be deterministic and repeatable with no random seeds

### Dependency Management
- Use `pyproject.toml` with pinned versions
- No unnecessary frameworks or libraries
- Document every non-obvious dependency choice

---

## Agent Workflow for AI Assistants

When an AI agent (Kiro, Copilot, or similar) works on this codebase, it must follow these rules:

1. **Read before writing** — always read an existing file before modifying it.
2. **Respect the trust boundary** — never move payment execution logic into the LLM layer.
3. **Test after each component** — run the relevant test suite after completing each module.
4. **No fake results** — never fabricate benchmark numbers, test outcomes, or implementation claims.
5. **Build order** — complete and test the backend before starting the React dashboard.
6. **Incremental steps** — implement one component at a time; do not scaffold the entire application before any component is working.
7. **Secrets discipline** — never write an actual key, token, or credential value into any source file.
8. **Pydantic-first** — define the data schema before writing the function that produces or consumes it.

---

## Build Order

```
1. Project scaffold         — pyproject.toml, directory structure, .env.example
2. Database layer           — SQLite schema, WAL config, repository functions
3. Pydantic models          — transaction, failure event, audit entry, LLM output
4. Policy engine            — retry rules, guardrails, unit tests
5. LLM classifier           — PydanticAI integration, mock fallback, unit tests
6. Scheduler                — autonomous retry scheduler, idempotency guard
7. Mock executor            — simulated Razorpay call, deterministic outcomes
8. FastAPI routes           — webhook intake, retry status, audit trail endpoints
9. Benchmark runner         — synthetic dataset generator, A/B comparison, metrics report
10. React dashboard         — after all backend tests pass
```

---

## Disclaimer

> This project is built for the Razorpay AI Buildathon. It uses a mock payment executor and synthetic data only. It does not process real payments, connect to live banking infrastructure, or represent a production-ready financial system. All benchmark results are clearly labelled as synthetic simulation results.
