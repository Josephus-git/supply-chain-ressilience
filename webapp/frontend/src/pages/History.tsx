/**
 * Run History: every saved run, compared by model arm (EVALUATION_PLAN §2.2, §2.11, §4).
 *
 * Shows only the automatic measures that each run file already records: status, refusals
 * forced by the pipeline (R7) versus by the model (R6), the citation check (B1 verified
 * share; C1 not found, wrong scope, uncited claims), ranked candidates and tokens.
 * Human-labelled measures (B2, C2, D1) come from the labelling sheets and are not shown.
 *
 * Two groups: pilot runs (trial runs before the evaluation, made by hand in the app or
 * with the batch runner) and evaluation runs (runs/evaluation/, the evaluation itself).
 * Runs saved before the current pipeline (R26, 27 Nov) are hidden unless asked for.
 */
import { useQuery } from '@tanstack/react-query'
import { History as HistoryIcon, Info } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { StatusBadge } from '@/components/ask/parts'
import { AssessStatusBadge } from '@/components/assess/History'
import { PageContainer } from '@/components/layout/AppShell'
import { ArmBadge } from '@/components/models/ModelPicker'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { getJson } from '@/lib/api'
import type { RunStatus } from '@/lib/ask'
import type { AssessStatus } from '@/lib/assess'
import { dateLabel, fmt } from '@/lib/format'
import { ARM_TONE, type ArmId, type ArmInfo } from '@/lib/models'
import { cn } from '@/lib/utils'

type Source = 'pilot' | 'evaluation'
type Kind = 'assess' | 'ask'

interface RunRow {
  run_id: string
  kind: Kind
  source: Source
  made_by: 'app' | 'runner'
  current_pipeline: boolean
  started_at: string | null
  status: string
  error: string | null
  arm: ArmId | null
  models_served: string[]
  set: string | null
  query_id: string | null
  repeat: number | null
  tokens: number | null
  calls: number | null
  title: string | null
  model: string | null
  // assess
  goal?: string | null
  items?: string[]
  as_of_date?: string | null
  answered_by?: 'llm' | 'pipeline' | null
  item_status?: string[]
  ranked?: number[]
  citations?: { total: number; verified: number; not_found: number; with_note: number; uncited: number } | null
  graph_off?: boolean
  // ask
  rows?: number | null
  attempts?: number
  gold_compare?: string | null
  gold_rows?: number | null
}

const ARMS: ArmId[] = ['M1', 'M2', 'M3']
const SOURCE_LABEL: Record<Source, string> = { pilot: 'Pilot', evaluation: 'Evaluation' }

const useHistory = () =>
  useQuery({
    queryKey: ['history'],
    queryFn: ({ signal }) => getJson<{ runs: RunRow[]; arms: ArmInfo[] }>('/history', {}, signal),
    refetchInterval: 30_000,
  })

const pct = (n: number, d: number) => (d ? `${Math.round((100 * n) / d)}%` : '—')
const mean = (xs: number[]) => (xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) / xs.length) : null)
const href = (r: RunRow) => (r.kind === 'ask' ? `/ask?run=${encodeURIComponent(r.run_id)}` : `/assess?run=${encodeURIComponent(r.run_id)}`)
const queryKey = (r: RunRow) => r.query_id ? `${r.kind}:${r.query_id}` : `${r.kind}:${(r.title ?? '').toLowerCase()}|${r.as_of_date ?? ''}`

function RunStatusBadge({ r }: { r: RunRow }) {
  return r.kind === 'ask'
    ? <StatusBadge status={r.status as RunStatus} className="px-1.5 py-0 text-[10px]" />
    : <AssessStatusBadge status={r.status as AssessStatus} className="px-1.5 py-0 text-[10px]" />
}

// ---------------------------------------------------------------------------- per-model measures

interface Measure { label: string; hint: string; value: (rs: RunRow[]) => string }

