export function DecisionBadge({ decision }) {
  const map = {
    APPROVE: 'badge-approve',
    REJECT:  'badge-reject',
    DEFER:   'badge-defer',
  }
  return <span className={`badge ${map[decision] || 'badge-defer'}`}>{decision}</span>
}

export function CategoryBadge({ category }) {
  const map = {
    LIQUIDITY_TEMPORARY:  { cls: 'badge-liquidity', label: 'Liquidity' },
    BANK_SURGE_TEMPORARY: { cls: 'badge-surge',    label: 'Bank Surge' },
    HARD_DECLINE:         { cls: 'badge-hard',     label: 'Hard Decline' },
  }
  const { cls, label } = map[category] || { cls: 'badge-defer', label: category }
  return <span className={`badge ${cls}`}>{label}</span>
}

export function RuleBadge({ rule }) {
  if (!rule) return null
  const colors = {
    APPROVE_LIQUIDITY_TEMPORARY:  '#3b82f6',
    APPROVE_BANK_SURGE_TEMPORARY: '#8b5cf6',
    HARD_DECLINE_BLOCK:           '#ef4444',
    MIN_AMOUNT_BLOCK:             '#f59e0b',
    MAX_RETRIES_BLOCK:            '#f97316',
    DUPLICATE_EVENT_BLOCK:        '#6b7280',
    EXECUTION_SUCCESS:            '#22c55e',
    EXECUTION_FAILURE:            '#ef4444',
  }
  const color = colors[rule] || '#6b7280'
  return (
    <span className="mono" style={{
      fontSize: '11px', color, background: `${color}18`,
      border: `1px solid ${color}30`, padding: '2px 7px', borderRadius: '4px'
    }}>
      {rule}
    </span>
  )
}
