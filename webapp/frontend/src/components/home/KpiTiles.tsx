import type { LucideIcon } from 'lucide-react'
import { Anchor, BookOpenText, Factory, Package, Ship, Truck } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { dateLabel, fmt } from '@/lib/format'
import type { HomeStats } from '@/lib/types'

function Tile({ icon: Icon, label, value, sub }: { icon: LucideIcon; label: string; value: string; sub: string }) {
  return (
    <Card className="gap-0 p-4">
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <Icon className="size-3.5" />
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      <div className="mt-0.5 truncate text-xs text-muted-foreground" title={sub}>{sub}</div>
    </Card>
  )
}

export function KpiTiles({ stats }: { stats?: HomeStats }) {
  if (!stats) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-[98px] rounded-xl" />)}
      </div>
    )
  }
  const tiles = [
    { icon: Factory, label: 'Suppliers', value: fmt(stats.supplier_companies), sub: `companies (${fmt(stats.suppliers)} graph nodes)` },
    { icon: Ship, label: 'Shipments', value: fmt(stats.shipments), sub: `${dateLabel(stats.first_arrival)} – ${dateLabel(stats.last_arrival)}` },
    { icon: Package, label: 'Products', value: fmt(stats.products), sub: 'HS-6 product codes' },
    { icon: Anchor, label: 'Ports', value: fmt(stats.ports), sub: `${fmt(stats.exit_ports)} exit · ${fmt(stats.entry_ports)} entry` },
    { icon: Truck, label: 'Carriers', value: fmt(stats.carriers), sub: `${fmt(stats.vessels)} vessels` },
    { icon: BookOpenText, label: 'Evidence records', value: fmt(stats.evidence_records), sub: 'in the risk evidence engine' },
  ]
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
      {tiles.map((t) => <Tile key={t.label} {...t} />)}
    </div>
  )
}
