import { useState, useEffect, useCallback, useRef } from 'react'
import { api, BENCHMARK, DEMO_SCENARIOS } from './services/api.js'
import { ToastContainer, toastSuccess, toastError } from './components/Toast.jsx'
import { KpiCard } from './components/KpiCard.jsx'
import { DecisionBadge, CategoryBadge, RuleBadge } from './components/Badge.jsx'
import { TransactionTimeline } from './components/TransactionTimeline.jsx'
import { PolicySimulator } from './components/PolicySimulator.jsx'
import { RecoveryFunnel } from './components/RecoveryFunnel.jsx'
import {
  ActivityIcon, CheckCircleIcon, CloseIcon,
  DatabaseIcon, LoaderIcon, PlusIcon, RefreshIcon,
  SendIcon, ShieldIcon, TrendUpIcon, ZapIcon, PlayIcon,
  InfoIcon, ListIcon, CheckIcon
} from './components/Icons.jsx'

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtRupees(paise) {
  const r = typeof paise === 'number' ? paise / 100 : 0
  return new Intl.NumberFormat('en-IN', { style:'currency', currency:'INR', maximumFractionDigits:2 }).format(r)
}
function fmtRupeesFromRupees(r) {
  return new Intl.NumberFormat('en-IN', { style:'currency', currency:'INR', maximumFractionDigits:2 }).format(r)
}
function fmtTime(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString('en-IN', { timeZone:'Asia/Kolkata', dateStyle:'short', timeStyle:'short' }) }
  catch { return iso }
}
function shortId(id) { return id ? id.slice(-8) : '—' }
function uid() { return `evt-${Date.now()}-${Math.random().toString(36).slice(2,7)}` }

// ── Synthetic benchmark comparison chart (CSS bars, no deps) ─────────────────

function RecoveryChart() {
  const bars = [
    { label: 'Fixed 24h Baseline', value: 40, color: '#475569', width: '75.5%' },
    { label: 'Autonomous Engine',  value: 53, color: '#3b82f6', width: '100%' },
  ]
  return (
    <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
      {bars.map(b => (
        <div key={b.label}>
          <div style={{ display:'flex', justifyContent:'space-between', marginBottom:8, fontSize:13 }}>
            <span style={{ color:'var(--text-secondary)', fontWeight:500 }}>{b.label}</span>
            <span style={{ color:'var(--text-primary)', fontWeight:700, fontSize:16 }}>{b.value}%</span>
          </div>
          <div style={{ height:10, background:'rgba(255,255,255,0.06)', borderRadius:5, overflow:'hidden' }}>
            <div style={{ height:'100%', width:b.width, background:b.color, borderRadius:5,
              boxShadow: b.color === '#3b82f6' ? '0 0 12px rgba(59,130,246,0.5)' : 'none',
              transition:'width 1s ease' }} />
          </div>
        </div>
      ))}
      <div style={{ display:'flex', alignItems:'center', gap:8, marginTop:4,
        padding:'10px 14px', background:'rgba(34,197,94,0.08)',
        border:'1px solid rgba(34,197,94,0.2)', borderRadius:'var(--radius-sm)' }}>
        <TrendUpIcon size={15} color="var(--green)" />
        <span style={{ fontSize:13, color:'var(--green)', fontWeight:600 }}>+13 percentage points improvement</span>
        <span style={{ fontSize:11, color:'var(--text-muted)', marginLeft:'auto' }}>SYNTHETIC — NOT REAL-WORLD DATA</span>
      </div>
    </div>
  )
}

// ── Pipeline visual ───────────────────────────────────────────────────────────

function PipelineStage({ label, sub, accent, highlight }) {
  return (
    <div style={{
      flex:1, minWidth:0,
      background: highlight ? `rgba(59,130,246,0.08)` : 'rgba(255,255,255,0.02)',
      border: `1px solid ${highlight ? 'rgba(59,130,246,0.3)' : 'rgba(255,255,255,0.06)'}`,
      borderRadius:'var(--radius)', padding:'12px 14px', textAlign:'center', position:'relative',
    }}>
      {highlight && (
        <div style={{ position:'absolute', top:-1, left:-1, right:-1, bottom:-1,
          borderRadius:'var(--radius)', background:'transparent',
          boxShadow:'0 0 16px rgba(59,130,246,0.2)', pointerEvents:'none' }} />
      )}
      <div style={{ fontSize:12, fontWeight:700, color: accent || 'var(--text-primary)', letterSpacing:'0.03em' }}>{label}</div>
      {sub && <div style={{ fontSize:11, color:'var(--text-muted)', marginTop:3 }}>{sub}</div>}
    </div>
  )
}

