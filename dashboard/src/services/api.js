/**
 * API service layer — all backend communication goes through here.
 * The frontend NEVER implements retry policy logic.
 * Every decision comes from the backend.
 */

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001'

async function request(path, options = {}) {
  const url = `${BASE}${path}`
  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...options.headers },
      ...options,
    })
    const data = await res.json().catch(() => null)
    if (!res.ok) {
      throw new ApiError(res.status, data?.detail || `HTTP ${res.status}`, data)
    }
    return data
  } catch (err) {
    if (err instanceof ApiError) throw err
    throw new ApiError(0, err.message || 'Network error', null)
  }
}

export class ApiError extends Error {
  constructor(status, message, data) {
    super(message)
    this.status = status
    this.data = data
  }
}

export const api = {
  /** GET /health */
  health: () => request('/health'),

  /** GET /api/v1/metrics */
  metrics: () => request('/api/v1/metrics'),

  /** POST /api/v1/webhook/payment-failed */
  ingestWebhook: (payload, params = {}) => {
    const qs = new URLSearchParams()
    if (params.salary_credit_day) qs.set('salary_credit_day', params.salary_credit_day)
    if (params.historical_surge_hour_ist) qs.set('historical_surge_hour_ist', params.historical_surge_hour_ist)
    const query = qs.toString() ? `?${qs}` : ''
    return request(`/api/v1/webhook/payment-failed${query}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  /** GET /api/v1/retries/{transaction_id} */
  getRetryStatus: (txnId) => request(`/api/v1/retries/${encodeURIComponent(txnId)}`),

  /** GET /api/v1/audit/{transaction_id} */
  getAuditTrail: (txnId) => request(`/api/v1/audit/${encodeURIComponent(txnId)}`),
}

/** Benchmark numbers derived from the engine report (synthetic simulation) */
export const BENCHMARK = {
  baseline: {
    total: 1000,
    recovered: 400,
    recoveryRate: 40.0,
    hardDeclinesSkipped: 376,
    belowThresholdSkipped: 70,
    recoveredAmountRupees: 9829343.99,
  },
  engine: {
    total: 1000,
    recovered: 530,
    recoveryRate: 53.0,
    hardDeclinesBlocked: 376,
    belowThresholdBlocked: 70,
    approvedForRetry: 554,
    totalRetryAttempts: 767,
    recoveredAmountRupees: 13312100.82,
    avgAttemptsPerApproved: 1.38,
  },
  delta: {
    recoveredDelta: 130,
    recoveryRateDelta: 13.0,
    amountDeltaRupees: 3482756.83,
  },
}

/** Demo scenarios that call the real backend */
export const DEMO_SCENARIOS = [
  {
    id: 'liquidity',
    label: 'Temporary Liquidity',
    color: '#3b82f6',
    failureCode: 'BANK_RESP_51_NO_FUNDS',
    amountPaise: 50000,
    expected: 'LIQUIDITY_TEMPORARY → APPROVE',
    description: 'Insufficient funds — recoverable after payday',
  },
  {
    id: 'surge',
    label: 'Bank Surge',
    color: '#8b5cf6',
    failureCode: 'NPCI_SURGE_TIMEOUT',
    amountPaise: 100000,
    expected: 'BANK_SURGE_TEMPORARY → APPROVE',
    description: 'NPCI congestion — retry outside surge window',
  },
  {
    id: 'hard_decline',
    label: 'Hard Decline',
    color: '#ef4444',
    failureCode: 'MANDATE_EXPIRED',
    amountPaise: 50000,
    expected: 'HARD_DECLINE → BLOCK',
    description: 'Mandate expired — permanent failure, never retry',
  },
  {
    id: 'below_threshold',
    label: 'Below ₹100',
    color: '#f59e0b',
    failureCode: 'BANK_RESP_51_NO_FUNDS',
    amountPaise: 5000,
    expected: 'MIN_AMOUNT_BLOCK',
    description: 'Amount ₹50 — below ₹100 minimum, not retried',
  },
]
