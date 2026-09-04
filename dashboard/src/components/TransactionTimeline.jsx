/**
 * TransactionTimeline
 * ───────────────────
 * Visual lifecycle timeline for a single transaction audit entry.
 * Data comes entirely from the backend API response — nothing is invented.
 */

import { useState, useEffect } from 'react'
import { CategoryBadge, DecisionBadge, RuleBadge } from './Badge.jsx'
import {
  AlertIcon, CheckCircleIcon, CheckIcon, ClockIcon,
  DatabaseIcon, LoaderIcon, ShieldIcon, XIcon, ZapIcon
} from './Icons.jsx'

function fmtTime(iso) {
  if (!iso) return null
  try {
    return new Date(iso).toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      dateStyle: 'short',
      timeStyle: 'medium',
    })
  } catch { return iso }
}

function fmtRupees(paise) {
  if (paise == null) return null
  return new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', maximumFractionDigits: 2,
  }).format(paise / 100)
}

/** One node in the vertical timeline */
function TimelineNode({ icon, color, label, children, index = 0, active = true }) {
  return (
    <div style={{
      display: 'flex', gap: 14,
      animation: `slide-up 0.3s ease ${index * 0.07}s both`,
      opacity: active ? 1 : 0.4,
    }}>
      {/* Left: dot + connector */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
        <div style={{
          width: 32, height: 32, borderRadius: '50%', flexShrink: 0,
          background: active ? `${color}20` : 'rgba(255,255,255,0.04)',
          border: `2px solid ${active ? color : 'rgba(255,255,255,0.08)'}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: active ? `0 0 12px ${color}30` : 'none',
          animation: active ? 'pop-in 0.35s ease both' : 'none',
        }}>
          {icon}
        </div>
        <div style={{
          width: 2, flex: 1, minHeight: 20,
          background: `linear-gradient(to bottom, ${active ? color : 'rgba(255,255,255,0.06)'}, rgba(255,255,255,0.04))`,
          marginTop: 4,
        }} />
      </div>
      {/* Right: content */}
      <div style={{ flex: 1, paddingBottom: 20 }}>
        <div style={{
          fontSize: 11, fontWeight: 700, color: active ? color : 'var(--text-muted)',
          letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6,
        }}>
          {label}
        </div>
        {children}
      </div>
    </div>
  )
}

/** Small pill */
function Pill({ label, value, color = 'var(--text-secondary)' }) {
  if (!value && value !== 0) return null
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '6px 10px', borderRadius: 6,
      background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)',
      marginBottom: 5, gap: 8,
    }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 500 }}>{label}</span>
      <span style={{ fontSize: 12, color, fontWeight: 600, textAlign: 'right' }}>{value}</span>
    </div>
  )
}

/**
 * Derive which guardrails passed/failed from the backend decision.
 * We NEVER hard-code policy logic here — we read the backend's `policy_rule_applied`
 * and `decision` fields to determine what was evaluated.
 */
function deriveGuardrails(audit) {
  const rule = audit.policy_rule_applied || ''
  const approved = audit.decision === 'APPROVE'
  const amountPaise = audit._amount_paise  // stored when we add to log

  const checks = [
    {
      label: 'Amount ≥ ₹100',
      pass: rule !== 'MIN_AMOUNT_BLOCK',
      hint: rule === 'MIN_AMOUNT_BLOCK' ? 'Blocked — amount below ₹100' : 'Passed',
    },
    {
      label: 'Retry count < 3',
      pass: rule !== 'MAX_RETRIES_BLOCK',
      hint: rule === 'MAX_RETRIES_BLOCK' ? 'Blocked — maximum retries reached' : 'Passed',
    },
    {
      label: 'Not a hard decline',
      pass: rule !== 'HARD_DECLINE_BLOCK',
      hint: rule === 'HARD_DECLINE_BLOCK' ? 'Blocked — permanent failure category' : 'Passed',
    },
    {
      label: 'Not a duplicate event',
      pass: rule !== 'DUPLICATE_EVENT_BLOCK',
      hint: rule === 'DUPLICATE_EVENT_BLOCK' ? 'Blocked — already processed' : 'Passed',
    },
  ]
  return checks
}

export function TransactionTimeline({ audit, onClose }) {
  const [visible, setVisible] = useState(false)
  useEffect(() => { const t = setTimeout(() => setVisible(true), 30); return () => clearTimeout(t) }, [])

  if (!audit) return null

  const approved = audit.decision === 'APPROVE'
  const category = audit.failure_category
  const guardrails = deriveGuardrails(audit)

  // Infer failure code from category (the audit doesn't return failure_code directly,
  // but we stored it on the enriched log entry as _failure_code)
  const failureCode = audit._failure_code || '—'
  const amountDisplay = audit._amount_paise != null
    ? fmtRupees(audit._amount_paise) : null

  const accentColor = approved ? 'var(--green)' : 'var(--red)'

  return (
    <div className="card fade-in" style={{
      borderLeft: `3px solid ${accentColor}`,
      maxHeight: 'calc(100vh - 120px)',
      overflowY: 'auto',
      position: 'sticky',
      top: 80,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>
            Transaction Journey
          </div>
          <div style={{
            fontSize: 20, fontWeight: 800, color: accentColor,
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            {approved ? <CheckCircleIcon size={18} color="var(--green)" /> : <XIcon size={18} color="var(--red)" />}
            {audit.decision}
          </div>
        </div>
        <button className="btn btn-ghost" style={{ padding: '3px 7px', fontSize: 11 }} onClick={onClose}>✕</button>
      </div>

      {/* Trust boundary callout */}
      <div style={{
        padding: '10px 12px', marginBottom: 20, borderRadius: 'var(--radius-sm)',
        background: 'rgba(59,130,246,0.06)', border: '1px solid rgba(59,130,246,0.18)',
        fontSize: 12, lineHeight: 1.7,
      }}>
        <span style={{ color: 'var(--purple)', fontWeight: 700 }}>AI classified</span> the failure.{' '}
        <span style={{ color: accentColor, fontWeight: 700 }}>
          Deterministic policy {approved ? 'approved' : 'blocked'} the retry.
        </span>
      </div>

      {/* Timeline */}
      <div style={{ paddingLeft: 2 }}>

        {/* Stage 1 — Payment Failed */}
        <TimelineNode index={0} color="#ef4444" active={visible}
          icon={<AlertIcon size={14} color="#ef4444" />}
          label="Payment Failed">
          <Pill label="Failure Code" value={failureCode} color="var(--red)" />
          {amountDisplay && <Pill label="Amount" value={amountDisplay} />}
          {audit._occurred_at && <Pill label="Occurred" value={fmtTime(audit._occurred_at)} />}
        </TimelineNode>

        {/* Stage 2 — AI Diagnosis */}
        <TimelineNode index={1} color="var(--purple)" active={visible}
          icon={<ZapIcon size={14} color="var(--purple)" />}
          label="AI Diagnosis">
          <div style={{ marginBottom: 6 }}><CategoryBadge category={category} /></div>
          {audit.llm_confidence != null && (
            <Pill label="Confidence" value={`${Math.round(audit.llm_confidence * 100)}%`} color="var(--purple)" />
          )}
          <div style={{
            fontSize: 11, color: 'var(--text-muted)', marginTop: 6,
            padding: '6px 10px', background: 'rgba(139,92,246,0.06)',
            borderRadius: 6, border: '1px solid rgba(139,92,246,0.15)',
          }}>
            Read-only classification only. LLM has no execution authority.
          </div>
        </TimelineNode>

        {/* Stage 3 — Policy Guardrails */}
        <TimelineNode index={2} color="var(--blue)" active={visible}
          icon={<ShieldIcon size={14} color="var(--blue)" />}
          label="Policy Guardrails">
          {guardrails.map(g => (
            <div key={g.label} className={`eval-row ${g.pass ? 'eval-pass' : 'eval-fail'}`}>
              {g.pass
                ? <CheckIcon size={13} color="var(--green)" />
                : <XIcon size={13} color="var(--red)" />}
              <span style={{ flex: 1 }}>{g.label}</span>
              <span style={{ fontSize: 11, color: g.pass ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
                {g.pass ? '✓' : '✗'}
              </span>
            </div>
          ))}
        </TimelineNode>

        {/* Stage 4 — Decision */}
        <TimelineNode index={3} color={accentColor} active={visible}
          icon={approved
            ? <CheckCircleIcon size={14} color="var(--green)" />
            : <XIcon size={14} color="var(--red)" />}
          label="Retry Decision">
          <div style={{ marginBottom: 8 }}><RuleBadge rule={audit.policy_rule_applied} /></div>
          <div style={{
            fontSize: 12, color: 'var(--text-muted)', padding: '8px 10px',
            background: 'rgba(255,255,255,0.03)', borderRadius: 6,
            borderLeft: `3px solid ${accentColor}`, lineHeight: 1.6,
          }}>
            {audit.reason}
          </div>
        </TimelineNode>

        {/* Stage 5 — Retry Scheduled (only if approved) */}
        <TimelineNode index={4}
          color={approved ? 'var(--cyan)' : 'rgba(255,255,255,0.1)'}
          active={approved && visible}
          icon={<ClockIcon size={14} color={approved ? 'var(--cyan)' : 'var(--text-muted)'} />}
          label="Retry Scheduled">
          {approved ? (
            <>
              <Pill label="Attempt #" value={audit.retry_attempt_number} color="var(--cyan)" />
              <Pill label="Scheduled At" value={fmtTime(audit.retry_scheduled_at)} color="var(--text-secondary)" />
            </>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No retry scheduled — blocked by policy</div>
          )}
        </TimelineNode>

        {/* Stage 6 — Audit Recorded */}
        <TimelineNode index={5} color="var(--green)" active={visible}
          icon={<DatabaseIcon size={14} color="var(--green)" />}
          label="Audit Recorded">
          <Pill label="Audit ID" value={audit.audit_id?.slice(-12) + '…'} color="var(--text-muted)" />
          <Pill label="Decided At" value={fmtTime(audit.decided_at)} />
          <div style={{
            marginTop: 6, fontSize: 11, color: 'var(--green)',
            padding: '5px 10px', background: 'rgba(34,197,94,0.06)',
            borderRadius: 6, border: '1px solid rgba(34,197,94,0.15)',
          }}>
            Immutable audit entry written. Cannot be modified or deleted.
          </div>
        </TimelineNode>

      </div>
    </div>
  )
}
