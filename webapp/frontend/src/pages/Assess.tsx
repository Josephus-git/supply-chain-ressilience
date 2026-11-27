/**
 * Risk Assessment: the main workflow.
 *
 * Input: a parts list (up to 20 items, typed or from the product catalogue)
 * with an optional goal, or a free-text description; plus a simulated
 * as-of date (chosen, or drawn at random from the study window).
 * Output, one click deeper each time: layer 1 summary -> layer 2 reasoning
 * per item -> layer 3 "How this answer was reached" (the live timeline).
 * History is a tab; a re-run is a new run linked by `rerun_of`.
 *
 * URL: ?run=<id> opens a run, ?tab=history the History tab, ?rerun=<id>
 * pre-fills the form from a stored run.
 */
import { useQueryClient } from '@tanstack/react-query'
import {
  ChevronRight, Dices, Info, ListOrdered, Loader2, MessageSquareText, Play, RotateCcw, Square, TriangleAlert, X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { CataloguePanel } from '@/components/assess/Catalogue'
import { CitationProvider, CitationTotals } from '@/components/assess/Citations'
import { AssessStatusBadge, DateModeBadge, History } from '@/components/assess/History'
import { ItemsEditor } from '@/components/assess/ItemsEditor'
import { Report } from '@/components/assess/Report'
import { Timeline } from '@/components/assess/Timeline'
import { PageContainer } from '@/components/layout/AppShell'
import { ArmBadge, ModelPicker } from '@/components/models/ModelPicker'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useHealth } from '@/lib/api'
import {
  DESCRIBE_EXAMPLES, GOAL_EXAMPLES, inWindow, MAX_ITEMS, modelsLabel, randomStudyDate, reduceAssess, requestTitle, scrollToAnchor,
  STEP_LABEL, streamAssess, STUDY_END, STUDY_START, useAssessRun,
  type AssessMode, type DateMode, type Item, type LiveAssess,
} from '@/lib/assess'
import { dateLabel, fmt } from '@/lib/format'
import { useArm } from '@/lib/models'
import { cn } from '@/lib/utils'

function Chips({ options, onPick, disabled }: { options: string[]; onPick: (s: string) => void; disabled?: boolean }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={o} type="button" disabled={disabled} onClick={() => onPick(o)}
          className="rounded-full border bg-background px-2.5 py-0.5 text-xs transition-colors hover:bg-muted disabled:opacity-50"
        >
          {o}
        </button>
      ))}
    </div>
  )
}

function TokenNotice() {
  const t = useHealth().data?.tokens_today
  if (!t || t.level === 'ok') return null
  return (
    <div className={cn(
      'flex items-start gap-2 rounded-md border px-3 py-2 text-xs',
      t.level === 'over' ? 'border-red-500/40 bg-red-500/8 text-red-800 dark:text-red-200' : 'border-amber-500/40 bg-amber-500/8 text-amber-900 dark:text-amber-200',
    )}>
      <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
      <span>
        {t.level === 'over' ? 'Past' : 'Near'} today's free OpenAI allowance: {fmt(t.used)} of {fmt(t.limit)} tokens used ({t.day_utc}, UTC).
        Further runs may be billed. This is a warning only.
      </span>
    </div>
  )
}