function PipelineArrow() {
  return <div style={{ fontSize:16, color:'var(--text-muted)', flexShrink:0 }}>→</div>
}

// ── Guardrail row ─────────────────────────────────────────────────────────────

function GuardrailRow({ text, ok = true }) {
  return (
    <div style={{ display:'flex', alignItems:'center', gap:10, padding:'8px 0',
      borderBottom:'1px solid rgba(255,255,255,0.04)' }}>
      <div style={{ width:20, height:20, borderRadius:'50%', flexShrink:0,
        background: ok ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
        display:'flex', alignItems:'center', justifyContent:'center' }}>
        <CheckIcon size={12} color={ok ? 'var(--green)' : 'var(--red)'} />
      </div>
      <span style={{ fontSize:13, color:'var(--text-secondary)' }}>{text}</span>
    </div>
  )
}

// ── Webhook simulate modal ────────────────────────────────────────────────────

function WebhookModal({ onClose, onSuccess }) {
  const [form, setForm] = useState({
    event_id: uid(),
    transaction_id: `txn-demo-${Date.now()}`,
    failure_code: 'BANK_RESP_51_NO_FUNDS',
    amount_paise: '50000',
    customer_id: 'cust-demo',
    mandate_id: '',
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    try {
      const payload = {
        event_id: form.event_id,
        transaction_id: form.transaction_id,
        failure_code: form.failure_code,
        amount_paise: parseInt(form.amount_paise, 10),
        customer_id: form.customer_id,
        mandate_id: form.mandate_id || undefined,
        occurred_at: new Date().toISOString(),
      }
      const res = await api.ingestWebhook(payload)
      setResult(res)
      toastSuccess('Webhook processed successfully')
      onSuccess?.({ ...res, transaction_id: payload.transaction_id,
        _failure_code: payload.failure_code, _amount_paise: payload.amount_paise,
        _occurred_at: payload.occurred_at })
    } catch (err) { toastError(`Error: ${err.message}`) }
    finally { setLoading(false) }
  }

  if (result) {
    const approved = result.decision === 'APPROVE'
    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal" onClick={e => e.stopPropagation()}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:20 }}>
            <h3 style={{ fontSize:16, fontWeight:700 }}>Engine Decision</h3>
            <button className="btn btn-ghost" style={{ padding:'4px 8px' }} onClick={onClose}><CloseIcon size={14} /></button>
          </div>
          <div style={{
            padding:'20px', borderRadius:'var(--radius)',
            background: approved ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
            border: `1px solid ${approved ? 'rgba(34,197,94,0.25)' : 'rgba(239,68,68,0.25)'}`,
            marginBottom:20, textAlign:'center',
          }}>
            <div style={{ fontSize:11, fontWeight:600, color:'var(--text-muted)', letterSpacing:'0.06em', textTransform:'uppercase', marginBottom:6 }}>Decision</div>
            <div style={{ fontSize:28, fontWeight:800, color: approved ? 'var(--green)' : 'var(--red)' }}>{result.decision}</div>
            <div style={{ fontSize:13, color:'var(--text-secondary)', marginTop:6 }}>{result.failure_category}</div>
          </div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:20 }}>
            {[['Policy Rule', result.policy_rule_applied], ['Attempt #', result.retry_attempt_number],
              ['Scheduled At', fmtTime(result.retry_scheduled_at)], ['Audit ID', shortId(result.audit_id)]
            ].map(([k,v]) => (
              <div key={k} style={{ background:'rgba(255,255,255,0.03)', borderRadius:'var(--radius-sm)', padding:'10px 12px' }}>
                <div style={{ fontSize:11, color:'var(--text-muted)', fontWeight:600, textTransform:'uppercase', letterSpacing:'0.04em', marginBottom:4 }}>{k}</div>
                <div style={{ fontSize:13, fontWeight:500, color:'var(--text-primary)', wordBreak:'break-all' }}>{v || '—'}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize:12, color:'var(--text-muted)', padding:'10px 14px',
            background:'rgba(255,255,255,0.02)', borderRadius:'var(--radius-sm)', borderLeft:'3px solid var(--blue)', marginBottom:20 }}>
            {result.reason}
          </div>
          <div style={{ display:'flex', gap:8 }}>
            <button className="btn btn-primary" style={{ flex:1 }} onClick={() => { setResult(null); setForm(f=>({...f, event_id:uid(), transaction_id:`txn-demo-${Date.now()}`})) }}>
              <PlusIcon size={14} /> New Event
            </button>
            <button className="btn btn-ghost" onClick={onClose}>Close</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:20 }}>
          <h3 style={{ fontSize:16, fontWeight:700 }}>Simulate Failed Payment</h3>
          <button className="btn btn-ghost" style={{ padding:'4px 8px' }} onClick={onClose}><CloseIcon size={14} /></button>
        </div>
        <form onSubmit={submit}>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:0 }}>
            <div className="form-group" style={{ gridColumn:'1/-1' }}>
              <label className="form-label">Event ID</label>
              <input className="form-input" value={form.event_id} onChange={e=>set('event_id',e.target.value)} required />
            </div>
            <div className="form-group" style={{ gridColumn:'1/-1' }}>
              <label className="form-label">Transaction ID</label>
              <input className="form-input" value={form.transaction_id} onChange={e=>set('transaction_id',e.target.value)} required />
            </div>
            <div className="form-group" style={{ gridColumn:'1/-1' }}>
              <label className="form-label">Failure Code</label>
              <select className="form-input" value={form.failure_code} onChange={e=>set('failure_code',e.target.value)}>
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
            <div className="form-group">
              <label className="form-label">Amount (paise)</label>
              <input className="form-input" type="number" value={form.amount_paise} onChange={e=>set('amount_paise',e.target.value)} required min="0" />
              <span style={{ fontSize:11, color:'var(--text-muted)' }}>₹{(parseInt(form.amount_paise)||0)/100}</span>
            </div>
            <div className="form-group">
              <label className="form-label">Customer ID</label>
              <input className="form-input" value={form.customer_id} onChange={e=>set('customer_id',e.target.value)} required />
            </div>
            <div className="form-group" style={{ gridColumn:'1/-1' }}>
              <label className="form-label">Mandate ID (optional)</label>
              <input className="form-input" value={form.mandate_id} onChange={e=>set('mandate_id',e.target.value)} />
            </div>
          </div>
          <div style={{ display:'flex', gap:8, marginTop:4 }}>
            <button className="btn btn-primary" type="submit" disabled={loading} style={{ flex:1 }}>
              {loading ? <LoaderIcon size={14} /> : <SendIcon size={14} />}
              {loading ? 'Processing…' : 'Submit to Engine'}
            </button>
            <button className="btn btn-ghost" type="button" onClick={onClose}>Cancel</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [health, setHealth]         = useState(null)
  const [metrics, setMetrics]       = useState(null)
  const [auditLog, setAuditLog]     = useState([])
  const [loading, setLoading]       = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [showModal, setShowModal]   = useState(false)
  const [showSimulator, setShowSimulator] = useState(false)
  const [selected, setSelected]     = useState(null)
  const [demoLoading, setDemoLoading] = useState(null)
  const pollRef = useRef(null)

  const loadData = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    else setRefreshing(true)
    try {
      const [h, m] = await Promise.allSettled([api.health(), api.metrics()])
      if (h.status === 'fulfilled') setHealth(h.value)
      if (m.status === 'fulfilled') setMetrics(m.value)
    } catch (_) {}
    finally { setLoading(false); setRefreshing(false) }
  }, [])

  useEffect(() => {
    loadData()
    pollRef.current = setInterval(() => loadData(true), 15000)
    return () => clearInterval(pollRef.current)
  }, [loadData])

  /** Enrich an audit response with fields we stored from the original payload */
  function enrichAudit(res, extra = {}) {
    return { ...res, ...extra, _ts: new Date() }
  }

  async function runDemo(scenario) {
    setDemoLoading(scenario.id)
    try {
      const payload = {
        event_id: uid(),
        transaction_id: `txn-demo-${scenario.id}-${Date.now()}`,
        failure_code: scenario.failureCode,
        amount_paise: scenario.amountPaise,
        customer_id: 'cust-demo',
        occurred_at: new Date().toISOString(),
      }
      const res = await api.ingestWebhook(payload)
      const enriched = enrichAudit(res, {
        transaction_id: payload.transaction_id,
        _failure_code:  payload.failure_code,
        _amount_paise:  payload.amount_paise,
        _occurred_at:   payload.occurred_at,
      })
      setSelected(enriched)
      setAuditLog(l => [enriched, ...l].slice(0, 50))
      await loadData(true)
      const d = res.decision === 'APPROVE' ? 'APPROVED' : 'BLOCKED'
      toastSuccess(`${scenario.label}: ${d} — ${res.policy_rule_applied}`)
    } catch (err) { toastError(`Demo failed: ${err.message}`) }
    finally { setDemoLoading(null) }
  }

  function handleWebhookSuccess(enriched) {
    setSelected(enriched)
    setAuditLog(l => [enriched, ...l].slice(0, 50))
    loadData(true)
    setShowModal(false)
  }

  const connected   = health?.status === 'ok'
  const m           = metrics || {}

  // Live session metrics (from the running DB)
  const liveTxns    = m.total_transactions ?? 0
  const liveRecovered = m.recovered_count ?? 0
  const liveRate    = m.recovery_rate_pct ?? 0
  const liveAmt     = m.recovered_amount_paise != null ? fmtRupees(m.recovered_amount_paise) : '₹0'
  const hasLiveData = liveTxns > 0

  // Benchmark constants (synthetic simulation)
  const BM = BENCHMARK

  return (
    <div style={{ minHeight:'100vh', background:'var(--bg-base)' }}>

      {/* ── HEADER ─────────────────────────────────────────────────── */}
      <header style={{
        position:'sticky', top:0, zIndex:100,
        background:'rgba(8,12,20,0.92)', backdropFilter:'blur(12px)',
        borderBottom:'1px solid var(--border)',
        padding:'0 28px', height:60,
        display:'flex', alignItems:'center', gap:16,
      }}>
        <div style={{ display:'flex', alignItems:'center', gap:10, flexShrink:0 }}>
          <div style={{
            width:34, height:34, borderRadius:8,
            background:'linear-gradient(135deg, #3b82f6 0%, #06b6d4 100%)',
            display:'flex', alignItems:'center', justifyContent:'center',
            boxShadow:'0 0 16px rgba(59,130,246,0.4)',
          }}>
            <ZapIcon size={18} color="#fff" />
          </div>
          <div>
            <div style={{ fontSize:15, fontWeight:800, color:'var(--text-primary)', lineHeight:1 }}>PayDay Engine</div>
            <div style={{ fontSize:9, fontWeight:700, color:'var(--text-muted)', letterSpacing:'0.12em', textTransform:'uppercase' }}>Autonomous Retry Control</div>
          </div>
        </div>

        <div style={{ flex:1, textAlign:'center' }} className="hide-mobile">
          <div style={{ fontSize:13, fontWeight:600, color:'var(--text-secondary)' }}>Autonomous Payment Recovery</div>
          <div style={{ fontSize:10, color:'var(--text-muted)', letterSpacing:'0.04em' }}>AI-assisted failure diagnosis · Deterministic retry guardrails</div>
        </div>

        <div style={{ display:'flex', alignItems:'center', gap:10, flexShrink:0 }}>
          <div style={{ display:'flex', alignItems:'center', gap:6 }}>
            <div style={{ width:7, height:7, borderRadius:'50%',
              background: connected ? 'var(--green)' : '#6b7280',
              animation: connected ? 'pulse-dot 2s ease-in-out infinite' : 'none' }} />
            <span style={{ fontSize:11, color: connected ? 'var(--green)' : 'var(--text-muted)', fontWeight:600 }}>
              {connected ? 'LIVE ENGINE' : 'OFFLINE'}
            </span>
          </div>

          {/* Policy Simulator button — NEW */}
          <button className="btn btn-cyan" style={{ padding:'6px 12px', fontSize:12 }}
            onClick={() => setShowSimulator(true)}>
            <ShieldIcon size={13} /> Policy Simulator
          </button>

          <button className="btn btn-ghost" style={{ padding:'6px 10px', fontSize:12 }}
            onClick={() => loadData(true)} disabled={refreshing}>
            <RefreshIcon size={13} style={{ animation: refreshing ? 'spin 1s linear infinite' : 'none' }} />
            {refreshing ? '' : 'Refresh'}
          </button>

          <button className="btn btn-primary" style={{ padding:'6px 14px', fontSize:12 }}
            onClick={() => setShowModal(true)}>
            <PlusIcon size={13} /> Simulate
          </button>
        </div>
      </header>

      {/* ── MAIN ───────────────────────────────────────────────────── */}
      <main style={{ maxWidth:1400, margin:'0 auto', padding:'28px 24px', display:'flex', flexDirection:'column', gap:28 }}>

        {/* ── LIVE SESSION + SYNTHETIC BENCHMARK — clearly separated ── */}
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>

          {/* Live session box */}
          <div style={{
            background:'rgba(6,182,212,0.04)', border:'1px solid rgba(6,182,212,0.18)',
            borderRadius:'var(--radius-lg)', padding:'18px 22px',
          }}>
            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:14 }}>
              <span style={{ fontSize:13, fontWeight:700, color:'var(--text-primary)' }}>Live Session</span>
              <span className="section-label label-live">LIVE DB</span>
              {!hasLiveData && <span style={{ fontSize:11, color:'var(--text-muted)' }}>— run a demo to populate</span>}
            </div>
            <div style={{ display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:12 }}>
              {[
                { label:'Transactions', value: liveTxns.toLocaleString(), color:'var(--cyan)' },
                { label:'Recovered', value: liveRecovered.toLocaleString(), color:'var(--green)' },
                { label:'Recovery Rate', value: `${liveRate.toFixed(1)}%`, color:'var(--blue)' },
              ].map(k => (
                <div key={k.label} style={{ textAlign:'center' }}>
                  <div style={{ fontSize:20, fontWeight:800, color: hasLiveData ? k.color : 'var(--text-muted)' }}>{k.value}</div>
                  <div style={{ fontSize:11, color:'var(--text-muted)', marginTop:2 }}>{k.label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Synthetic benchmark box */}
          <div style={{
            background:'rgba(139,92,246,0.04)', border:'1px solid rgba(139,92,246,0.18)',
            borderRadius:'var(--radius-lg)', padding:'18px 22px',
          }}>
            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:14 }}>
              <span style={{ fontSize:13, fontWeight:700, color:'var(--text-primary)' }}>Synthetic Benchmark</span>
              <span className="section-label label-bench">1,000 RECORDS · SEED 42</span>
            </div>
            <div style={{ display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:12 }}>
              {[
                { label:'Baseline', value:'40%', color:'#475569' },
                { label:'Engine', value:'53%', color:'var(--blue)' },
                { label:'Δ Rate', value:'+13pp', color:'var(--green)' },
                { label:'Δ Txns', value:'+130', color:'var(--cyan)' },
              ].map(k => (
                <div key={k.label} style={{ textAlign:'center' }}>
                  <div style={{ fontSize:20, fontWeight:800, color:k.color }}>{k.value}</div>
                  <div style={{ fontSize:11, color:'var(--text-muted)', marginTop:2 }}>{k.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── KPI CARDS ─────────────────────────────────────────── */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(200px, 1fr))', gap:16 }}>
          <KpiCard loading={loading} icon={<ActivityIcon size={14} />} label="Transactions (Live)" accent="#06b6d4"
            value={liveTxns.toLocaleString() || '—'}
            sub={liveTxns > 0 ? `${m.by_failure_category?.HARD_DECLINE ?? 0} hard declines blocked` : 'No live data yet'} />
          <KpiCard loading={loading} icon={<TrendUpIcon size={14} />} label="Recovery Rate (Benchmark)" accent="#22c55e"
            value="53%" sub="Baseline: 40%" delta="+13 pp improvement" />
          <KpiCard loading={loading} icon={<CheckCircleIcon size={14} />} label="Retry Recoveries (Benchmark)" accent="#06b6d4"
            value="530" delta="+130 vs baseline" deltaLabel=" transactions" />
          <KpiCard loading={loading} icon={<DatabaseIcon size={14} />} label="Recovered Amount (Benchmark)" accent="#8b5cf6"
            value={fmtRupeesFromRupees(BM.engine.recoveredAmountRupees)}
            sub="⚠️ Synthetic simulation only" />
          <KpiCard loading={loading} icon={<ShieldIcon size={14} />} label="Guardrails" accent="#f59e0b"
            value="100% deterministic" sub="All execution decisions" />
        </div>

        {/* ── RECOVERY FUNNEL (NEW Feature 3) ────────────────────── */}
        <RecoveryFunnel liveMetrics={metrics} />

        {/* ── ROW: Recovery Chart + Pipeline ─────────────────────── */}
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:20 }}>
          <div className="card">
            <div style={{ marginBottom:18 }}>
              <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:4 }}>
                <div style={{ fontSize:14, fontWeight:700, color:'var(--text-primary)' }}>Recovery Comparison</div>
                <span className="section-label label-bench">SYNTHETIC</span>
              </div>
              <div style={{ fontSize:12, color:'var(--text-muted)' }}>Fixed baseline vs autonomous engine — 1,000 record simulation</div>
            </div>
            <RecoveryChart />
            <div style={{ marginTop:16, padding:'10px 14px',
              background:'rgba(59,130,246,0.05)', border:'1px solid rgba(59,130,246,0.1)',
              borderRadius:'var(--radius-sm)', fontSize:12, color:'var(--text-secondary)', lineHeight:1.6 }}>
              <InfoIcon size={12} style={{ marginRight:6, verticalAlign:'middle' }} />
              Autonomous scheduling improves recovery while preserving deterministic safety controls.
            </div>
          </div>

          <div className="card">
            <div style={{ marginBottom:18 }}>
              <div style={{ fontSize:14, fontWeight:700, color:'var(--text-primary)', marginBottom:4 }}>Retry Pipeline</div>
              <div style={{ fontSize:12, color:'var(--text-muted)' }}>End-to-end event flow</div>
            </div>
            <div style={{ display:'flex', alignItems:'center', gap:6, overflowX:'auto', paddingBottom:8 }}>
              <PipelineStage label="FAILED PAYMENT" sub="Webhook ingested" accent="#ef4444" />
              <PipelineArrow />
              <PipelineStage label="LLM DIAGNOSIS" sub="classify only" accent="#8b5cf6" highlight />
              <PipelineArrow />
              <PipelineStage label="POLICY ENGINE" sub="final decision" accent="#3b82f6" highlight />
              <PipelineArrow />
              <PipelineStage label="SCHEDULER" sub="timing predictor" accent="#06b6d4" />
              <PipelineArrow />
              <PipelineStage label="MOCK EXECUTOR" sub="no real payments" accent="#f59e0b" />
              <PipelineArrow />
              <PipelineStage label="AUDIT TRAIL" sub="immutable log" accent="#22c55e" />
            </div>
            <div style={{ marginTop:16, display:'flex', gap:10 }}>
              <div style={{ flex:1, padding:'8px 12px', background:'rgba(139,92,246,0.08)',
                border:'1px solid rgba(139,92,246,0.2)', borderRadius:'var(--radius-sm)',
                fontSize:11, color:'var(--purple)', fontWeight:600, textAlign:'center' }}>
                LLM = Diagnosis only
              </div>
              <div style={{ flex:1, padding:'8px 12px', background:'rgba(59,130,246,0.08)',
                border:'1px solid rgba(59,130,246,0.2)', borderRadius:'var(--radius-sm)',
                fontSize:11, color:'var(--blue)', fontWeight:600, textAlign:'center' }}>
                Policy = Final decision
              </div>
            </div>
          </div>
        </div>

        {/* ── ROW: Demo scenarios + Safety guardrails ────────────── */}
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:20 }}>
          <div className="card">
            <div style={{ marginBottom:16 }}>
              <div style={{ fontSize:14, fontWeight:700, color:'var(--text-primary)', marginBottom:4 }}>
                Demo Scenarios
                <span style={{ fontSize:10, fontWeight:600, color:'var(--cyan)',
                  background:'rgba(6,182,212,0.1)', border:'1px solid rgba(6,182,212,0.2)',
                  borderRadius:'99px', padding:'1px 8px', marginLeft:8 }}>
                  LIVE API
                </span>
              </div>
              <div style={{ fontSize:12, color:'var(--text-muted)' }}>Calls real backend — no frontend policy logic</div>
            </div>
            <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
              {DEMO_SCENARIOS.map(s => (
                <button key={s.id} className="btn btn-ghost"
                  style={{ width:'100%', justifyContent:'flex-start', gap:12,
                    padding:'12px 14px', textAlign:'left',
                    borderColor: `${s.color}30`,
                    background: demoLoading === s.id ? `${s.color}08` : 'transparent' }}
                  disabled={demoLoading !== null}
                  onClick={() => runDemo(s)}>
                  {demoLoading === s.id ? <LoaderIcon size={14} color={s.color} /> : <PlayIcon size={14} color={s.color} />}
                  <div style={{ flex:1, minWidth:0 }}>
                    <div style={{ fontWeight:600, color:'var(--text-primary)', fontSize:13 }}>{s.label}</div>
                    <div style={{ fontSize:11, color:'var(--text-muted)', marginTop:1 }}>{s.description}</div>
                  </div>
                  <span style={{ fontSize:10, color:s.color, fontWeight:600, flexShrink:0 }}>{s.expected}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="card">
            <div style={{ marginBottom:16 }}>
              <div style={{ display:'flex', alignItems:'center', gap:8, fontSize:14, fontWeight:700, color:'var(--text-primary)', marginBottom:4 }}>
                <ShieldIcon size={16} color="var(--green)" />
                Safety Guardrails
              </div>
              <div style={{ fontSize:12, color:'var(--text-muted)' }}>Deterministic enforcement — cannot be overridden by AI</div>
            </div>
            <GuardrailRow text="Maximum retries: 3 per transaction" />
            <GuardrailRow text="Minimum transaction value: ₹100" />
            <GuardrailRow text="Hard declines: Never retried" />
            <GuardrailRow text="Duplicate webhooks: Idempotently rejected" />
            <GuardrailRow text="All execution decisions: Deterministic Python" />
            <GuardrailRow text="Payment execution: Mock only — no real Razorpay API" />
            <GuardrailRow text="LLM output: Validated by Pydantic before use" />
            <div style={{ marginTop:16, padding:'10px 12px', background:'rgba(34,197,94,0.06)',
              border:'1px solid rgba(34,197,94,0.15)', borderRadius:'var(--radius-sm)',
              fontSize:12, color:'var(--green)', fontWeight:500 }}>
              The system is autonomous but controlled. The LLM cannot approve, schedule, or execute payments.
            </div>
          </div>
        </div>

        {/* ── AUDIT LOG + TRANSACTION TIMELINE (NEW Feature 1) ───── */}
        <div style={{ display:'grid', gridTemplateColumns: selected ? '1fr 360px' : '1fr', gap:20, alignItems:'start' }}>
          <div className="card" style={{ padding:0, overflow:'hidden' }}>
            <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between',
              padding:'16px 20px', borderBottom:'1px solid var(--border)' }}>
              <div>
                <div style={{ fontSize:14, fontWeight:700 }}>Live Audit Log</div>
                <div style={{ fontSize:12, color:'var(--text-muted)', marginTop:2 }}>
                  {auditLog.length === 0
                    ? 'Run a demo scenario or simulate a payment to see entries'
                    : `${auditLog.length} events this session — click any row to see the Transaction Journey`}
                </div>
              </div>
              <div style={{ display:'flex', gap:8 }}>
                <button className="btn btn-cyan" style={{ fontSize:12, padding:'6px 12px' }}
                  onClick={() => setShowSimulator(true)}>
                  <ShieldIcon size={13} /> Policy Simulator
                </button>
                <button className="btn btn-primary" style={{ fontSize:12, padding:'6px 14px' }}
                  onClick={() => setShowModal(true)}>
                  <PlusIcon size={13} /> Simulate Payment
                </button>
              </div>
            </div>

            {auditLog.length === 0 ? (
              <div style={{ padding:'48px 24px', textAlign:'center', color:'var(--text-muted)' }}>
                <ListIcon size={32} style={{ margin:'0 auto 12px', opacity:0.3 }} />
                <div style={{ fontSize:13, fontWeight:500 }}>No events yet</div>
                <div style={{ fontSize:12, marginTop:4 }}>Use the demo scenarios or simulate a payment above</div>
              </div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Transaction</th>
                      <th>Failure Code</th>
                      <th>Category</th>
                      <th>Decision</th>
                      <th>Policy Rule</th>
                      <th>Attempt #</th>
                      <th>Scheduled</th>
                      <th>Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditLog.map((e, i) => (
                      <tr key={e.audit_id || i}
                        className={selected?.audit_id === e.audit_id ? 'selected' : ''}
                        style={{ cursor:'pointer' }}
                        onClick={() => setSelected(selected?.audit_id === e.audit_id ? null : e)}>
                        <td><span className="mono" style={{ fontSize:12, color:'var(--text-muted)' }}>{shortId(e.transaction_id)}</span></td>
                        <td><span className="mono" style={{ fontSize:11, color:'var(--text-secondary)' }}>{e._failure_code || '—'}</span></td>
                        <td><CategoryBadge category={e.failure_category} /></td>
                        <td><DecisionBadge decision={e.decision} /></td>
                        <td><RuleBadge rule={e.policy_rule_applied} /></td>
                        <td style={{ color:'var(--text-muted)', fontSize:12 }}>{e.retry_attempt_number || '—'}</td>
                        <td style={{ color:'var(--text-muted)', fontSize:11 }}>{fmtTime(e.retry_scheduled_at)}</td>
                        <td style={{ color:'var(--text-muted)', fontSize:11 }}>{fmtTime(e.decided_at || e._ts?.toISOString())}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Transaction Journey Timeline (Feature 1) */}
          {selected && (
            <TransactionTimeline
              audit={selected}
              onClose={() => setSelected(null)}
            />
          )}
        </div>

        {/* ── BENCHMARK / BUSINESS IMPACT ─────────────────────────── */}
        <div className="card" style={{
          background:'linear-gradient(135deg, rgba(59,130,246,0.06) 0%, rgba(8,12,20,1) 60%)',
          borderColor:'rgba(59,130,246,0.2)',
        }}>
          <div style={{ marginBottom:20 }}>
            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:4 }}>
              <div style={{ fontSize:14, fontWeight:700, color:'var(--text-primary)' }}>Business Impact</div>
              <span className="section-label label-bench">SYNTHETIC BENCHMARK · 1,000 RECORDS</span>
            </div>
            <div style={{ fontSize:12, color:'var(--text-muted)' }}>
              Seed 42 · <span style={{ color:'var(--orange)' }}>SYNTHETIC SIMULATION — NOT REAL-WORLD DATA</span>
            </div>
          </div>

          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(180px, 1fr))', gap:16, marginBottom:20 }}>
            {[
              { label:'Fixed 24h Baseline', value:'40%', sub:'Recovery rate', color:'#475569' },
              { label:'Autonomous Engine', value:'53%', sub:'Recovery rate', color:'#3b82f6' },
              { label:'Improvement', value:'+13 pp', sub:'Percentage points', color:'#22c55e' },
              { label:'Additional Recoveries', value:'+130', sub:'Transactions', color:'#06b6d4' },
              { label:'Extra Recovered', value:'₹34.8 L', sub:'Amount delta (synthetic)', color:'#8b5cf6' },
            ].map(c => (
              <div key={c.label} style={{
                background:'rgba(255,255,255,0.03)', border:`1px solid ${c.color}20`,
                borderRadius:'var(--radius)', padding:'16px', borderTop:`2px solid ${c.color}`,
              }}>
                <div style={{ fontSize:11, color:'var(--text-muted)', fontWeight:600, textTransform:'uppercase', letterSpacing:'0.05em', marginBottom:6 }}>{c.label}</div>
                <div style={{ fontSize:22, fontWeight:800, color:c.color, lineHeight:1 }}>{c.value}</div>
                <div style={{ fontSize:11, color:'var(--text-muted)', marginTop:4 }}>{c.sub}</div>
              </div>
            ))}
          </div>

          <div style={{ padding:'12px 16px', background:'rgba(34,197,94,0.06)',
            border:'1px solid rgba(34,197,94,0.15)', borderRadius:'var(--radius-sm)',
            fontSize:13, color:'var(--text-secondary)', lineHeight:1.7 }}>
            <CheckIcon size={14} color="var(--green)" style={{ marginRight:8, verticalAlign:'middle' }} />
            The autonomous engine recovers more eligible payments without weakening retry safety rules.
            Hard declines (376) and below-threshold transactions (70) are blocked identically in both strategies.
          </div>
        </div>

        {/* ── FOOTER ─────────────────────────────────────────────── */}
        <div style={{ textAlign:'center', padding:'16px 0', fontSize:11, color:'var(--text-muted)',
          borderTop:'1px solid var(--border)' }}>
          PayDay Engine · Razorpay AI Buildathon ·{' '}
          ⚠️ SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ·{' '}
          Mock executor only — no real Razorpay API calls
        </div>
      </main>

      {/* ── MODALS & OVERLAYS ──────────────────────────────────── */}
      {showModal && (
        <WebhookModal
          onClose={() => setShowModal(false)}
          onSuccess={handleWebhookSuccess}
        />
      )}

      {/* Policy Simulator modal (Feature 2) */}
      {showSimulator && (
        <PolicySimulator onClose={() => setShowSimulator(false)} />
      )}

      <ToastContainer />
    </div>
  )
}