const ASSESS_MEASURES: Measure[] = [
  { label: 'Runs', hint: 'Risk Assessment runs in view', value: (rs) => fmt(rs.length) },
  { label: 'Answered', hint: 'At least one item answered at supplier level', value: (rs) => `${rs.filter((r) => r.status === 'answered').length} (${pct(rs.filter((r) => r.status === 'answered').length, rs.length)})` },
  { label: 'Country level', hint: 'No supplier ranked; country-level evidence only (R4)', value: (rs) => fmt(rs.filter((r) => r.status === 'country_level').length) },
  { label: 'Not enough data: pipeline', hint: 'Nothing relevant found, so the fixed answer was returned and no model was called (R7)', value: (rs) => fmt(rs.filter((r) => r.status === 'insufficient_data' && r.answered_by === 'pipeline').length) },
  { label: 'Not enough data: model', hint: 'The model itself declined (R6)', value: (rs) => fmt(rs.filter((r) => r.status === 'insufficient_data' && r.answered_by === 'llm').length) },
  { label: 'Failed', hint: 'No readable answer (kept and reported, §2.5)', value: (rs) => fmt(rs.filter((r) => r.status === 'failed').length) },
  {
    label: 'Citations verified (B1)', hint: 'Cited ids that were given to the model, out of all citations',
    value: (rs) => {
      const v = rs.reduce((a, r) => a + (r.citations?.verified ?? 0), 0)
      const t = rs.reduce((a, r) => a + (r.citations?.total ?? 0), 0)
      return `${pct(v, t)} (${fmt(v)}/${fmt(t)})`
    },
  },
  { label: 'Cited but never given', hint: 'Citation ids the model was not given (flagged not_found)', value: (rs) => fmt(rs.reduce((a, r) => a + (r.citations?.not_found ?? 0), 0)) },
  { label: 'Wrong scope (C1)', hint: 'Given to the model, but for another supplier, item or country (R18)', value: (rs) => fmt(rs.reduce((a, r) => a + (r.citations?.with_note ?? 0), 0)) },
  { label: 'Claims without a citation (C1)', hint: 'Claims with no citation at all', value: (rs) => fmt(rs.reduce((a, r) => a + (r.citations?.uncited ?? 0), 0)) },
  { label: 'Ranked per item (mean)', hint: 'Candidates the model ranked, per answered item', value: (rs) => { const xs = rs.flatMap((r) => r.ranked ?? []); return xs.length ? (xs.reduce((a, b) => a + b, 0) / xs.length).toFixed(1) : '—' } },
  { label: 'Tokens per run (mean)', hint: 'Model calls only; runs answered by the pipeline use none', value: (rs) => fmt(mean(rs.map((r) => r.tokens ?? 0))) },
]

const ASK_MEASURES: Measure[] = [
  { label: 'Runs', hint: 'Ask the Graph runs in view', value: (rs) => fmt(rs.length) },
  { label: 'Answered', hint: 'The query ran and returned rows', value: (rs) => fmt(rs.filter((r) => r.status === 'answered').length) },
  { label: 'No rows / failed', hint: 'No rows after the retry, or no valid query', value: (rs) => `${rs.filter((r) => r.status === 'no_rows').length} / ${rs.filter((r) => r.status === 'failed').length}` },
  { label: 'Needed the retry', hint: 'Second attempt used (A4)', value: (rs) => fmt(rs.filter((r) => (r.attempts ?? 0) > 1).length) },
  { label: 'Same row count as gold', hint: 'Gold-set runs only. Indicative: execution accuracy compares the rows themselves, in the notebook', value: (rs) => { const g = rs.filter((r) => r.gold_rows != null && r.gold_compare !== 'refusal'); return g.length ? `${g.filter((r) => r.rows === r.gold_rows).length} of ${g.length}` : '—' } },
  { label: 'Tokens per run (mean)', hint: 'Both calls: Cypher and answer', value: (rs) => fmt(mean(rs.map((r) => r.tokens ?? 0))) },
]