export default function Assess() {
  const [params, setParams] = useSearchParams()
  const runParam = params.get('run')
  const rerunParam = params.get('rerun')
  const tab = params.get('tab') === 'history' ? 'history' : 'assess'

  const [mode, setMode] = useState<AssessMode>('parts')
  const [items, setItems] = useState<Item[]>([])
  const [goal, setGoal] = useState('')
  const [description, setDescription] = useState('')
  const [asOf, setAsOf] = useState('')
  const [dateMode, setDateMode] = useState<DateMode>('chosen')
  const [rerunOf, setRerunOf] = useState<string | null>(null)
  const [arm, setArm] = useArm()

  const [live, setLive] = useState<LiveAssess | null>(null)
  const [busy, setBusy] = useState(false)
  const [traceOpen, setTraceOpen] = useState<boolean | null>(null)
  const abort = useRef<AbortController | null>(null)
  const qc = useQueryClient()

  const stored = useAssessRun(runParam, !!runParam && runParam !== live?.run_id)
  const run: LiveAssess | null =
    live && (!runParam || live.run_id === runParam) ? live : stored.data ? { ...stored.data, pending: null } : null

  // Re-run: pre-fill from the stored run; the date is left for the user to set.
  const source = useAssessRun(rerunParam)
  useEffect(() => {
    const r = source.data
    if (!r || !rerunParam) return
    setMode(r.mode)
    if (r.mode === 'parts') {
      setItems(r.items.map(({ text, source: s, product_id }) => ({ text, source: s, product_id })))
      setGoal(r.goal ?? '')
    } else {
      setDescription(r.items[0]?.text ?? '')
    }
    setAsOf('')
    setDateMode('chosen')
    setRerunOf(r.run_id)
    setParams({}, { replace: true })
    setLive(null)
  }, [source.data, rerunParam, setParams])

  useEffect(() => () => abort.current?.abort(), [])

  const ready =
    inWindow(asOf) && (mode === 'parts' ? items.some((i) => i.text.trim()) : description.trim().length >= 3)

  const submit = useCallback(async () => {
    if (!ready || busy) return
    abort.current?.abort()
    const ctrl = new AbortController()
    abort.current = ctrl
    setLive(null)
    setBusy(true)
    setTraceOpen(null)
    try {
      await streamAssess(
        {
          mode,
          items: mode === 'parts' ? items.filter((i) => i.text.trim()) : [],
          goal: mode === 'parts' ? goal.trim() || null : null,
          description: mode === 'describe' ? description.trim() : null,
          as_of_date: asOf,
          date_mode: dateMode,
          rerun_of: rerunOf,
          arm,
        },
        (e) => {
          setLive((s) => reduceAssess(s, e))
          if (e.event === 'run') setParams({ run: e.run.run_id }, { replace: true })
        },
        ctrl.signal,
      )
    } catch (err) {
      if (ctrl.signal.aborted) {
        setLive((s) => (s ? { ...s, status: 'cancelled', pending: null } : s))
      } else {
        toast.error('The assessment could not run', { description: String((err as Error).message ?? err) })
        setLive((s) => (s ? { ...s, status: 'failed', error: String((err as Error).message ?? err), pending: null } : s))
      }
    } finally {
      if (abort.current === ctrl) abort.current = null
      setBusy(false)
      setRerunOf(null)
      qc.invalidateQueries({ queryKey: ['assess', 'runs'] })
      qc.invalidateQueries({ queryKey: ['health'] })
    }
  }, [ready, busy, mode, items, goal, description, asOf, dateMode, rerunOf, arm, setParams, qc])

  const showInTrace = (id: string) => {
    setTraceOpen(true)
    setTimeout(() => scrollToAnchor(id), 80)
  }
  const traceIsOpen = traceOpen ?? (!!run && (run.status === 'running' || run.status === 'failed' || !run.report?.parsed))
  const addedIds = new Set(items.map((i) => i.product_id).filter(Boolean) as string[])
  const runFinished = run && run.status !== 'running'

  return (
    <PageContainer>
      <div className="space-y-5">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold tracking-tight">Risk Assessment</h2>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Give a parts list or describe what you need, pick a date and a model. Candidate suppliers come from the knowledge graph (product
            matching for a parts list, an LLM-written query for a description); fixed queries and the risk engine gather what was known on
            that date; the chosen model compares and ranks. Every claim cites its source.
          </p>
        </div>

        <Tabs value={tab} onValueChange={(v) => setParams(v === 'history' ? { tab: 'history' } : runParam ? { run: runParam } : {}, { replace: true })}>
          <TabsList>
            <TabsTrigger value="assess">Assess</TabsTrigger>
            <TabsTrigger value="history">History</TabsTrigger>
          </TabsList>

          <TabsContent value="history" className="pt-3">
            <History
              onOpen={(id) => setParams({ run: id })}
              onRerun={(id) => setParams({ rerun: id })}
            />
          </TabsContent>

          <TabsContent value="assess" className="space-y-5 pt-3">
            {/* ------------------------------------------------------------ request */}
            <form
              className="space-y-4 rounded-xl border bg-card p-4 shadow-xs"
              onSubmit={(e) => {
                e.preventDefault()
                submit()
              }}
            >
              {rerunOf && (
                <div className="flex items-center gap-2 rounded-md border border-violet-500/30 bg-violet-500/8 px-3 py-2 text-xs">
                  <RotateCcw className="size-3.5 shrink-0" />
                  <span className="flex-1">Re-running <span className="font-mono">{rerunOf}</span> with the same request. Set a new date (or Random); the result is saved as a new run linked to the original.</span>
                  <Button type="button" variant="ghost" size="icon" className="size-6" aria-label="Cancel re-run" onClick={() => setRerunOf(null)}><X className="size-3.5" /></Button>
                </div>
              )}

              <ToggleGroup type="single" variant="outline" size="sm" value={mode} onValueChange={(v) => v && setMode(v as AssessMode)} disabled={busy}>
                <ToggleGroupItem value="parts"><ListOrdered className="size-3.5" /> Parts list</ToggleGroupItem>
                <ToggleGroupItem value="describe"><MessageSquareText className="size-3.5" /> Describe your need</ToggleGroupItem>
              </ToggleGroup>

              {mode === 'parts' ? (
                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
                  <div className="space-y-4">
                    <div className="space-y-1.5">
                      <div className="text-xs font-medium text-muted-foreground">Items (up to {MAX_ITEMS})</div>
                      <ItemsEditor items={items} setItems={setItems} asOf={inWindow(asOf) ? asOf : null} disabled={busy} />
                    </div>
                    <div className="space-y-1.5">
                      <label htmlFor="goal" className="text-xs font-medium text-muted-foreground">What do you want to know? (optional)</label>
                      <Textarea
                        id="goal" value={goal} onChange={(e) => setGoal(e.target.value)} maxLength={500} disabled={busy}
                        placeholder="Assess supplier risk for these items." className="min-h-14 resize-none text-sm"
                      />
                      <Chips options={GOAL_EXAMPLES} onPick={setGoal} disabled={busy} />
                    </div>
                  </div>
                  <div className="h-[480px]">
                    <CataloguePanel
                      asOf={inWindow(asOf) ? asOf : null}
                      addedIds={addedIds}
                      full={items.length >= MAX_ITEMS || busy}
                      onAdd={(p) => setItems((xs) => [...xs, { text: p.name, source: 'catalogue' as const, product_id: p.id }].slice(0, MAX_ITEMS))}
                    />
                  </div>
                </div>
              ) : (
                <div className="space-y-1.5">
                  <Textarea
                    value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} disabled={busy}
                    placeholder="e.g. Who supplies parts for air filters?" className="min-h-20 resize-none text-sm" aria-label="Describe your need"
                  />
                  <Chips options={DESCRIBE_EXAMPLES} onPick={setDescription} disabled={busy} />
                </div>
              )}

              <div className="flex flex-wrap items-end gap-3 border-t pt-4">
                <div className="space-y-1">
                  <label htmlFor="as-of" className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    As-of date <DateModeBadge mode={dateMode} />
                  </label>
                  <div className="flex gap-1.5">
                    <input
                      id="as-of" type="date" min={STUDY_START} max={STUDY_END} value={asOf} disabled={busy} required
                      onChange={(e) => { setAsOf(e.target.value); setDateMode('chosen') }}
                      className="h-8 rounded-md border bg-background px-2 text-sm tabular outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
                    />
                    <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => { setAsOf(randomStudyDate()); setDateMode('random') }}>
                      <Dices className="size-3.5" /> Random
                    </Button>
                  </div>
                </div>
                <ModelPicker value={arm} onChange={setArm} disabled={busy} />
                <p className="max-w-sm text-[11px] leading-snug text-muted-foreground">
                  Study window {dateLabel(STUDY_START)} to {dateLabel(STUDY_END)}. Nothing after the date is used: not shipments, not evidence. The LLMs never choose it.
                  {asOf && !inWindow(asOf) && <span className="block text-red-600 dark:text-red-400">Pick a date inside the study window.</span>}
                </p>
                <div className="ml-auto flex items-center gap-2">
                  {busy ? (
                    <Button type="button" variant="outline" onClick={() => abort.current?.abort()}>
                      <Square className="size-3 fill-current" /> Stop
                    </Button>
                  ) : (
                    <Button type="submit" disabled={!ready}><Play className="size-3.5" /> Assess</Button>
                  )}
                </div>
              </div>
              <TokenNotice />
            </form>

            {/* ------------------------------------------------------------ result */}
            {runParam && !run && stored.isPending && (
              <div className="space-y-3"><Skeleton className="h-6 w-2/3" /><Skeleton className="h-40 w-full" /></div>
            )}
            {runParam && stored.isError && !live && (
              <div className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">Run {runParam} was not found in runs/assess/.</div>
            )}

            {run && (
              <CitationProvider run={run} showInTrace={showInTrace}>
                <section className="space-y-4" aria-live="polite" data-testid="assess-result">
                  <div className="space-y-1 border-b pb-3">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <h3 className="min-w-0 flex-1 text-base font-medium">{run.mode === 'parts' ? (run.goal ?? requestTitle(run)) : requestTitle(run)}</h3>
                      <ArmBadge arm={run.arm} model={run.models?.report} />
                      <AssessStatusBadge status={busy && run.status === 'running' ? 'running' : run.status} />
                      {runFinished && (
                        <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setParams({ rerun: run.run_id })}>
                          <RotateCcw className="size-3" /> Re-run with another date
                        </Button>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                      {run.mode === 'parts' && <span>{run.items.length} item{run.items.length === 1 ? '' : 's'}</span>}
                      <span className="flex items-center gap-1">as of <span className="font-medium text-foreground tabular">{dateLabel(run.as_of_date)}</span> <DateModeBadge mode={run.date_mode} /></span>
                      {run.usage && <span className="tabular">{fmt(run.usage.total_tokens)} tokens · {run.usage.calls} LLM call{run.usage.calls === 1 ? '' : 's'}</span>}
                      <CitationTotals run={run} />
                      {run.rerun_of && (
                        <button type="button" className="hover:text-foreground hover:underline" onClick={() => setParams({ run: run.rerun_of! })}>re-run of {run.rerun_of}</button>
                      )}
                      <span className="ml-auto font-mono text-[10px]">{modelsLabel(run.models)} · {run.run_id}</span>
                    </div>
                  </div>

                  {run.status === 'running' && !run.report?.parsed && (
                    <div className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
                      <Loader2 className="size-4 animate-spin" />
                      {run.pending ? `${STEP_LABEL[run.pending.step]}…` : 'Waiting for the next step…'}
                    </div>
                  )}

                  {/* Layers 1 and 2 */}
                  <Report run={run} />

                  {/* Layer 3 */}
                  <section className="rounded-lg border">
                    <button
                      type="button" onClick={() => setTraceOpen(!traceIsOpen)} aria-expanded={traceIsOpen}
                      className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-muted/40"
                    >
                      <ChevronRight className={cn('size-4 transition-transform', traceIsOpen && 'rotate-90')} />
                      <span className="text-sm font-medium">How this answer was reached</span>
                      <span className="text-xs text-muted-foreground">the queries, profiles and evidence the risk LLM was given, in pipeline order</span>
                    </button>
                    {traceIsOpen && (
                      <div className="border-t px-4 pt-4">
                        <Timeline run={run} />
                      </div>
                    )}
                  </section>

                  <div className="flex gap-2 rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                    <Info className="mt-0.5 size-3.5 shrink-0" />
                    <p>
                      A linked evidence record is context, not proof that an event affected a supplier. Track record means shipment volume and
                      recency only: customs records hold completed arrivals, not failed or late deliveries. Citations are checked and flagged,
                      never corrected.
                    </p>
                  </div>
                </section>
              </CitationProvider>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </PageContainer>
  )
}
