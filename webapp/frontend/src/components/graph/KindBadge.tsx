import { kindColor, type NodeKind } from '@/lib/kinds'

/** A plain dot in the kind's colour, matching the circles on the canvas. */
export function KindSwatch({ kind, size = 12 }: { kind: NodeKind; size?: number }) {
  return (
    <span
      aria-hidden
      className="inline-block shrink-0 rounded-full"
      style={{ width: size, height: size, background: kindColor(kind) }}
    />
  )
}
