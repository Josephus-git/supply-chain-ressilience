import { Factory, Landmark, Star } from 'lucide-react'
import { companyStyle } from '@/components/home/TopSuppliersChart'
import { fmt, plural } from '@/lib/format'
import type { Mode } from '@/lib/palette'
import type { TopSuppliers } from '@/lib/types'
import { cn } from '@/lib/utils'

const ROW = 34 // px per supplier row
const GAP = 14 // extra px between parent groups
const HEAD = 52 // px reserved for column headings
const BOX = 24 // box height
// Column x positions, in % of the drawing width.
const COL = { dyson: [0, 18], supplier: [25, 58], parent: [67, 100] } as const
const NO_PARENT = 'No parent company recorded'

type Supplier = TopSuppliers['series'][number] & { rank: number; y: number }

/**
 * Dyson -> its top suppliers -> their parent companies (SUBSIDIARY_OF).
 * Suppliers sharing a parent sit together, and their links converge on one
 * parent box, so supplier concentration is visible at a glance. Groups are
 * ordered by their best-ranked supplier.
 * Boxes are HTML (crisp text); curves are one SVG stretched over the same
 * area with non-scaling strokes, so both share percentage x coordinates.
 */
export function RelationshipsTree({ data, mode }: { data: TopSuppliers; mode: Mode }) {
  const byParent = new Map<string, Omit<Supplier, 'y'>[]>()
  data.series.forEach((s, rank) => {
    const key = s.parents.length ? s.parents.join(' / ') : NO_PARENT
    byParent.set(key, [...(byParent.get(key) ?? []), { ...s, rank }])
  })

  let y = HEAD
  const groups = [...byParent.entries()].map(([parent, members]) => {
    const suppliers: Supplier[] = members.map((m, i) => ({ ...m, y: y + i * ROW + ROW / 2 }))
    y += members.length * ROW + GAP
    const mid = (suppliers[0].y + suppliers[suppliers.length - 1].y) / 2
    return { parent, suppliers, mid, total: members.reduce((n, m) => n + m.total, 0) }
  })
  const height = y - GAP + 4
  const all = groups.flatMap((g) => g.suppliers)
  const dysonY = (all[0].y + all[all.length - 1].y) / 2

  const curve = (x1: number, y1: number, x2: number, y2: number) => {
    const mx = (x1 + x2) / 2
    return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`
  }

  return (
    <div className="overflow-x-auto">
      <div className="relative min-w-[760px] text-xs" style={{ height }}>
        <svg className="absolute inset-0 size-full" viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" aria-hidden>
          <g fill="none" className="stroke-muted-foreground/45" strokeWidth={1.25}>
            {groups.map((g) =>
              g.suppliers.map((s) => (
                <g key={s.company}>
                  <path d={curve(COL.dyson[1], dysonY, COL.supplier[0], s.y)} vectorEffect="non-scaling-stroke" />
                  <path d={curve(COL.supplier[1], s.y, COL.parent[0], g.mid)} vectorEffect="non-scaling-stroke" />
                </g>
              )),
            )}
          </g>
        </svg>

        <Heading col={COL.supplier}>
          Dyson's top {data.series.length} suppliers<br />
          <span className="font-normal text-muted-foreground">shipments to Dyson in the study window</span>
        </Heading>
        <Heading col={COL.parent}>
          Parent companies<br />
          <span className="font-normal text-muted-foreground">{plural(groups.length, 'group')} · combined shipments</span>
        </Heading>

        <Box col={COL.dyson} y={dysonY} className="border-foreground/30 bg-muted font-semibold">
          <Star className="size-3.5 shrink-0 fill-current" /> Dyson
        </Box>

        {groups.map((g) => (
          <div key={g.parent}>
            {g.suppliers.map((s) => (
              <Box key={s.company} col={COL.supplier} y={s.y} className="border-primary/40 bg-primary/5" title={`${s.company}: ${s.supplier_ids.length} supplier record(s) in the graph`}>
                <span className="size-2 shrink-0 rounded-full" style={{ background: companyStyle(mode, s.rank).color }} />
                <Factory className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="truncate">{s.company}</span>
                <span className="ml-auto pl-2 tabular-nums text-muted-foreground">{fmt(s.total)}</span>
              </Box>
            ))}
            <Box
              col={COL.parent}
              y={g.mid}
              title={g.parent}
              className={cn(
                'border-emerald-600/35 bg-emerald-600/8 dark:border-emerald-400/30 dark:bg-emerald-400/8',
                g.suppliers.length > 1 && 'border-emerald-600/70 font-medium dark:border-emerald-400/60',
              )}
            >
              <Landmark className="size-3.5 shrink-0 text-muted-foreground" />
              <span className={cn('truncate', g.parent === NO_PARENT && 'italic text-muted-foreground')}>{g.parent}</span>
              <span className="ml-auto pl-2 tabular-nums text-muted-foreground">
                {g.suppliers.length > 1 && <span className="mr-1.5">{g.suppliers.length} suppliers ·</span>}
                {fmt(g.total)}
              </span>
            </Box>
          </div>
        ))}
      </div>
    </div>
  )
}

function place(col: readonly [number, number]) {
  return { left: `${col[0]}%`, width: `${col[1] - col[0]}%` }
}

function Heading({ col, children }: { col: readonly [number, number]; children: React.ReactNode }) {
  return (
    <div className="absolute top-0 text-center font-medium leading-snug" style={place(col)}>
      {children}
    </div>
  )
}

function Box({ col, y, className, title, children }: { col: readonly [number, number]; y: number; className?: string; title?: string; children: React.ReactNode }) {
  return (
    <div
      title={title}
      className={cn('absolute flex items-center gap-1.5 rounded-md border px-2 whitespace-nowrap', className)}
      style={{ ...place(col), top: y - BOX / 2, height: BOX }}
    >
      {children}
    </div>
  )
}

export function RelationshipsLegend() {
  return (
    <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <span className="flex items-center gap-1.5"><Star className="size-3 fill-current" /> Dyson</span>
      <span className="flex items-center gap-1.5"><Factory className="size-3" /> Supplier (count = shipments to Dyson)</span>
      <span className="flex items-center gap-1.5"><Landmark className="size-3" /> Parent company (SUBSIDIARY_OF)</span>
    </span>
  )
}
