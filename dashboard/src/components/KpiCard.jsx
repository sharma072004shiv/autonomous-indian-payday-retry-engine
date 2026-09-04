import { TrendUpIcon } from './Icons.jsx'

export function KpiCard({ icon, label, value, sub, delta, deltaLabel, accent = '#3b82f6', loading }) {
  if (loading) {
    return (
      <div className="card" style={{ display:'flex', flexDirection:'column', gap:10 }}>
        <div className="skeleton" style={{ height:12, width:'40%' }} />
        <div className="skeleton" style={{ height:28, width:'60%' }} />
        <div className="skeleton" style={{ height:12, width:'80%' }} />
      </div>
    )
  }
  return (
    <div className="card" style={{
      display:'flex', flexDirection:'column', gap:6,
      borderTop: `2px solid ${accent}`,
      position:'relative', overflow:'hidden'
    }}>
      <div style={{
        position:'absolute', top:0, right:0, width:120, height:120,
        background: `radial-gradient(circle at top right, ${accent}12 0%, transparent 70%)`,
        pointerEvents:'none'
      }} />
      <div style={{ display:'flex', alignItems:'center', gap:7, color:'var(--text-secondary)', fontSize:12, fontWeight:600, textTransform:'uppercase', letterSpacing:'0.05em' }}>
        {icon}
        {label}
      </div>
      <div style={{ fontSize:28, fontWeight:700, color:'var(--text-primary)', lineHeight:1.1 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize:12, color:'var(--text-secondary)' }}>{sub}</div>}
      {delta && (
        <div style={{ display:'flex', alignItems:'center', gap:4, fontSize:12, color:'var(--green)', fontWeight:600, marginTop:2 }}>
          <TrendUpIcon size={13} />
          {delta}
          {deltaLabel && <span style={{ color:'var(--text-muted)', fontWeight:400 }}>{deltaLabel}</span>}
        </div>
      )}
    </div>
  )
}
