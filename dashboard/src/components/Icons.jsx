/**
 * Minimal inline SVG icons — no external icon library needed.
 * All icons are 16×16 by default, size prop overrides.
 */
export function Icon({ d, size = 16, color = 'currentColor', ...p }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}>
      {Array.isArray(d) ? d.map((path, i) => <path key={i} d={path} />) : <path d={d} />}
    </svg>
  )
}

const P = {
  activity:     'M22 12h-4l-3 9L9 3l-3 9H2',
  alert:        'M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z;M12 9v4;M12 17h.01',
  check:        'M20 6L9 17l-5-5',
  checkCircle:  'M22 11.08V12a10 10 0 11-5.93-9.14;M22 4L12 14.01l-3-3',
  chevronRight: 'M9 18l6-6-6-6',
  chevronDown:  'M6 9l6 6 6-6',
  clock:        'M12 2a10 10 0 100 20A10 10 0 0012 2zm0 0v10l4 2',
  close:        'M18 6L6 18M6 6l12 12',
  copy:         'M20 9h-9a2 2 0 00-2 2v9a2 2 0 002 2h9a2 2 0 002-2v-9a2 2 0 00-2-2z;M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1',
  database:     'M12 2C6.48 2 2 4.24 2 7s4.48 5 10 5 10-2.24 10-5-4.48-5-10-5zm0 13c-5.52 0-10-2.24-10-5v6c0 2.76 4.48 5 10 5s10-2.24 10-5v-6c0 2.76-4.48 5-10 5zm0-6c-5.52 0-10-2.24-10-5v6c0 2.76 4.48 5 10 5s10-2.24 10-5V9c0 2.76-4.48 5-10 5z',
  eye:          'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z;M12 9a3 3 0 100 6 3 3 0 000-6z',
  filter:       'M22 3H2l8 9.46V19l4 2v-8.54L22 3z',
  hash:         'M4 9h16M4 15h16M10 3L8 21M16 3l-2 18',
  info:         'M12 2a10 10 0 100 20A10 10 0 0012 2zm0 0v0;M12 16v-4;M12 8h.01',
  list:         'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  loader:       'M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83',
  play:         'M5 3l14 9-14 9V3z',
  plus:         'M12 5v14M5 12h14',
  refresh:      'M23 4v6h-6M1 20v-6h6;M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15',
  shield:       'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
  send:         'M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z',
  trendUp:      'M23 6l-9.5 9.5-5-5L1 18;M17 6h6v6',
  warning:      'M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z',
  x:            'M18 6L6 18M6 6l12 12',
  zap:          'M13 2L3 14h9l-1 8 10-12h-9l1-8z',
}

export const ActivityIcon    = (p) => <Icon d={P.activity} {...p} />
export const AlertIcon       = (p) => <Icon d={P.alert.split(';')} {...p} />
export const CheckIcon       = (p) => <Icon d={P.check} {...p} />
export const CheckCircleIcon = (p) => <Icon d={P.checkCircle.split(';')} {...p} />
export const ChevronRightIcon= (p) => <Icon d={P.chevronRight} {...p} />
export const ChevronDownIcon = (p) => <Icon d={P.chevronDown} {...p} />
export const ClockIcon       = (p) => <Icon d={P.clock} {...p} />
export const CloseIcon       = (p) => <Icon d={P.close} {...p} />
export const CopyIcon        = (p) => <Icon d={P.copy.split(';')} {...p} />
export const DatabaseIcon    = (p) => <Icon d={P.database} {...p} />
export const EyeIcon         = (p) => <Icon d={P.eye.split(';')} {...p} />
export const FilterIcon      = (p) => <Icon d={P.filter} {...p} />
export const HashIcon        = (p) => <Icon d={P.hash} {...p} />
export const InfoIcon        = (p) => <Icon d={P.info.split(';')} {...p} />
export const ListIcon        = (p) => <Icon d={P.list} {...p} />
export const LoaderIcon      = (p) => <Icon d={P.loader} {...p} style={{ animation:'spin 1s linear infinite', ...p.style }} />
export const PlayIcon        = (p) => <Icon d={P.play} {...p} />
export const PlusIcon        = (p) => <Icon d={P.plus} {...p} />
export const RefreshIcon     = (p) => <Icon d={P.refresh.split(';')} {...p} />
export const SendIcon        = (p) => <Icon d={P.send.split(';')} {...p} />
export const ShieldIcon      = (p) => <Icon d={P.shield} {...p} />
export const TrendUpIcon     = (p) => <Icon d={P.trendUp.split(';')} {...p} />
export const WarningIcon     = (p) => <Icon d={P.warning} {...p} />
export const XIcon           = (p) => <Icon d={P.x} {...p} />
export const ZapIcon         = (p) => <Icon d={P.zap} {...p} />
