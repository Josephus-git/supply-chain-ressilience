import { CalendarRange, CircleDashed } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { dateLabel } from '@/lib/format'
import { FAMILY_LABEL, type EvidenceDates, type EvidenceMeasure, type EvidenceSummary } from '@/lib/evidence'
import { cn } from '@/lib/utils'

/** Four broad groups, so 18 risk types stay readable at a glance. */
const GROUP: Record<string, 'supplier' | 'logistics' | 'policy' | 'hazard'> = {
  supplier_operational_disruption: 'supplier',
  supplier_financial_distress: 'supplier',
  product_quality_compliance: 'supplier',
  labour_disruption: 'supplier',
  cyberattack: 'supplier',
  supplier_or_route_concentration: 'supplier',
  port_disruption: 'logistics',
  carrier_vessel_disruption: 'logistics',
  route_chokepoint_disruption: 'logistics',
  goods_in_transit_loss_theft_or_damage: 'logistics',
  border_customs_delays: 'logistics',
  tariffs_and_duties: 'policy',
  government_restrictions: 'policy',
  geopolitical_conflict: 'policy',
  currency_fluctuations: 'policy',
  energy_or_transport_cost_increase: 'policy',
  input_material_shortage: 'policy',
  natural_hazards: 'hazard',
}

const GROUP_DOT = {
  supplier: 'bg-violet-500',
  logistics: 'bg-sky-500',
  policy: 'bg-amber-500',
  hazard: 'bg-rose-500',
}

export function RiskBadge({ riskType, label, className }: { riskType: string; label: string; className?: string }) {
  return (
    <Badge variant="outline" className={cn('gap-1.5 font-normal', className)}>
      <span className={cn('size-1.5 rounded-full', GROUP_DOT[GROUP[riskType] ?? 'policy'])} />
      {label}
    </Badge>
  )
}

export function RiskDot({ riskType }: { riskType: string }) {
  return <span className={cn('inline-block size-1.5 shrink-0 rounded-full', GROUP_DOT[GROUP[riskType] ?? 'policy'])} />
}

/** The family's start and end, as stored; open or missing ends are said plainly. */
export function DateLine({ dates, className }: { dates: EvidenceDates; className?: string }) {
  const label = FAMILY_LABEL[dates.family]
  let text: string
  if (dates.undated) {
    text = 'Undated'
  } else if (dates.end_field === null || !dates.end || dates.end === dates.start) {
    text = dateLabel(dates.start)
    if (dates.open_end) text += ' → open'
  } else {
    text = `${dateLabel(dates.start)} → ${dateLabel(dates.end)}`
  }
  const tip = dates.undated
    ? `No ${dates.start_field} recorded. The date filter uses the search window${
        dates.filter_range ? ` (${dateLabel(dates.filter_range.start)} – ${dateLabel(dates.filter_range.end)})` : ''
      }.`
    : dates.open_end
      ? `${dates.open_end}. Filtered as in effect to the end of the study window.`
      : dates.end_field && !dates.end
        ? `No ${dates.end_field} recorded; counted as a single day.`
        : `${dates.start_field}${dates.end_field ? ` / ${dates.end_field}` : ''}`
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn('inline-flex items-center gap-1.5 text-xs', className)}>
          {dates.undated ? <CircleDashed className="size-3.5 text-muted-foreground" /> : <CalendarRange className="size-3.5 text-muted-foreground" />}
          <span className="text-muted-foreground">{label}</span>
          <span className={cn('tabular-nums', dates.undated && 'italic text-muted-foreground')}>{text}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">{tip}</TooltipContent>
    </Tooltip>
  )
}

const num = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 4 })

function formatMeasure(m: EvidenceMeasure): string {
  const v = num.format(m.value)
  if (m.unit === 'percent') return `${m.value > 0 && m.label === 'Reported change' ? '+' : ''}${v}%`
  return m.unit ? `${v} ${m.unit}` : v
}

export function Measures({ measures, compact }: { measures: EvidenceMeasure[]; compact?: boolean }) {
  if (!measures.length) return null
  if (!compact) {
    return (
      <dl className="space-y-2 text-sm">
        {measures.map((m, i) => (
          <div key={i}>
            <dt className="text-muted-foreground">{m.label}</dt>
            <dd>
              <span className="font-medium tabular-nums">{formatMeasure(m)}</span>
              {m.note && <span className="ml-2 text-xs text-muted-foreground">{m.note}</span>}
            </dd>
          </div>
        ))}
      </dl>
    )
  }
  const shown = measures.slice(0, 3)
  return (
    <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1 text-xs">
      {shown.map((m, i) => (
        <div key={i} className="contents">
          <dt className="truncate text-muted-foreground" title={m.label}>{m.label}</dt>
          <dd className="text-right font-medium tabular-nums">{formatMeasure(m)}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Countries({ record, max }: { record: EvidenceSummary; max?: number }) {
  const list = max ? record.countries.slice(0, max) : record.countries
  const extra = record.countries.length - list.length
  if (!record.countries.length) return <span className="text-xs text-muted-foreground">No country recorded</span>
  return (
    <span className="flex flex-wrap gap-1">
      {list.map((c) => (
        <Tooltip key={c.code}>
          <TooltipTrigger asChild>
            <Badge variant="secondary" className="px-1.5 font-mono text-[10px]">{c.code}</Badge>
          </TooltipTrigger>
          <TooltipContent>
            {c.name} · {c.fields.join(', ')}
            {c.import_side && ' (import side, not used for the graph link)'}
          </TooltipContent>
        </Tooltip>
      ))}
      {extra > 0 && <Badge variant="secondary" className="px-1.5 text-[10px]">+{extra}</Badge>}
    </span>
  )
}
