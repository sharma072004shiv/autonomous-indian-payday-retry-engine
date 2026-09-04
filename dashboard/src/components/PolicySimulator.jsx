/**
 * PolicySimulator
 * ───────────────
 * Sends a scenario to the REAL backend and displays the actual engine decision.
 * NEVER implements policy logic in the frontend.
 * All guardrail evaluations are inferred from the backend response fields.
 */

import { useState } from 'react'
import { api } from '../services/api.js'
import { CategoryBadge, DecisionBadge, RuleBadge } from './Badge.jsx'
import {
  CheckIcon, XIcon, CloseIcon, LoaderIcon,
  SendIcon, PlayIcon, ShieldIcon, ZapIcon
} from './Icons.jsx'
import { toastSuccess, toastError } from './Toast.jsx'

function uid() { return `sim-${Date.now()}-${Math.random().toString(36).slice(2,6)}` }
function fmtTime(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'short', timeStyle: 'short' }) }
  catch { return iso }
}

const QUICK_SCENARIOS = [
  {
    id: 'liquidity',
    label: 'A — Temporary Liquidity',
    color: '#3b82f6',
    failureCode: 'BANK_RESP_51_NO_FUNDS',
    amountPaise: 50000,
    retryCount: 0,
    hint: '₹500 · Liquidity shortfall · Fresh transaction',
  },
  {
    id: 'hard',
    label: 'B — Hard Decline',
    color: '#ef4444',
    failureCode: 'MANDATE_EXPIRED',
    amountPaise: 50000,
    retryCount: 0,
    hint: '₹500 · Mandate expired · Permanent failure',
  },
  {
    id: 'below_min',
    label: 'C — Below Minimum',
    color: '#f59e0b',
    failureCode: 'BANK_RESP_51_NO_FUNDS',
    amountPaise: 5000,
    retryCount: 0,
    hint: '₹50 · Below ₹100 threshold',
  },
  {
    id: 'max_retries',
    label: 'D — Maximum Retries',
    color: '#f97316',
    failureCode: 'BANK_RESP_51_NO_FUNDS',
    amountPaise: 50000,
    retryCount: 3,
    hint: '₹500 · 3 retries already attempted',
  },
]

/** Derive guardrail evaluation rows from the backend's policy_rule_applied */
function deriveEvalRows(result) {
  if (!result) return []
  const rule = result.policy_rule_applied || ''
  const approved = result.decision === 'APPROVE'

  const rows = [
    {
      label: 'Amount ≥ ₹100 (min threshold)',
      pass: rule !== 'MIN_AMOUNT_BLOCK',
      blocker: rule === 'MIN_AMOUNT_BLOCK',
    },
    {
      label: 'Retry count < 3 (max retries)',
      pass: rule !== 'MAX_RETRIES_BLOCK',
      blocker: rule === 'MAX_RETRIES_BLOCK',
    },
    {
      label: 'Not a hard decline',
      pass: rule !== 'HARD_DECLINE_BLOCK',
      blocker: rule === 'HARD_DECLINE_BLOCK',
    },
    {
      label: 'Not a duplicate event',
      pass: rule !== 'DUPLICATE_EVENT_BLOCK',
      blocker: rule === 'DUPLICATE_EVENT_BLOCK',
    },
    {
      label: 'All guardrails — retry approved',
      pass: approved,
      blocker: false,
      isSummary: true,
    },
  ]
  return rows
}

