# Autonomous Indian PayDay & Mandate Retry Engine

> Razorpay AI Buildathon submission

⚠️ **MOCK ONLY** — This project uses a simulated payment executor and synthetic data only. It never connects to real Razorpay APIs or real banking infrastructure.

---

## Project Purpose

An AI-augmented, fintech-safe autonomous retry engine for failed recurring payment and mandate transactions in India. When a payment fails (insufficient funds, NPCI surge, etc.), the system:

1. **Classifies** the failure using a structured LLM (PydanticAI)
2. **Evaluates** whether a retry is safe using deterministic Python guardrails
3. **Schedules** the retry at the optimal time (after payday, outside surge windows)
4. **Executes** via a mock Razorpay layer (no real payments)
5. **Audits** every decision immutably

---

## Architecture

| Layer | Technology | File |
|---|---|---|
| API Framework | FastAPI | `app/main.py` |
| Database | SQLite + WAL mode | `app/db/` |
| Schemas | Pydantic v2 | `app/models/` |
| LLM Classifier | PydanticAI (mock in tests) | `app/llm/` |
| Timing Predictor | Deterministic Python | `app/services/payday_predictor.py` |
| Policy Engine | Deterministic guardrails | `app/policy/` |
| Scheduler | Asyncio background task | `app/scheduler/` |
| Executor | Mock Razorpay (no real API) | `app/executor/mock_razorpay.py` |
| Audit | Append-only SQLite table | `app/db/repo_audit.py` |
| Ingestion | CSV + Webhook | `app/services/ingestion_service.py` |
| Benchmark | 1,000-record A/B | `benchmark/` |

---

## Trust Boundary

**The LLM is a read-only classifier. It has NO execution authority.**

| The LLM MAY | The LLM MUST NEVER |
|---|---|
| Classify a failure code | Execute payments |
| Return a confidence score | Call Razorpay APIs |
| Provide a rationale string | Modify amounts |
| | Schedule retries |
| | Override policy rules |
| | Access the database |

All retry decisions are made by deterministic Python policy logic (`app/policy/engine.py`).

---

## Failure Categories

| Category | Meaning | Example Codes |
|---|---|---|
| `LIQUIDITY_TEMPORARY` | Insufficient funds; retry after payday | `BANK_RESP_51_NO_FUNDS` |
| `BANK_SURGE_TEMPORARY` | NPCI/bank congestion | `NPCI_SURGE_TIMEOUT` |
| `HARD_DECLINE` | Permanent failure; never retry | `MANDATE_EXPIRED`, `ACCOUNT_FROZEN` |

---

## Policy Guardrails (enforced deterministically)

1. Maximum **3 retries** per transaction
2. Amount **below ₹100** → never retry
3. **HARD_DECLINE** → never retry
4. **Duplicate webhook** → rejected idempotently
5. LLM confidence **< 0.5** → defaults to HARD_DECLINE
6. `LIQUIDITY_TEMPORARY` → retry after predicted salary credit
7. `BANK_SURGE_TEMPORARY` → retry outside known surge windows (9–11 AM, 7–10 PM IST)

---

## Quick Start

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS

# 2. Install all dependencies
pip install -e ".[dev]"

# 3. Copy environment template
copy .env.example .env
# Edit .env and set your LLM API key if using a real LLM
# For testing/demo, set LLM_USE_MOCK=true

# 4. Run the API server
uvicorn app.main:app --reload

# 5. Run all tests
pytest

# 6. Generate synthetic data
python data/generate_data.py

# 7. Run the benchmark
python benchmark/report.py
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/api/v1/webhook/payment-failed` | Ingest a failed payment event |
| GET | `/api/v1/retries/{transaction_id}` | Get retry status |
| GET | `/api/v1/audit/{transaction_id}` | Get full audit trail |
| GET | `/api/v1/metrics` | Aggregate engine metrics |
| GET | `/docs` | Interactive API documentation |

---

## Example Webhook Request

```bash
curl -X POST http://localhost:8000/api/v1/webhook/payment-failed \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "evt-razorpay-20260701-001",
    "transaction_id": "txn-razorpay-20260701-001",
    "failure_code": "BANK_RESP_51_NO_FUNDS",
    "amount_paise": 250000,
    "customer_id": "cust-001",
    "occurred_at": "2026-07-01T10:30:00+00:00"
  }'
```

Expected response (APPROVE for LIQUIDITY_TEMPORARY, ≥ ₹100):
```json
{
  "audit_id": "...",
  "transaction_id": "txn-razorpay-20260701-001",
  "decision": "APPROVE",
  "failure_category": "LIQUIDITY_TEMPORARY",
  "policy_rule_applied": "APPROVE_LIQUIDITY_TEMPORARY",
  "retry_scheduled_at": "2026-07-15T12:00:00+00:00",
  "retry_attempt_number": 1
}
```

---

## How to Run Tests

```bash
# Run full suite
pytest

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run a specific test file
pytest tests/unit/test_policy_guardrails.py -v

# Run integration tests only
pytest tests/integration/ -v
```

---

## How to Generate Synthetic Data

```bash
python data/generate_data.py
```

Produces `data/synthetic_failed_transactions.csv` with 1,000 deterministic records.

⚠️ **SYNTHETIC SIMULATION — NOT REAL-WORLD DATA**

---

## How to Run the Benchmark

```bash
python benchmark/report.py
```

Compares:
- **Strategy A**: Fixed 24-hour retry baseline
- **Strategy B**: Autonomous PayDay Engine (LLM + policy + timing)

Results saved to `benchmark/output/benchmark_<timestamp>.json`.

⚠️ **SYNTHETIC SIMULATION — NOT REAL-WORLD DATA** — Numbers reflect a synthetic dataset with fixed seed=42. They do not represent real payment recovery rates.

---

## Razorpay Execution Is MOCK ONLY

`app/executor/mock_razorpay.py` simulates payment outcomes using a seeded RNG. It:
- **Never** connects to `api.razorpay.com` or any payment gateway
- Uses `Settings.mock_executor_seed` (default 42) for determinism
- Uses `Settings.mock_executor_success_rate` (default 72%) to simulate outcomes
- Is designed to be replaced by a real Razorpay adapter without changing policy logic

---

## Disclaimer

This project is built for the **Razorpay AI Buildathon**. It uses a mock payment executor and synthetic data only. It does not process real payments, connect to live banking infrastructure, or represent a production-ready financial system. All benchmark results are labelled as synthetic simulation results.
