/**
 * Evidence Library: the engine's stored records as cards. Filters (risk type,
 * country, date overlap, text) live in the URL, and each record has its own
 * address (/evidence/:id) that opens it in a panel over the filtered list.
 * Risk Assessment citation chips will link here.
 */
import { BookOpenText, Search, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { EvidenceCard } from '@/components/evidence/EvidenceCard'
import { EvidenceDetailPanel } from '@/components/evidence/EvidenceDetail'
import { PageContainer } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { useEvidenceList, type EvidenceFilters, type Facet } from '@/lib/evidence'
import { dateLabel, plural } from '@/lib/format'

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

  const anyFilter = Object.values(filters).some(Boolean)
  const data = list.data
  const studyWindow = data?.study_window

  const close = () => navigate({ pathname: '/evidence', search }, { replace: false })

  return (
    <PageContainer className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <BookOpenText className="size-5 text-muted-foreground" /> Evidence Library
          </h1>
          <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">
            The supplier risk evidence engine's stored records. Each card shows its own date fields, source and
            limitations. Risk Assessment cites these records by id.
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
          value={filters.risk_type}
          facets={data?.facets.risk_type ?? []}
          onChange={(v) => setParam({ type: v })}
          placeholder="Risk type"
          allLabel="All risk types"
          width="w-56"
        />
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
        {anyFilter && (
          <Button variant="ghost" size="sm" onClick={() => { setText(''); setParams({}, { replace: true }) }}>
            <X className="size-4" /> Clear
          </Button>
        )}
      </div>
      {(filters.date_from || filters.date_to) && (
        <p className="-mt-2 text-xs text-muted-foreground">
          Keeps records whose date range overlaps the chosen range. A record with no end date counts as one day; an
          effective interval with no end stays in force to the end of the study window; an undated record uses its search window.
        </p>
      )}

      {list.isError && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm">
          Could not load evidence: {list.error.message}
        </div>
      )}

      {list.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 9 }, (_, i) => <Skeleton key={i} className="h-64 rounded-xl" />)}
        </div>
      ) : data && data.records.length === 0 ? (
        <div className="rounded-xl border border-dashed px-6 py-12 text-center text-sm text-muted-foreground">
          No records match these filters.
        </div>
      ) : (
        <div className={`grid gap-3 sm:grid-cols-2 xl:grid-cols-3 ${list.isPlaceholderData ? 'opacity-60' : ''}`}>
          {data?.records.map((r) => (
            <EvidenceCard
              key={r.evidence_id}
              record={r}
              href={`/evidence/${encodeURIComponent(r.evidence_id)}${search}`}
              active={r.evidence_id === id}
            />
          ))}
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
