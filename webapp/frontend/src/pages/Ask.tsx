/**
 * Ask the Graph: a natural-language question becomes LLM-written, read-only
 * Cypher. Every step is shown as it happens: the Cypher, the safety checks,
 * the rows (and a small graph when they hold nodes), and the answer written
 * from those rows only. Runs are stored in runs/ask/ and can be reopened.
 */
import { useQueryClient } from '@tanstack/react-query'
import { ArrowUp, Info, Loader2, MessageSquarePlus, Square } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { StatusBadge } from '@/components/ask/parts'
import { Trace } from '@/components/ask/Trace'
import { PageContainer } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  reduceEvent, streamAsk, useAskExamples, useAskRun, useAskRuns, type LiveRun,
} from '@/lib/ask'
import { cn } from '@/lib/utils'

function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

function History({ current, onOpen, onNew }: { current: string | null; onOpen: (id: string, question: string) => void; onNew: () => void }) {
  const runs = useAskRuns()
  return (
    <aside className="space-y-3 lg:sticky lg:top-6 lg:self-start">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-medium text-muted-foreground">Recent questions</h2>
        <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={onNew}>
          <MessageSquarePlus className="size-3.5" /> New
        </Button>
      </div>
      <div className="max-h-[calc(100dvh-12rem)] space-y-1 overflow-y-auto pr-1">
        {runs.isPending && [0, 1, 2].map((i) => <Skeleton key={i} className="h-14 w-full" />)}
        {runs.data?.runs.length === 0 && (
          <p className="rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground">
            Questions you ask are saved to runs/ask/ and listed here.
          </p>
        )}
        {runs.data?.runs.map((r) => (
          <button
            key={r.run_id}
            onClick={() => onOpen(r.run_id, r.question)}
            className={cn(
              'w-full rounded-md border px-3 py-2 text-left transition-colors hover:bg-muted/60',
              r.run_id === current ? 'border-primary/40 bg-muted/60' : 'border-transparent',
            )}
          >
            <div className="line-clamp-2 text-xs leading-snug">{r.question}</div>
            <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
              <StatusBadge status={r.status} className="px-1.5 py-0 text-[10px]" />
              {r.row_count != null && <span>{r.row_count} rows</span>}
              {r.attempts > 1 && <span>{r.attempts} tries</span>}
              <span className="ml-auto">{timeAgo(r.started_at)}</span>
            </div>
          </button>
        ))}
      </div>
    </aside>
  )
}

