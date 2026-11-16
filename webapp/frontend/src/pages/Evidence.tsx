/**
 * Risk Library: the engine's stored records, organised as a drill-down.
 *
 *   1. Overview: four risk groups, each with a tile per risk type (count,
 *      countries, date span). A text search with no type chosen shows the
 *      matches grouped under their risk type instead.
 *   2. Risk type (?type=…): that type's record cards, with its sibling types
 *      one click away.
 *   3. Record (/evidence/:id): the detail panel over whichever list is open.
 *
 * Filters (type, country, date overlap, text) live in the URL. Choosing a type
 * pushes a history entry, so the browser's back button steps back up a level.
 * Risk Assessment citation chips link to /evidence/:id.
 */
import { BookOpenText, ChevronRight, Search, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { EvidenceCard } from '@/components/evidence/EvidenceCard'
import { EvidenceDetailPanel } from '@/components/evidence/EvidenceDetail'
import { PageContainer } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import {
  RISK_BLURB, RISK_GROUPS, riskGroup, useEvidenceList,
  type EvidenceFilters, type EvidenceSummary, type Facet, type RiskGroup,
} from '@/lib/evidence'
import { dateLabel, fmt, monthLabel, plural } from '@/lib/format'
import { cn } from '@/lib/utils'

const ALL = '__all__'

function FacetSelect({
  value, facets, onChange, placeholder, allLabel, width,
}: { value: string | null; facets: Facet[]; onChange: (v: string | null) => void; placeholder: string; allLabel: string; width: string }) {
  return (
    <Select value={value ?? ALL} onValueChange={(v) => onChange(v === ALL ? null : v)}>
      <SelectTrigger className={width} aria-label={placeholder}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{allLabel}</SelectItem>
        {facets.map((f) => (
          <SelectItem key={f.value} value={f.value} disabled={f.count === 0 && f.value !== value}>
            <span className="flex-1">{f.label}</span>
            <span className="ml-3 text-xs tabular-nums text-muted-foreground">{f.count}</span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/* ---------------------------------------------------------------- stats */

interface TypeStats {
  count: number
  countries: number
  from: string | null
  to: string | null
}

/** Count, distinct countries and the overall date span (undated records are left out of the span). */
function statsOf(records: EvidenceSummary[]): TypeStats {
  const countries = new Set<string>()
  let from: string | null = null
  let to: string | null = null
  for (const r of records) {
    for (const c of r.countries) countries.add(c.code)
    const { start, end, undated } = r.dates
    if (undated || !start) continue
    const last = end ?? start
    if (!from || start < from) from = start
    if (!to || last > to) to = last
  }
  return { count: records.length, countries: countries.size, from, to }
}

function spanLabel(s: TypeStats): string | null {
  if (!s.from) return null
  const a = monthLabel(s.from.slice(0, 7))
  const b = s.to ? monthLabel(s.to.slice(0, 7)) : a
  return a === b ? a : `${a} – ${b}`
}

function StatLine({ stats, className }: { stats: TypeStats; className?: string }) {
  const span = spanLabel(stats)
  return (
    <div className={cn('flex flex-wrap gap-x-2 text-xs text-muted-foreground', className)}>
      <span>{stats.countries ? plural(stats.countries, 'country', 'countries') : 'No country recorded'}</span>
      {span && <><span aria-hidden>·</span><span className="tabular-nums">{span}</span></>}
    </div>
  )
}

const Dot = ({ group, className }: { group: RiskGroup; className?: string }) => (
  <span className={cn('inline-block size-2 shrink-0 rounded-full', group.dot, className)} />
)

/* ---------------------------------------------------------------- page */

export default function Evidence() {
  const { id } = useParams<{ id?: string }>()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const { search } = useLocation()

  const filters: EvidenceFilters = useMemo(
    () => ({
      risk_type: params.get('type'),
      country: params.get('country'),
      date_from: params.get('from'),
      date_to: params.get('to'),
      q: params.get('q'),
    }),
    [params],
  )
  const list = useEvidenceList(filters)

  const setParam = (patch: Record<string, string | null>) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p)
        for (const [k, v] of Object.entries(patch)) {
          if (v == null || v === '') next.delete(k)
          else next.set(k, v)
        }
        return next
      },
      { replace: true },
    )

  /** "?…" for the list page with `type` set (or cleared), keeping the other filters. */
  const typeSearch = (type: string | null) => {
    const next = new URLSearchParams(params)
    if (type) next.set('type', type)
    else next.delete('type')
    const s = next.toString()
    return s ? `?${s}` : ''
  }

  // The search box writes to the URL after a short pause.
  const [text, setText] = useState(filters.q ?? '')
  useEffect(() => setText(filters.q ?? ''), [filters.q])
  useEffect(() => {
    const t = setTimeout(() => {
      if ((filters.q ?? '') !== text.trim()) setParam({ q: text.trim() || null })
    }, 250)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text])

  const otherFilter = !!(filters.country || filters.date_from || filters.date_to || filters.q)
  const data = list.data
  const studyWindow = data?.study_window
  const typeCounts = useMemo(
    () => Object.fromEntries((data?.facets.risk_type ?? []).map((f) => [f.value, f])),
    [data],
  )

  const selected = filters.risk_type?.split(',').filter(Boolean) ?? []
  const single = selected.length === 1 ? selected[0] : null
  const mode: 'overview' | 'search' | 'type' = selected.length ? 'type' : filters.q ? 'search' : 'overview'

  // Records grouped by type, in group order (used by the overview tiles and the grouped search view).
  const byType = useMemo(() => {
    const m = new Map<string, EvidenceSummary[]>()
    for (const r of data?.records ?? []) {
      const arr = m.get(r.risk_type)
      if (arr) arr.push(r)
      else m.set(r.risk_type, [r])
    }
    return m
  }, [data])

  const close = () => navigate({ pathname: '/evidence', search }, { replace: false })
  const recordHref = (rid: string) => `/evidence/${encodeURIComponent(rid)}${search}`
  const dimmed = list.isPlaceholderData ? 'opacity-60' : ''

  const cardGrid = (records: EvidenceSummary[], hideType: boolean) => (
    <div className={cn('grid gap-3 sm:grid-cols-2 xl:grid-cols-3', dimmed)}>
      {records.map((r) => (
        <EvidenceCard key={r.evidence_id} record={r} href={recordHref(r.evidence_id)} active={r.evidence_id === id} hideType={hideType} />
      ))}
    </div>
  )

  return (
    <PageContainer className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <BookOpenText className="size-5 text-muted-foreground" /> Risk Library
          </h1>
          <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">
            The supplier risk evidence engine's stored records, sorted by risk type. Pick a risk type to see its
            records, then open a record for its full source, dates and limitations. Risk Assessment cites these
            records by id.
          </p>
        </div>
        {data && (
          <div className="text-right text-xs text-muted-foreground">
            <div>
              <span className="text-sm font-medium tabular-nums text-foreground">{data.count}</span> of {plural(data.total, 'record')}
            </div>
            {studyWindow && <div>Study window {dateLabel(studyWindow.start)} – {dateLabel(studyWindow.end)}</div>}
          </div>
        )}
      </header>

      <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-card p-3">
        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Search id, title, entities, publisher…"
            className="pl-8"
            aria-label="Search evidence"
          />
        </div>
        <FacetSelect
          value={filters.country}
          facets={data?.facets.country ?? []}
          onChange={(v) => setParam({ country: v })}
          placeholder="Country"
          allLabel="All countries"
          width="w-44"
        />
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Input
            type="date"
            value={filters.date_from ?? ''}
            max={filters.date_to ?? undefined}
            onChange={(e) => setParam({ from: e.target.value || null })}
            className="w-36"
            aria-label="From date"
          />
          <span>to</span>
          <Input
            type="date"
            value={filters.date_to ?? ''}
            min={filters.date_from ?? undefined}
            onChange={(e) => setParam({ to: e.target.value || null })}
            className="w-36"
            aria-label="To date"
          />
        </div>
        {otherFilter && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => { setText(''); setParam({ country: null, from: null, to: null, q: null }) }}
          >
            <X className="size-4" /> Clear filters
          </Button>
        )}
      </div>
      {(filters.date_from || filters.date_to) && (
        <p className="-mt-2 text-xs text-muted-foreground">
          Keeps records whose date range overlaps the chosen range. A record with no end date counts as one day; an
          effective interval with no end stays in force to the end of the study window; an undated record uses its search window.
        </p>
      )}

      {/* Breadcrumb: where you are, and one click back up. */}
      <nav aria-label="Evidence level" className="flex flex-wrap items-center gap-1 text-sm">
        {mode === 'type' ? (
          <Link to={{ pathname: '/evidence', search: typeSearch(null) }} className="text-muted-foreground hover:text-foreground hover:underline">
            All risk types
          </Link>
        ) : (
          <span className="font-medium">{mode === 'search' ? 'Search results by risk type' : 'All risk types'}</span>
        )}
        {mode === 'type' && single && (
          <>
            <ChevronRight className="size-3.5 text-muted-foreground" />
            <span className="text-muted-foreground">{riskGroup(single).label}</span>
            <ChevronRight className="size-3.5 text-muted-foreground" />
            <span className="font-medium">{typeCounts[single]?.label ?? single}</span>
          </>
        )}
        {mode === 'type' && !single && (
          <>
            <ChevronRight className="size-3.5 text-muted-foreground" />
            <span className="font-medium">{plural(selected.length, 'risk type')}</span>
          </>
        )}
      </nav>

      {list.isError && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm">
          Could not load evidence: {list.error.message}
        </div>
      )}

      {list.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-28 rounded-xl" />)}
        </div>
      ) : !data ? null : mode === 'overview' ? (
        /* ---------------- Level 1: groups → risk type tiles */
        <div className={cn('space-y-7', dimmed)}>
          {RISK_GROUPS.map((g) => {
            const groupTotal = g.types.reduce((n, t) => n + (typeCounts[t]?.count ?? 0), 0)
            return (
              <section key={g.key} aria-labelledby={`grp-${g.key}`}>
                <div className="mb-2.5 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                  <h2 id={`grp-${g.key}`} className="flex items-center gap-2 text-sm font-semibold">
                    <Dot group={g} /> {g.label}
                  </h2>
                  <span className="text-xs text-muted-foreground">{g.blurb}</span>
                  <span className="ml-auto text-xs tabular-nums text-muted-foreground">{plural(groupTotal, 'record')}</span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {g.types.map((t) => {
                    const count = typeCounts[t]?.count ?? 0
                    const label = typeCounts[t]?.label ?? t
                    const stats = statsOf(byType.get(t) ?? [])
                    const body = (
                      <>
                        <div className="flex items-start justify-between gap-3">
                          <h3 className="text-sm font-medium leading-snug">{label}</h3>
                          <span className="text-xl font-semibold leading-none tabular-nums">{fmt(count)}</span>
                        </div>
                        <p className="text-xs leading-relaxed text-muted-foreground">{RISK_BLURB[t]}</p>
                        {count > 0 ? (
                          <div className="mt-auto flex items-end justify-between gap-2 pt-1">
                            <StatLine stats={stats} />
                            <ChevronRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                          </div>
                        ) : (
                          <div className="mt-auto pt-1 text-xs italic text-muted-foreground">
                            {otherFilter ? 'No records match these filters' : 'No records yet'}
                          </div>
                        )}
                      </>
                    )
                    const base = 'flex flex-col gap-1.5 rounded-xl border bg-card p-4 text-card-foreground'
                    return count > 0 ? (
                      <Link
                        key={t}
                        to={{ pathname: '/evidence', search: typeSearch(t) }}
                        className={cn(base, 'group transition-colors hover:border-primary/40 hover:bg-muted/30')}
                      >
                        {body}
                      </Link>
                    ) : (
                      <div key={t} className={cn(base, 'opacity-50')}>{body}</div>
                    )
                  })}
                </div>
              </section>
            )
          })}
        </div>
      ) : data.records.length === 0 ? (
        <div className="rounded-xl border border-dashed px-6 py-12 text-center text-sm text-muted-foreground">
          No records match these filters.
        </div>
      ) : mode === 'search' ? (
        /* ---------------- Search with no type: matches grouped by risk type */
        <div className="space-y-7">
          {RISK_GROUPS.flatMap((g) => g.types).filter((t) => byType.has(t)).map((t) => {
            const records = byType.get(t)!
            return (
              <section key={t} aria-labelledby={`type-${t}`}>
                <Link
                  to={{ pathname: '/evidence', search: typeSearch(t) }}
                  className="group mb-2.5 flex w-fit items-center gap-2 text-sm font-semibold hover:underline"
                  id={`type-${t}`}
                >
                  <Dot group={riskGroup(t)} /> {records[0].risk_label}
                  <span className="font-normal text-muted-foreground">· {fmt(records.length)}</span>
                  <ChevronRight className="size-3.5 text-muted-foreground" />
                </Link>
                {cardGrid(records, true)}
              </section>
            )
          })}
        </div>
      ) : (
        /* ---------------- Level 2: one risk type's records */
        <div className="space-y-4">
          {single && (
            <TypeHeader
              type={single}
              label={typeCounts[single]?.label ?? single}
              stats={statsOf(data.records)}
              siblings={riskGroup(single).types
                .filter((t) => t !== single)
                .map((t) => ({ type: t, label: typeCounts[t]?.label ?? t, count: typeCounts[t]?.count ?? 0 }))}
              siblingHref={typeSearch}
            />
          )}
          {cardGrid(data.records, !!single)}
        </div>
      )}

      <Sheet open={!!id} onOpenChange={(open) => !open && close()}>
        <SheetContent className="w-full gap-0 overflow-y-auto data-[side=right]:sm:max-w-xl">
          <div className="px-5 pt-5 pb-3">
            <SheetTitle className="sr-only">Evidence record {id}</SheetTitle>
            <SheetDescription className="text-xs">Evidence record</SheetDescription>
          </div>
          {id && <EvidenceDetailPanel id={id} search={search} />}
        </SheetContent>
      </Sheet>
    </PageContainer>
  )
}

