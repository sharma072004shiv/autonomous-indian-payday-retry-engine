/**
 * RecoveryFunnel
 * ──────────────
 * Visual funnel showing how 1,000 failed payments flow through the engine.
 * Numbers come from BENCHMARK constants (synthetic simulation) and live
 * metrics from GET /api/v1/metrics when available.
 *
 * ⚠️  SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ⚠️
 */

import { BENCHMARK } from '../services/api.js'
import { CheckIcon, XIcon, ShieldIcon } from './Icons.jsx'

const B = BENCHMARK.engine
const TOTAL = B.total

function Bar({ value, total, color, animated = true }) {
  const pct = Math.min(100, Math.round((value / total) * 100))
  return (
    <div className="funnel-bar-track">
      <div className="funnel-bar-fill"
        style={{ width: `${pct}%`, background: color }}
      />
    </div>
  )
}

function FunnelRow({ label, value, total, color, icon, sub, dimmed }) {
  const pct = Math.round((value / total) * 100)
  return (
    <div style={{
      padding: '12px 14px',
      background: dimmed ? 'rgba(255,255,255,0.01)' : 'rgba(255,255,255,0.03)',
      border: `1px solid ${dimmed ? 'rgba(255,255,255,0.05)' : `${color}25`}`,
      borderRadius: 'var(--radius)',
      opacity: dimmed ? 0.6 : 1,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {icon}
          <span style={{ fontSize: 13, fontWeight: 600, color: dimmed ? 'var(--text-muted)' : 'var(--text-secondary)' }}>
            {label}
          </span>
        </div>
        <div style={{ textAlign: 'right' }}>
          <span style={{ fontSize: 18, fontWeight: 800, color }}>{value.toLocaleString()}</span>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 5 }}>({pct}%)</span>
        </div>
      </div>
      <Bar value={value} total={total} color={color} />
      {sub && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 5 }}>{sub}</div>}
    </div>
  )
}

function Arrow({ label }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 14px' }}>
      <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
      <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
        {label}
      </span>
      <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
    </div>
  )
}

export function RecoveryFunnel({ liveMetrics }) {
  // Prefer live DB metrics for what we have, fall back to benchmark constants.
  const totalLive  = liveMetrics?.total_transactions
  const byStatus   = liveMetrics?.by_status || {}
  const byCat      = liveMetrics?.by_failure_category || {}

  // For the funnel we always use the benchmark simulation numbers
  // (the live session won't have 1,000 records unless the CSV ingestion was run).
  const hardBlocked  = B.hardDeclinesBlocked
  const belowBlocked = B.belowThresholdBlocked
  const maxRetryBlk  = B.max_retry_blocked || 0
  const eligible     = TOTAL - hardBlocked - belowBlocked - maxRetryBlk  // 554
  const attempted    = B.totalRetryAttempts // 767 (attempts across up to 3 tries)
  const recovered    = B.recovered          // 530
  const failed       = eligible - recovered  // 24 (failed even after retries)

  return (
    <div className="card">
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>Recovery Funnel</div>
            <span className="section-label label-bench">SYNTHETIC BENCHMARK</span>
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 3 }}>
            1,000 failed payments · seed 42 · ⚠️ not real-world data
          </div>
        </div>
        <div style={{
          textAlign: 'right', fontSize: 11, color: 'var(--text-muted)',
          padding: '6px 10px', background: 'rgba(255,255,255,0.02)',
          borderRadius: 6, border: '1px solid var(--border)',
        }}>
          <div style={{ color: 'var(--blue)', fontWeight: 700, fontSize: 18 }}>53%</div>
          <div>Recovery</div>
        </div>
      </div>

      <div style={{ height: 1, background: 'var(--border)', margin: '14px 0' }} />

      {/* Funnel rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>

        <FunnelRow
          label="Failed Payments Ingested"
          value={TOTAL}
          total={TOTAL}
          color="#94a3b8"
          icon={<div style={{ width: 8, height: 8, borderRadius: '50%', background: '#94a3b8' }} />}
          sub="All recurring payment failures entering the engine"
        />

        <Arrow label="guardrail evaluation ↓" />

        {/* Blocked section */}
        <div style={{ display: 'flex', gap: 8 }}>
          <div style={{ flex: 1 }}>
            <FunnelRow
              label="Hard Declines Blocked"
              value={hardBlocked}
              total={TOTAL}
              color="var(--red)"
              dimmed
              icon={<XIcon size={12} color="var(--red)" />}
              sub="MANDATE_EXPIRED, ACCOUNT_FROZEN…"
            />
          </div>
          <div style={{ flex: 1 }}>
            <FunnelRow
              label="Below ₹100 Blocked"
              value={belowBlocked}
              total={TOTAL}
              color="var(--orange)"
              dimmed
              icon={<XIcon size={12} color="var(--orange)" />}
              sub="Amount below minimum threshold"
            />
          </div>
        </div>

        <Arrow label="eligible for retry ↓" />

        <FunnelRow
          label="Approved for Retry"
          value={eligible}
          total={TOTAL}
          color="var(--blue)"
          icon={<CheckIcon size={12} color="var(--blue)" />}
          sub={`${B.totalRetryAttempts} total attempts across up to 3 tries (avg ${B.avgAttemptsPerApproved}/txn)`}
        />

        <Arrow label="mock executor ↓" />

        <div style={{ display: 'flex', gap: 8 }}>
          <div style={{ flex: 2 }}>
            <FunnelRow
              label="Successfully Recovered"
              value={recovered}
              total={TOTAL}
              color="var(--green)"
              icon={<CheckIcon size={12} color="var(--green)" />}
              sub="Payment recovered via mock executor"
            />
          </div>
          <div style={{ flex: 1 }}>
            <FunnelRow
              label="Failed After Retry"
              value={failed}
              total={TOTAL}
              color="#475569"
              dimmed
              icon={<XIcon size={12} color="#475569" />}
              sub="Exhausted attempts"
            />
          </div>
        </div>
      </div>

      {/* Key insight */}
      <div style={{
        marginTop: 16, padding: '12px 14px',
        background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.15)',
        borderRadius: 'var(--radius-sm)', fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.7,
        display: 'flex', alignItems: 'flex-start', gap: 8,
      }}>
        <ShieldIcon size={14} color="var(--green)" style={{ flexShrink: 0, marginTop: 1 }} />
        <span>
          Recovery is optimized without weakening safety guardrails.{' '}
          Hard declines ({hardBlocked}) and sub-threshold ({belowBlocked}) transactions are always blocked,
          regardless of retry history.
        </span>
      </div>

      {/* Baseline comparison strip */}
      <div style={{ marginTop: 14, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
        {[
          { label: 'Baseline recovered', value: '400', color: '#475569' },
          { label: 'Engine recovered', value: '530', color: 'var(--blue)' },
          { label: 'Extra recoveries', value: '+130', color: 'var(--green)' },
        ].map(c => (
          <div key={c.label} style={{
            textAlign: 'center', padding: '8px',
            background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
          }}>
            <div style={{ fontSize: 16, fontWeight: 800, color: c.color }}>{c.value}</div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>{c.label}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