function MeasuresTable({ runs, kind, arms }: { runs: RunRow[]; kind: Kind; arms: ArmId[] }) {
  const measures = kind === 'assess' ? ASSESS_MEASURES : ASK_MEASURES
  const byArm = Object.fromEntries(arms.map((a) => [a, runs.filter((r) => r.arm === a)])) as Record<ArmId, RunRow[]>
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Measure</th>
            {arms.map((a) => <th key={a} className="px-3 py-2 text-right font-medium"><ArmBadge arm={a} /></th>)}
          </tr>
        </thead>
        <tbody>
          {measures.map((m) => (
            <tr key={m.label} className="border-t">
              <td className="px-3 py-1.5" title={m.hint}>
                <div>{m.label}</div>
                <div className="text-[10.5px] text-muted-foreground">{m.hint}</div>
              </td>
              {arms.map((a) => <td key={a} className="px-3 py-1.5 text-right tabular">{byArm[a].length ? m.value(byArm[a]) : '—'}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------- same query, each model

function Cell({ r }: { r: RunRow | undefined }) {
  if (!r) return <span className="text-xs text-muted-foreground">not run</span>
  const c = r.citations
  return (
    <Link to={href(r)} className="block rounded-md px-1.5 py-1 hover:bg-muted/60">
      <div className="flex flex-wrap items-center gap-1.5">
        <RunStatusBadge r={r} />
        {r.answered_by === 'pipeline' && <span className="text-[10px] text-muted-foreground">no model call</span>}
      </div>
      <div className="mt-0.5 text-[11px] text-muted-foreground tabular">
        {r.kind === 'assess' && c && c.total > 0 && <span className={cn(c.not_found > 0 && 'text-red-700 dark:text-red-400')}>{c.verified}/{c.total} cited ok · </span>}
        {r.kind === 'assess' && (r.ranked ?? []).some((n) => n > 0) && <span>ranked {r.ranked!.join('+')} · </span>}
        {r.kind === 'ask' && r.rows != null && <span>{r.rows} rows{r.gold_rows != null ? ` (gold ${r.gold_rows})` : ''} · </span>}
        {fmt(r.tokens)} tok
      </div>
    </Link>
  )
}

function CompareTable({ runs, arms }: { runs: RunRow[]; arms: ArmId[] }) {
  const groups = useMemo(() => {
    const m = new Map<string, { key: string; first: RunRow; byArm: Partial<Record<ArmId, RunRow>> }>()
    for (const r of runs) {
      if (!r.arm) continue
      const k = queryKey(r)
      const g = m.get(k) ?? { key: k, first: r, byArm: {} }
      if (!g.byArm[r.arm]) g.byArm[r.arm] = r // newest first, so the latest run per arm
      m.set(k, g)
    }
    return [...m.values()]
      .filter((g) => Object.keys(g.byArm).length >= 2)
      .sort((a, b) => (a.first.query_id ?? a.key).localeCompare(b.first.query_id ?? b.key))
  }, [runs])
  if (!groups.length) return <p className="rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground">No query has been run on two or more models yet.</p>
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Query</th>
            {arms.map((a) => <th key={a} className="px-3 py-2 text-left font-medium"><ArmBadge arm={a} /></th>)}
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <tr key={g.key} className="border-t align-top">
              <td className="max-w-80 px-3 py-2">
                <div className="flex items-baseline gap-1.5">
                  {g.first.query_id && <span className="font-mono text-[11px] text-muted-foreground">{g.first.query_id}</span>}
                  <span className="line-clamp-2 text-[13px]">{g.first.title}</span>
                </div>
                {g.first.as_of_date && <div className="text-[11px] text-muted-foreground">as of {dateLabel(g.first.as_of_date)}</div>}
              </td>
              {arms.map((a) => <td key={a} className="px-2 py-1.5"><Cell r={g.byArm[a]} /></td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------- every run

function RunsTable({ runs }: { runs: RunRow[] }) {
  const [shown, setShown] = useState(50)
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">When</th>
              <th className="px-3 py-2 text-left font-medium">Model</th>
              <th className="px-3 py-2 text-left font-medium">Source</th>
              <th className="px-3 py-2 text-left font-medium">Request</th>
              <th className="px-3 py-2 text-left font-medium">Status</th>
              <th className="px-3 py-2 text-right font-medium">Citations ok</th>
              <th className="px-3 py-2 text-right font-medium">Tokens</th>
            </tr>
          </thead>
          <tbody>
            {runs.slice(0, shown).map((r) => (
              <tr key={`${r.source}:${r.run_id}`} className="border-t hover:bg-muted/30">
                <td className="px-3 py-1.5 text-xs whitespace-nowrap text-muted-foreground tabular">{r.started_at ? new Date(r.started_at).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'}</td>
                <td className="px-3 py-1.5"><ArmBadge arm={r.arm} model={r.model} /></td>
                <td className="px-3 py-1.5 text-xs">
                  {SOURCE_LABEL[r.source]}
                  {r.source === 'pilot' && <span className="text-muted-foreground"> · {r.made_by === 'app' ? 'in the app' : 'runner'}</span>}
                  {!r.current_pipeline && <span className="text-amber-700 dark:text-amber-400"> · older pipeline</span>}
                  {r.set && <span className="text-muted-foreground"> · {r.set}{r.repeat ? ` r${r.repeat}` : ''}</span>}
                </td>
                <td className="max-w-96 px-3 py-1.5">
                  <Link to={href(r)} className="hover:underline">
                    <span className="mr-1.5 text-[10px] font-medium text-muted-foreground uppercase">{r.kind === 'ask' ? 'Ask' : 'Assess'}</span>
                    {r.query_id && <span className="mr-1 font-mono text-[11px] text-muted-foreground">{r.query_id}</span>}
                    <span className="line-clamp-1 inline">{r.title}</span>
                  </Link>
                  {r.as_of_date && <div className="text-[11px] text-muted-foreground">as of {dateLabel(r.as_of_date)}{r.graph_off ? ' · graph off' : ''}</div>}
                </td>
                <td className="px-3 py-1.5"><RunStatusBadge r={r} /></td>
                <td className="px-3 py-1.5 text-right text-xs tabular">{r.citations && r.citations.total ? `${r.citations.verified}/${r.citations.total}` : '—'}</td>
                <td className="px-3 py-1.5 text-right text-xs tabular">{fmt(r.tokens)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {runs.length > shown && (
        <button type="button" className="text-xs text-muted-foreground hover:text-foreground hover:underline" onClick={() => setShown((n) => n + 100)}>
          Show more ({runs.length - shown} left)
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------- page

export default function History() {
  const q = useHistory()
  const [kind, setKind] = useState<Kind>('assess')
  const [sources, setSources] = useState<Source[]>(['pilot', 'evaluation'])
  // Runs from before the current pipeline (e.g. the 16 Nov runs, whose candidates came from an
  // LLM-written query) would skew the comparison, so they are hidden by default.
  const [showOlder, setShowOlder] = useState(false)
  const [arms, setArms] = useState<ArmId[]>(ARMS)

  const all = useMemo(() => q.data?.runs ?? [], [q.data])
  const counts = useMemo(() => {
    const c: Record<Source, number> = { pilot: 0, evaluation: 0 }
    for (const r of all) if (showOlder || r.current_pipeline) c[r.source] += 1
    return c
  }, [all, showOlder])
  const older = all.filter((r) => !r.current_pipeline).length
  const runs = all.filter((r) => r.kind === kind && sources.includes(r.source) && (showOlder || r.current_pipeline) && (!r.arm || arms.includes(r.arm)))
  const shownArms = ARMS.filter((a) => arms.includes(a))

  return (
    <PageContainer>
      <div className="space-y-6">
        <div className="space-y-1">
          <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><HistoryIcon className="size-5" /> Run History</h2>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Every saved run, compared by model. M1 is OpenAI gpt-5.2 (the baseline), M2 DeepSeek V4.1 Flash (open weights, through its
            API) and M3 Claude Sonnet 5.5; all three run without thinking, with the same prompts, evidence and limits. For a parts list,
            candidates come from the same product matching for every model, so differences here come from the model.
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-4 rounded-xl border bg-card p-3 shadow-xs">
          <div className="space-y-1">
            <div className="text-xs font-medium text-muted-foreground">Pipeline</div>
            <ToggleGroup type="single" variant="outline" size="sm" value={kind} onValueChange={(v) => v && setKind(v as Kind)}>
              <ToggleGroupItem value="assess">Risk Assessment</ToggleGroupItem>
              <ToggleGroupItem value="ask">Ask the Graph</ToggleGroupItem>
            </ToggleGroup>
          </div>
          <div className="space-y-1">
            <div className="text-xs font-medium text-muted-foreground">Where the runs come from</div>
            <ToggleGroup type="multiple" variant="outline" size="sm" value={sources} onValueChange={(v) => setSources(v as Source[])}>
              {(['pilot', 'evaluation'] as Source[]).map((s) => (
                <ToggleGroupItem key={s} value={s}>{SOURCE_LABEL[s]} <span className="text-muted-foreground tabular">{counts[s]}</span></ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
          <div className="space-y-1">
            <div className="text-xs font-medium text-muted-foreground">Models</div>
            <ToggleGroup type="multiple" variant="outline" size="sm" value={arms} onValueChange={(v) => setArms(v as ArmId[])}>
              {ARMS.map((a) => (
                <ToggleGroupItem key={a} value={a}><span className={cn('rounded border px-1 text-[10px] font-semibold', ARM_TONE[a])}>{a}</span></ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
          {older > 0 && (
            <label className="flex max-w-64 items-start gap-2 text-xs text-muted-foreground">
              <Checkbox checked={showOlder} onCheckedChange={(v) => setShowOlder(v === true)} className="mt-0.5" />
              <span>Show {older} older run{older === 1 ? '' : 's'} from before the current pipeline (product matching, 27 Nov)</span>
            </label>
          )}
        </div>

        {q.isPending && <div className="space-y-3"><Skeleton className="h-40 w-full" /><Skeleton className="h-64 w-full" /></div>}
        {q.isError && <p className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">The run history could not be loaded: {String(q.error)}</p>}

        {q.data && (
          <>
            <section className="space-y-2">
              <h3 className="text-sm font-medium">Automatic measures by model</h3>
              <p className="max-w-3xl text-xs text-muted-foreground">
                What each run already records (evaluation plan §2.2). Hover a measure for its definition. Human judgements (claim
                support, deciding factor, usefulness) come from the labelling sheets and are not shown here.
              </p>
              <MeasuresTable runs={runs} kind={kind} arms={shownArms} />
            </section>

            <section className="space-y-2">
              <h3 className="text-sm font-medium">Same query, each model</h3>
              <p className="max-w-3xl text-xs text-muted-foreground">
                Queries run on two or more models, with the same items and as-of date. Open a cell for the full answer and trace.
              </p>
              <CompareTable runs={runs} arms={shownArms} />
            </section>

            <section className="space-y-2">
              <h3 className="text-sm font-medium">Every run <span className="font-normal text-muted-foreground">({runs.length})</span></h3>
              <RunsTable runs={runs} />
            </section>

            <div className="flex gap-2 rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              <Info className="mt-0.5 size-3.5 shrink-0" />
              <p>
                Pilot runs are trial runs made before the evaluation, to check that every model and every step works: some by hand in
                the app, some with the evaluation runner on queries from the evaluation sample. They are not results. Only Evaluation
                runs are the evaluation. Pilot runs made before the model picker existed are matched to a model by the model name they
                recorded.
              </p>
            </div>
          </>
        )}
      </div>
    </PageContainer>
  )
}
