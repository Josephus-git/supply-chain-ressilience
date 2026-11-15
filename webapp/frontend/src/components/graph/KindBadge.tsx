import { KIND_META, kindColor, type NodeKind } from '@/lib/kinds'
import { useTheme } from '@/lib/theme'

/** Swatch drawn in the node's Cytoscape shape, so the legend matches the canvas. */
export function KindSwatch({ kind, size = 12 }: { kind: NodeKind; size?: number }) {
  const { mode } = useTheme()
  const c = kindColor(kind, mode)
  const s = size
  const shape = KIND_META[kind]?.shape
  const poly = (pts: [number, number][]) => <polygon points={pts.map(([x, y]) => `${x * s},${y * s}`).join(' ')} fill={c} />
  let el
  switch (shape) {
    case 'round-rectangle':
    case 'barrel':
      el = <rect x={s * 0.08} y={s * 0.18} width={s * 0.84} height={s * 0.64} rx={s * 0.15} fill={c} />
      break
    case 'round-hexagon':
      el = poly([[0.25, 0.07], [0.75, 0.07], [1, 0.5], [0.75, 0.93], [0.25, 0.93], [0, 0.5]])
      break
    case 'star':
      el = poly([[0.5, 0], [0.62, 0.36], [1, 0.38], [0.69, 0.6], [0.8, 0.98], [0.5, 0.76], [0.2, 0.98], [0.31, 0.6], [0, 0.38], [0.38, 0.36]])
      break
    case 'round-triangle':
      el = poly([[0.5, 0.08], [0.96, 0.9], [0.04, 0.9]])
      break
    case 'round-diamond':
      el = poly([[0.5, 0], [1, 0.5], [0.5, 1], [0, 0.5]])
      break
    case 'round-pentagon':
      el = poly([[0.5, 0.03], [0.98, 0.38], [0.8, 0.95], [0.2, 0.95], [0.02, 0.38]])
      break
    default:
      el = <circle cx={s / 2} cy={s / 2} r={s * (kind === 'shipment' ? 0.3 : 0.44)} fill={c} />
  }
  return (
    <svg width={s} height={s} viewBox={`0 0 ${s} ${s}`} className="shrink-0" aria-hidden>
      {el}
    </svg>
  )
}