function TypeHeader({
  type, label, stats, siblings, siblingHref,
}: {
  type: string
  label: string
  stats: TypeStats
  siblings: { type: string; label: string; count: number }[]
  siblingHref: (t: string) => string
}) {
  const group = riskGroup(type)
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <Dot group={group} /> {label}
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">{RISK_BLURB[type]}</p>
        </div>
        <div className="text-right">
          <div className="text-xl font-semibold leading-none tabular-nums">{fmt(stats.count)}</div>
          <StatLine stats={stats} className="mt-1 justify-end" />
        </div>
      </div>
      {siblings.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t pt-3">
          <span className="mr-1 text-xs text-muted-foreground">Also in {group.label.toLowerCase()}:</span>
          {siblings.map((s) =>
            s.count > 0 ? (
              <Link
                key={s.type}
                to={{ pathname: '/evidence', search: siblingHref(s.type) }}
                className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition-colors hover:border-primary/40 hover:bg-muted/40"
              >
                {s.label} <span className="tabular-nums text-muted-foreground">{s.count}</span>
              </Link>
            ) : (
              <span key={s.type} className="inline-flex items-center gap-1.5 rounded-full border border-dashed px-2.5 py-0.5 text-xs text-muted-foreground">
                {s.label} <span className="tabular-nums">0</span>
              </span>
            ),
          )}
        </div>
      )}
    </div>
  )
}