export function PolicySimulator({ onClose }) {
  const [form, setForm] = useState({
    failureCode: 'BANK_RESP_51_NO_FUNDS',
    amountRupees: '500',
    retryCount: '0',
  })
  const [loading, setLoading] = useState(null)  // null | 'quick' | 'custom'
  const [result, setResult] = useState(null)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  async function runScenario(failureCode, amountPaise, retryCountStr) {
    const retryCount = parseInt(retryCountStr, 10) || 0

    // We create a unique transaction per scenario call so we don't hit the idempotency guard.
    // We also embed the retry_count into the transaction_id so each retry-count scenario
    // is a distinct transaction (idempotency is per transaction_id + event_id pair).
    const txnId  = `sim-txn-${failureCode.slice(0,8)}-rc${retryCount}-${Date.now()}`
    const evtId  = uid()

    const payload = {
      event_id:       evtId,
      transaction_id: txnId,
      failure_code:   failureCode,
      amount_paise:   amountPaise,
      customer_id:    'cust-simulator',
      occurred_at:    new Date().toISOString(),
    }

    // If retryCount > 0, we pre-ingest dummy events to increment the counter.
    // This lets the policy engine see the correct retry_count from the DB.
    // Dummy events use the same transaction_id but different event_ids.
    for (let i = 0; i < retryCount; i++) {
      const dummyEvt = uid()
      try {
        await api.ingestWebhook({
          ...payload,
          event_id: dummyEvt,
          // Use a different, non-dummy failure code so these are approvable
          // (we just want to increment retry_count in the DB)
          failure_code: 'BANK_RESP_51_NO_FUNDS',
          amount_paise: 50000, // always above threshold
        })
      } catch (_) { /* ignore — may be blocked for other reasons */ }
    }

    return api.ingestWebhook(payload)
  }

  async function handleQuick(scenario) {
    setLoading(`quick-${scenario.id}`)
    setResult(null)
    try {
      const res = await runScenario(scenario.failureCode, scenario.amountPaise, scenario.retryCount)
      setResult({ ...res, _amountPaise: scenario.amountPaise })
      toastSuccess(`Simulator: ${res.decision} — ${res.policy_rule_applied}`)
    } catch (err) {
      toastError(`Simulator error: ${err.message}`)
    } finally {
      setLoading(null)
    }
  }

  async function handleCustom(e) {
    e.preventDefault()
    setLoading('custom')
    setResult(null)
    try {
      const amountPaise = Math.round(parseFloat(form.amountRupees) * 100)
      const res = await runScenario(form.failureCode, amountPaise, form.retryCount)
      setResult({ ...res, _amountPaise: amountPaise })
      toastSuccess(`Simulator: ${res.decision} — ${res.policy_rule_applied}`)
    } catch (err) {
      toastError(`Simulator error: ${err.message}`)
    } finally {
      setLoading(null)
    }
  }

  const evalRows  = deriveEvalRows(result)
  const approved  = result?.decision === 'APPROVE'
  const accentClr = approved ? 'var(--green)' : 'var(--red)'

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 660 }} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <ShieldIcon size={18} color="var(--blue)" />
              <h3 style={{ fontSize: 16, fontWeight: 700 }}>Policy Simulator</h3>
              <span className="section-label label-live">LIVE BACKEND</span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
              Frontend sends scenario → backend evaluates → actual decision displayed
            </div>
          </div>
          <button className="btn btn-ghost" style={{ padding: '4px 8px' }} onClick={onClose}>
            <CloseIcon size={14} />
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>

          {/* ── Left: inputs ── */}
          <div>
            {/* Quick scenarios */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 10 }}>
                Quick Scenarios
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                {QUICK_SCENARIOS.map(s => {
                  const isRunning = loading === `quick-${s.id}`
                  return (
                    <button key={s.id} className="btn btn-ghost"
                      style={{
                        justifyContent: 'flex-start', gap: 10, padding: '10px 12px',
                        textAlign: 'left', borderColor: `${s.color}30`,
                        background: isRunning ? `${s.color}08` : 'transparent',
                      }}
                      disabled={loading !== null}
                      onClick={() => handleQuick(s)}>
                      {isRunning
                        ? <LoaderIcon size={13} color={s.color} />
                        : <PlayIcon size={13} color={s.color} />}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>{s.label}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>{s.hint}</div>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Divider */}
            <div style={{ height: 1, background: 'var(--border)', margin: '16px 0' }} />

            {/* Custom form */}
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 12 }}>
              Custom Scenario
            </div>
            <form onSubmit={handleCustom}>
              <div className="form-group">
                <label className="form-label">Failure Code</label>
                <select className="form-input" value={form.failureCode} onChange={e => set('failureCode', e.target.value)}>
                  <option>BANK_RESP_51_NO_FUNDS</option>
                  <option>BANK_RESP_65_LIMIT_EXCEEDED</option>
                  <option>NPCI_SURGE_TIMEOUT</option>
                  <option>BANK_UNAVAILABLE</option>
                  <option>MANDATE_EXPIRED</option>
                  <option>ACCOUNT_FROZEN</option>
                  <option>ACCOUNT_CLOSED</option>
                  <option>DO_NOT_HONOUR</option>
                </select>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <div className="form-group">
                  <label className="form-label">Amount (₹)</label>
                  <input className="form-input" type="number" min="0" step="0.01"
                    value={form.amountRupees} onChange={e => set('amountRupees', e.target.value)} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Retry Count</label>
                  <input className="form-input" type="number" min="0" max="3"
                    value={form.retryCount} onChange={e => set('retryCount', e.target.value)} required />
                </div>
              </div>
              <button className="btn btn-primary" type="submit" disabled={loading !== null}
                style={{ width: '100%' }}>
                {loading === 'custom' ? <LoaderIcon size={13} /> : <SendIcon size={13} />}
                {loading === 'custom' ? 'Evaluating…' : 'Evaluate via Backend'}
              </button>
            </form>
          </div>

          {/* ── Right: result ── */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 12 }}>
              Policy Evaluation
            </div>

            {!result && loading === null && (
              <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
                <ShieldIcon size={28} style={{ margin: '0 auto 10px', opacity: 0.25 }} />
                <div style={{ fontSize: 13, fontWeight: 500 }}>Run a scenario to see the engine decision</div>
                <div style={{ fontSize: 12, marginTop: 4 }}>All decisions come from the real backend</div>
              </div>
            )}

            {loading !== null && (
              <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
                <LoaderIcon size={24} color="var(--blue)" style={{ margin: '0 auto 10px' }} />
                <div style={{ fontSize: 13 }}>Calling backend engine…</div>
              </div>
            )}

            {result && loading === null && (
              <div className="slide-up">
                {/* Guardrail evaluation rows */}
                {evalRows.map((row, i) => (
                  <div key={i} className={`eval-row ${row.pass ? 'eval-pass' : 'eval-fail'} ${row.isSummary ? 'mt-3' : ''}`}
                    style={row.isSummary ? { marginTop: 12, fontWeight: 600 } : {}}>
                    {row.pass
                      ? <CheckIcon size={13} color="var(--green)" />
                      : <XIcon size={13} color="var(--red)" />}
                    <span style={{ flex: 1 }}>{row.label}</span>
                    {row.blocker && (
                      <span style={{ fontSize: 10, color: 'var(--red)', fontWeight: 700, background: 'rgba(239,68,68,0.12)', padding: '2px 6px', borderRadius: 4 }}>
                        BLOCKED HERE
                      </span>
                    )}
                  </div>
                ))}

                {/* Final decision */}
                <div style={{
                  marginTop: 16, padding: '16px', borderRadius: 'var(--radius)',
                  background: approved ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
                  border: `1px solid ${approved ? 'rgba(34,197,94,0.25)' : 'rgba(239,68,68,0.25)'}`,
                  textAlign: 'center',
                }}>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>
                    Final Decision
                  </div>
                  <div style={{ fontSize: 22, fontWeight: 800, color: accentClr }}>
                    {approved ? '✓ APPROVE RETRY' : '✗ BLOCK'}
                  </div>
                </div>

                {/* Details */}
                <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '5px 0', borderBottom: '1px solid var(--border)' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Category</span>
                    <CategoryBadge category={result.failure_category} />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '5px 0', borderBottom: '1px solid var(--border)' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Policy Rule</span>
                    <RuleBadge rule={result.policy_rule_applied} />
                  </div>
                  {approved && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '5px 0', borderBottom: '1px solid var(--border)' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Attempt #</span>
                      <span style={{ color: 'var(--cyan)', fontWeight: 600 }}>{result.retry_attempt_number}</span>
                    </div>
                  )}
                  {approved && result.retry_scheduled_at && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '5px 0', borderBottom: '1px solid var(--border)' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Scheduled At</span>
                      <span style={{ color: 'var(--text-secondary)', fontWeight: 500, fontSize: 11 }}>{fmtTime(result.retry_scheduled_at)}</span>
                    </div>
                  )}
                </div>

                {/* Reason */}
                <div style={{
                  marginTop: 10, fontSize: 11, color: 'var(--text-muted)',
                  padding: '8px 10px', background: 'rgba(255,255,255,0.02)',
                  borderRadius: 6, borderLeft: `3px solid ${accentClr}`, lineHeight: 1.6,
                }}>
                  {result.reason}
                </div>

                <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-muted)', textAlign: 'center' }}>
                  Real backend response · No frontend policy logic
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
