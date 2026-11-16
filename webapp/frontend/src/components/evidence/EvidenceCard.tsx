import { Link2, Network } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { EvidenceSummary } from '@/lib/evidence'
import { humanise } from '@/lib/evidence'
import { dateLabel } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Countries, DateLine, Measures, RiskBadge } from './parts'

export function EvidenceCard({ record, href, active }: { record: EvidenceSummary; href: string; active?: boolean }) {
  const entities = record.entities.slice(0, 3)
  return (
    <Link
      to={href}
      className={cn(
        'group flex flex-col gap-2.5 rounded-xl border bg-card p-4 text-card-foreground transition-colors hover:border-primary/40 hover:bg-muted/30',
        active && 'border-primary/60 ring-2 ring-primary/20',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <RiskBadge riskType={record.risk_type} label={record.risk_label} className="max-w-[70%] truncate" />
        <Countries record={record} max={4} />
      </div>

      <div>
        <h3 className="line-clamp-2 text-sm font-medium leading-snug">{record.title}</h3>
        <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{record.evidence_id}</div>
      </div>

      {record.description && (
        <p className="line-clamp-3 text-xs leading-relaxed text-muted-foreground">{record.description}</p>
      )}

      <Measures measures={record.measures} compact />

      {entities.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {entities.map((e) => (
            <span key={e.value} className="max-w-full truncate rounded bg-muted px-1.5 py-0.5 text-[11px]" title={`${e.field}: ${e.value}`}>
              {e.value}
            </span>
          ))}
          {record.entities.length > entities.length && (
            <span className="px-1 text-[11px] text-muted-foreground">+{record.entities.length - entities.length}</span>
          )}
        </div>
      )}

      <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-2.5">
        <DateLine dates={record.dates} />
        <span className="text-xs text-muted-foreground">
          {record.source.publisher ?? 'Unknown publisher'}
          {record.source.published_at && ` · ${dateLabel(record.source.published_at)}`}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <span className="truncate" title={record.verification_status ?? undefined}>{humanise(record.verification_status)}</span>
        {record.related_evidence_ids.length > 0 && (
          <span className="inline-flex items-center gap-1"><Link2 className="size-3" />{record.related_evidence_ids.length} related</span>
        )}
        {record.graph_supplier_ids.length > 0 && (
          <span className="inline-flex items-center gap-1"><Network className="size-3" />{record.graph_supplier_ids.length} graph suppliers</span>
        )}
      </div>
    </Link>
  )
}
