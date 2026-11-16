import { AlertTriangle, Check, Copy, ExternalLink, Network } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import {
  explorerHref, FAMILY_LABEL, humanise, useEvidenceRecord, type EvidenceBrief, type EvidenceDetail as Detail,
} from '@/lib/evidence'
import { dateLabel } from '@/lib/format'
import { Countries, Measures, RiskBadge, RiskDot } from './parts'

// Fields shown in their own sections, so the "all stored fields" list skips them.
const SHOWN = new Set(['evidence_id', 'related_evidence_ids', 'source', 'verification_status', 'limitations'])

const NARRATIVE = [
  'reported_effect', 'reported_operational_impact', 'reported_supply_chain_effect', 'reported_loss_or_damage',
  'conflict_description', 'distress_indicator', 'issue_or_standard', 'cause', 'rate_definition', 'assessment_scope',
]

function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  )
}

function CopyId({ id }: { id: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground hover:text-foreground"
      onClick={() => {
        navigator.clipboard?.writeText(id)
        setDone(true)
        setTimeout(() => setDone(false), 1200)
      }}
      title="Copy evidence id"
    >
      {id}
      {done ? <Check className="size-3" /> : <Copy className="size-3" />}
    </button>
  )
}

function Value({ value }: { value: unknown }): ReactNode {
  if (value === null || value === undefined || value === '') return <span className="italic text-muted-foreground">not recorded</span>
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return <span className="break-words">{String(value)}</span>
  if (Array.isArray(value)) {
    if (!value.length) return <span className="italic text-muted-foreground">none</span>
    return (
      <ul className="list-disc space-y-1 pl-4">
        {value.map((v, i) => <li key={i}><Value value={v} /></li>)}
      </ul>
    )
  }
  return (
    <dl className="grid grid-cols-[minmax(0,9rem)_1fr] gap-x-3 gap-y-1 rounded-md border bg-muted/30 p-2">
      {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="truncate font-mono text-[11px] text-muted-foreground" title={k}>{k}</dt>
          <dd className="min-w-0"><Value value={v} /></dd>
        </div>
      ))}
    </dl>
  )
}

function EvidenceLinks({ items, search }: { items: EvidenceBrief[]; search: string }) {
  return (
    <ul className="space-y-1">
      {items.map((r) => (
        <li key={r.evidence_id}>
          {r.missing ? (
            <span className="font-mono text-xs text-destructive">{r.evidence_id} (not in the database)</span>
          ) : (
            <Link
              to={`/evidence/${encodeURIComponent(r.evidence_id)}${search}`}
              className="flex items-start gap-2 rounded-md border px-2.5 py-1.5 text-xs transition-colors hover:bg-muted/60"
            >
              <RiskDot riskType={r.risk_type!} />
              <span className="min-w-0 flex-1">
                <span className="line-clamp-1">{r.title}</span>
                <span className="font-mono text-[10px] text-muted-foreground">{r.evidence_id} · {r.risk_label}</span>
              </span>
            </Link>
          )}
        </li>
      ))}
    </ul>
  )
}