export default function Ask() {
  const [params, setParams] = useSearchParams()
  const runParam = params.get('run')
  const [question, setQuestion] = useState('')
  const [live, setLive] = useState<LiveRun | null>(null)
  const [busy, setBusy] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const qc = useQueryClient()
  const examples = useAskExamples()

  // A stored run is fetched only when the URL points at a run other than the live one.
  const stored = useAskRun(runParam, !!runParam && runParam !== live?.run_id)
  const run: LiveRun | null =
    live && (!runParam || live.run_id === runParam) ? live : stored.data ? { ...stored.data, pending: null } : null

  useEffect(() => () => abort.current?.abort(), [])

  const submit = useCallback(
    async (q: string) => {
      const text = q.trim()
      if (text.length < 3 || busy) return
      abort.current?.abort()
      const ctrl = new AbortController()
      abort.current = ctrl
      setQuestion(text)
      setLive(null)
      setBusy(true)
      try {
        await streamAsk(
          text,
          (e) => {
            setLive((s) => reduceEvent(s, e))
            if (e.event === 'run') setParams({ run: e.run.run_id }, { replace: true })
          },
          ctrl.signal,
        )
      } catch (err) {
        if (ctrl.signal.aborted) {
          setLive((s) => (s ? { ...s, status: 'cancelled', pending: null } : s))
        } else {
          toast.error('The question could not be sent', { description: String((err as Error).message ?? err) })
          setLive((s) => (s ? { ...s, status: 'failed', error: String((err as Error).message ?? err), pending: null } : s))
        }
      } finally {
        if (abort.current === ctrl) abort.current = null
        setBusy(false)
        qc.invalidateQueries({ queryKey: ['ask', 'runs'] })
      }
    },
    [busy, qc, setParams],
  )

  const reset = () => {
    abort.current?.abort()
    setLive(null)
    setQuestion('')
    setParams({}, { replace: true })
  }

  return (
    <PageContainer>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0 space-y-5">
          <div className="space-y-1">
            <h2 className="text-xl font-semibold tracking-tight">Ask the Graph</h2>
            <p className="max-w-3xl text-sm text-muted-foreground">
              Ask about Dyson's suppliers, shipments, ports and carriers. An LLM writes a Cypher query, the app checks it
              and runs it read-only on the knowledge graph, then answers from the returned rows only.
            </p>
          </div>

          <form
            className="rounded-xl border bg-card p-3 shadow-xs focus-within:ring-2 focus-within:ring-ring/30"
            onSubmit={(e) => {
              e.preventDefault()
              submit(question)
            }}
          >
            <Textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  submit(question)
                }
              }}
              placeholder="e.g. Which carriers move the most Dyson shipments?"
              className="min-h-16 resize-none border-0 bg-transparent p-1 text-sm shadow-none focus-visible:ring-0 dark:bg-transparent"
              maxLength={500}
              aria-label="Question"
            />
            <div className="mt-2 flex items-center gap-2">
              <span className="text-[11px] text-muted-foreground">Enter to ask · Shift+Enter for a new line</span>
              {busy ? (
                <Button type="button" variant="outline" size="sm" className="ml-auto" onClick={() => abort.current?.abort()}>
                  <Square className="size-3 fill-current" /> Stop
                </Button>
              ) : (
                <Button type="submit" size="sm" className="ml-auto" disabled={question.trim().length < 3}>
                  <ArrowUp className="size-4" /> Ask
                </Button>
              )}
            </div>
          </form>

          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">Try an example</div>
            <div className="flex flex-wrap gap-1.5">
              {examples.isPending && [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-7 w-56 rounded-full" />)}
              {examples.data?.questions.map((q) => (
                <Tooltip key={q.id}>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => submit(q.question)}
                      className="rounded-full border bg-background px-3 py-1 text-left text-xs transition-colors hover:bg-muted disabled:opacity-50"
                    >
                      {q.question}
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="max-w-xs">{q.angle}</TooltipContent>
                </Tooltip>
              ))}
            </div>
          </div>

          <div className="flex gap-2 rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0" />
            <p>
              Exploratory. The model writes the query, so answers are less reliable than Risk Assessment: check the Cypher
              and the rows. It sees the graph only (no evidence records) and applies no as-of date. One retry is made if
              the query fails or returns nothing.
            </p>
          </div>

          {runParam && !run && stored.isPending && (
            <div className="space-y-3"><Skeleton className="h-6 w-2/3" /><Skeleton className="h-40 w-full" /></div>
          )}
          {runParam && stored.isError && !live && (
            <div className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">
              Run {runParam} was not found in runs/ask/.
            </div>
          )}

          {run && (
            <section className="space-y-4" aria-live="polite">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b pb-3">
                <h3 className="min-w-0 flex-1 text-base font-medium">{run.question}</h3>
                <StatusBadge status={busy && run.status === 'running' ? 'running' : run.status} />
                <span className="font-mono text-[10px] text-muted-foreground">{run.model} · {run.run_id}</span>
              </div>
              <Trace run={run} />
              {busy && !run.pending && run.status === 'running' && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="size-3 animate-spin" /> Waiting for the next step…</div>
              )}
            </section>
          )}
        </div>

        <History current={run?.run_id ?? runParam} onOpen={(id, q) => {
            if (busy) return
            setQuestion(q)
            setParams({ run: id })
          }} onNew={reset} />
      </div>
    </PageContainer>
  )
}