function DetailBody({ data, search }: { data: Detail; search: string }) {
  const navigate = useNavigate()
  const { summary: s, record } = data
  const d = s.dates
  const source = (record.source ?? {}) as Record<string, string | null>
  const narrative = NARRATIVE.filter((k) => typeof record[k] === 'string' && record[k])
  const others = Object.entries(record).filter(([k]) => !SHOWN.has(k))
  const graphCountries = s.countries.filter((c) => !c.import_side).map((c) => c.code)

  return (
    <div className="space-y-6 px-5 pb-8">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <RiskBadge riskType={s.risk_type} label={s.risk_label} />
          <Countries record={s} />
        </div>
        <h2 className="text-base font-semibold leading-snug">{s.title}</h2>
        <CopyId id={s.evidence_id} />
      </div>

      <Section title="Dates">
        <dl className="grid grid-cols-[minmax(0,10rem)_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Date family</dt>
          <dd>{FAMILY_LABEL[d.family]} <span className="font-mono text-[11px] text-muted-foreground">({d.family})</span></dd>
          <dt className="font-mono text-xs text-muted-foreground">{d.start_field}</dt>
          <dd>{d.start ? dateLabel(d.start) : <span className="italic text-muted-foreground">not recorded</span>}</dd>
          {d.end_field && (
            <>
              <dt className="font-mono text-xs text-muted-foreground">{d.end_field}</dt>
              <dd>
                {d.end ? dateLabel(d.end) : <span className="italic text-muted-foreground">not recorded</span>}
                {d.open_end && <div className="text-xs text-muted-foreground">{d.open_end}</div>}
              </dd>
            </>
          )}
          {d.known_from && (
            <>
              <dt className="font-mono text-xs text-muted-foreground">known_from</dt>
              <dd>{dateLabel(d.known_from)}</dd>
            </>
          )}
          <dt className="text-muted-foreground">Published</dt>
          <dd>{dateLabel(d.published_at)}</dd>
          {d.filter_range && (
            <>
              <dt className="text-muted-foreground">Date filter uses</dt>
              <dd>
                {dateLabel(d.filter_range.start)} – {dateLabel(d.filter_range.end)}
                <span className="ml-1 text-xs text-muted-foreground">
                  ({d.filter_range.basis === 'search_window' ? 'search window: undated record' : d.open_end ? 'open to study end' : 'stored dates'})
                </span>
              </dd>
            </>
          )}
        </dl>
      </Section>

      {narrative.length > 0 && (
        <Section title="What was reported">
          <dl className="space-y-2 text-sm">
            {narrative.map((k) => (
              <div key={k}>
                <dt className="font-mono text-[11px] text-muted-foreground">{k}</dt>
                <dd className="leading-relaxed">{record[k] as string}</dd>
              </div>
            ))}
          </dl>
        </Section>
      )}

      {s.measures.length > 0 && (
        <Section title="Measures">
          <Measures measures={s.measures} />
        </Section>
      )}

      {s.entities.length > 0 && (
        <Section title="Reported entities and routes">
          <ul className="space-y-1 text-sm">
            {s.entities.map((e) => (
              <li key={e.value} className="flex gap-2">
                <span className="w-44 shrink-0 truncate font-mono text-[11px] leading-5 text-muted-foreground">{e.field}</span>
                <span>{e.value}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Verification and limitations">
        <Badge variant="outline" className="h-auto whitespace-normal py-0.5 text-left font-normal">{humanise(s.verification_status)}</Badge>
        {s.limitations.length > 0 ? (
          <ul className="space-y-1.5 text-sm">
            {s.limitations.map((l, i) => (
              <li key={i} className="flex gap-2">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-500" />
                <span className="leading-relaxed">{l}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No limitations recorded.</p>
        )}
      </Section>

      <Section title="Source">
        <dl className="grid grid-cols-[minmax(0,8rem)_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Publisher</dt>
          <dd>{source.publisher ?? '—'}</dd>
          <dt className="text-muted-foreground">Published</dt>
          <dd>{dateLabel(source.published_at)}</dd>
          <dt className="text-muted-foreground">Retrieved</dt>
          <dd>{dateLabel(source.retrieved_at)}</dd>
          <dt className="text-muted-foreground">Licence</dt>
          <dd className="text-muted-foreground">{source.licence_notes ?? '—'}</dd>
        </dl>
        {source.url && (
          <a href={source.url} target="_blank" rel="noreferrer noopener" className="inline-flex max-w-full items-center gap-1.5 text-sm text-primary hover:underline">
            <ExternalLink className="size-3.5 shrink-0" />
            <span className="truncate">{source.url}</span>
          </a>
        )}
      </Section>

      <Section title="Graph Explorer">
        {data.graph_error ? (
          <p className="text-sm text-muted-foreground">The supplier list could not be read from Neo4j, so this link is unavailable.</p>
        ) : data.graph_suppliers.length ? (
          <>
            <p className="text-sm text-muted-foreground">
              {data.graph_suppliers.length} supplier node{data.graph_suppliers.length === 1 ? '' : 's'} with a reported country of{' '}
              {graphCountries.join(', ')}. The match is by country only; the record names no graph supplier.
            </p>
            <ul className="flex flex-wrap gap-1">
              {data.graph_suppliers.map((g) => (
                <li key={g.id}><Badge variant="secondary" className="font-normal">{g.name}</Badge></li>
              ))}
            </ul>
            <Button size="sm" variant="outline" onClick={() => navigate(explorerHref(data.graph_suppliers.map((g) => g.id)))}>
              <Network className="size-4" /> Show in Graph Explorer
            </Button>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            {graphCountries.length
              ? `No supplier in the graph reports ${graphCountries.join(', ')} as its country.`
              : 'No supplier-side country is recorded, so there is no graph link.'}
          </p>
        )}
      </Section>

      {data.related.length > 0 && (
        <Section title={`Related evidence (${data.related.length})`}>
          <EvidenceLinks items={data.related} search={search} />
        </Section>
      )}
      {data.incident_group.length > data.related.length && (
        <Section title="Same incident group">
          <p className="text-xs text-muted-foreground">Connected through related links (group {data.incident_group_id}).</p>
          <EvidenceLinks items={data.incident_group.filter((g) => !data.related.some((r) => r.evidence_id === g.evidence_id))} search={search} />
        </Section>
      )}

      <Section title="All stored fields">
        <details className="group rounded-md border">
          <summary className="cursor-pointer px-3 py-2 text-sm text-muted-foreground hover:text-foreground">
            {others.length} fields as stored
          </summary>
          <dl className="space-y-2 border-t p-3 text-xs">
            {others.map(([k, v]) => (
              <div key={k} className="grid grid-cols-[minmax(0,10rem)_1fr] gap-3">
                <dt className="truncate font-mono text-muted-foreground" title={k}>{k}</dt>
                <dd className="min-w-0"><Value value={v} /></dd>
              </div>
            ))}
          </dl>
        </details>
        <details className="rounded-md border">
          <summary className="cursor-pointer px-3 py-2 text-sm text-muted-foreground hover:text-foreground">Raw JSON</summary>
          <pre className="max-h-96 overflow-auto border-t bg-muted/30 p-3 text-[11px] leading-relaxed">{JSON.stringify(record, null, 2)}</pre>
        </details>
        <p className="font-mono text-[10px] text-muted-foreground">engine {data.engine_version} · {data.data_snapshot_id}</p>
      </Section>
    </div>
  )
}

export function EvidenceDetailPanel({ id, search }: { id: string; search: string }) {
  const q = useEvidenceRecord(id)
  if (q.isPending) {
    return (
      <div className="space-y-3 px-5">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }
  if (q.isError) {
    const notFound = q.error instanceof ApiError && q.error.status === 404
    return (
      <div className="px-5 text-sm">
        <p className="font-medium">{notFound ? 'No such evidence record' : 'Could not load this record'}</p>
        <p className="mt-1 text-muted-foreground">{notFound ? <>There is no record with id <span className="font-mono">{id}</span>.</> : q.error.message}</p>
      </div>
    )
  }
  return <DetailBody data={q.data} search={search} />
}
