/**
 * The step-by-step trace of one Ask the Graph run. Live runs (built from SSE
 * events) and stored runs (from runs/ask/) render through the same component.
 */
import { AlertTriangle, RotateCcw } from 'lucide-react'
import type { ReactNode } from 'react'
import Markdown from 'react-markdown'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { STEP_LABEL, type Attempt, type LiveRun, type StepName } from '@/lib/ask'
import { cn } from '@/lib/utils'
import { CypherBlock, Disclosure, ms, PromptText, StepIcon } from './parts'
import { RowsGraphView, RowsTable } from './RowsView'

type StepState = 'running' | 'done' | 'failed' | 'waiting'

function Step({
  n, step, state, attempt, elapsed, children, last,
}: {
  n: number
  step: StepName
  state: StepState
  attempt?: number | null
  elapsed?: number | null
  children?: ReactNode
  last?: boolean
}) {
  return (
    <li className="relative flex gap-3 pb-6" data-step={step} data-state={state}>
      {!last && <span aria-hidden className="absolute top-7 bottom-0 left-3 w-px -translate-x-1/2 bg-border" />}
      <StepIcon state={state} />
      <div className="min-w-0 flex-1 space-y-2.5">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 pt-0.5">
          <span className="text-xs text-muted-foreground tabular">{n}.</span>
          <h3 className="text-sm font-medium">{STEP_LABEL[step]}</h3>
          {attempt && attempt > 1 && <span className="rounded bg-amber-500/15 px-1.5 text-[10px] font-medium text-amber-800 dark:text-amber-300">retry</span>}
          {state === 'running' && <span className="text-xs text-muted-foreground">working…</span>}
          {elapsed != null && <span className="ml-auto text-[11px] text-muted-foreground tabular">{ms(elapsed)}</span>}
        </div>
        {children}
      </div>
    </li>
  )
}

const stripFences = (s: string) => s.trim().replace(/^```[\w-]*\s*\n?/, '').replace(/\n?\s*```\s*$/, '').trim()

function stateOf(run: LiveRun, step: StepName, attempt: number, has: boolean, ok = true): StepState {
  if (isPending(run, step, attempt)) return 'running'
  if (!has) return 'waiting'
  return ok ? 'done' : 'failed'
}

const isPending = (run: LiveRun, step: StepName, attempt: number) => run.pending?.step === step && run.pending.attempt === attempt

/** Which steps of an attempt are on screen (started or finished). */
const shown = (run: LiveRun, a: Attempt) => ({
  check: !!a.check || isPending(run, 'check_cypher', a.attempt),
  run: !!a.run || isPending(run, 'run_query', a.attempt),
})

function AttemptSteps({ run, a, start, problem, model }: { run: LiveRun; a: Attempt; start: number; problem?: string | null; model: string }) {
  const steps: ReactNode[] = []
  let n = start
  const feedback = a.generate?.feedback ?? a.retry_of
  const gen = stateOf(run, 'generate_cypher', a.attempt, !!a.generate)
  steps.push(
    <Step key="g" n={n++} step="generate_cypher" state={gen} attempt={a.attempt} elapsed={a.generate?.elapsed_ms}>
      {feedback && (
        <div className="flex gap-2 rounded-md border border-amber-500/30 bg-amber-500/8 px-3 py-2 text-xs">
          <RotateCcw className="mt-0.5 size-3.5 shrink-0 text-amber-600" />
          <div>
            <div className="font-medium">Retry: the previous attempt's problem was sent back to the model</div>
            <div className="mt-0.5 text-muted-foreground">{feedback.problem}</div>
          </div>
        </div>
      )}
      {a.generate && (
        <>
          <CypherBlock cypher={stripFences(a.generate.raw) || '(empty reply)'} />
          <Disclosure title={<>Prompt sent to {model}: schema, examples and question</>}>
            <PromptText text={a.generate.prompt} />
          </Disclosure>
        </>
      )}
    </Step>,
  )
  const vis = shown(run, a)
  if (vis.check) {
    steps.push(
      <Step key="c" n={n++} step="check_cypher" state={stateOf(run, 'check_cypher', a.attempt, !!a.check, a.check?.ok)} attempt={a.attempt} elapsed={a.check?.elapsed_ms}>
        {a.check && (
          <ul className="grid gap-1 text-xs sm:grid-cols-2">
            {a.check.checks.map((c, i) => (
              <li key={i} className={cn('flex items-start gap-1.5 rounded px-2 py-1', !c.ok && 'bg-red-500/8')}>
                <span className={cn('mt-px font-semibold', c.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>
                  {c.ok ? '✓' : '✕'}
                </span>
                <span className={cn(!c.ok && 'text-red-700 dark:text-red-300', c.name === 'server_note' && 'text-muted-foreground')}>{c.detail}</span>
              </li>
            ))}
          </ul>
        )}
      </Step>,
    )
  }
  if (vis.run) {
    const r = a.run
    const graph = r?.graph && (r.graph.nodes.length > 0 || r.graph.omitted) ? r.graph : null
    steps.push(
      <Step key="r" n={n++} step="run_query" state={stateOf(run, 'run_query', a.attempt, !!r, r?.ok)} attempt={a.attempt} elapsed={r?.elapsed_ms}>
        {a.check && (
          <Disclosure title="Query as run (with the row limit)">
            <CypherBlock cypher={a.check.cypher} />
          </Disclosure>
        )}
        {r && !r.ok && (
          <div className="rounded-md border border-red-500/30 bg-red-500/8 px-3 py-2 font-mono text-xs text-red-700 dark:text-red-300">{r.error}</div>
        )}
        {r?.ok && !graph && <RowsTable result={r} fileName={`${run.run_id}-attempt${a.attempt}`} />}
        {r?.ok && graph && (
          <>
            {/* Wide screens: table and graph side by side; narrow: tabs. */}
            <div className="hidden gap-3 xl:grid xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
              <RowsTable result={r} fileName={`${run.run_id}-attempt${a.attempt}`} />
              <RowsGraphView graph={graph} question={run.question} />
            </div>
            <Tabs defaultValue="table" className="xl:hidden">
              <TabsList>
                <TabsTrigger value="table">Rows</TabsTrigger>
                <TabsTrigger value="graph">Graph</TabsTrigger>
              </TabsList>
              <TabsContent value="table"><RowsTable result={r} fileName={`${run.run_id}-attempt${a.attempt}`} /></TabsContent>
              <TabsContent value="graph" className="h-[420px]"><RowsGraphView graph={graph} question={run.question} /></TabsContent>
            </Tabs>
          </>
        )}
        {r?.ok && problem && a.attempt < run.attempts.length && (
          <div className="text-xs text-amber-700 dark:text-amber-300">No rows, so the question goes back to the model once.</div>
        )}
      </Step>,
    )
  }
  return <>{steps}</>
}

const PROSE =
  'text-sm leading-relaxed [&_p]:my-2 [&_p:first-child]:mt-0 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 ' +
  '[&_li]:my-0.5 [&_li>ul]:my-0.5 [&_strong]:font-semibold [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:font-mono [&_code]:text-[12px] ' +
  '[&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm [&_h1,&_h2,&_h3]:mt-3 [&_h1,&_h2,&_h3]:font-semibold [&_table]:my-2 [&_td]:border [&_td]:px-2 [&_th]:border [&_th]:px-2'

export function Trace({ run }: { run: LiveRun }) {
  let n = 1
  const blocks: ReactNode[] = []
  run.attempts.forEach((a, i) => {
    const problem = a.problem ?? run.attempts[i + 1]?.generate?.feedback?.problem ?? run.attempts[i + 1]?.retry_of?.problem
    const start = n
    const vis = shown(run, a)
    n += 1 + (vis.check ? 1 : 0) + (vis.run ? 1 : 0)
    blocks.push(<AttemptSteps key={a.attempt} run={run} a={a} start={start} problem={problem} model={run.model} />)
  })
  const answering = run.pending?.step === 'write_answer'
  if (run.answer || answering) {
    blocks.push(
      <Step key="answer" n={n} step="write_answer" state={answering ? 'running' : 'done'} elapsed={run.answer?.elapsed_ms} last>
        <div className="rounded-lg border border-primary/25 bg-primary/[0.03] p-4 shadow-xs" data-testid="answer">
          {run.answer?.text ? (
            <div className={PROSE}>
              <Markdown>{run.answer.text}</Markdown>
              {answering && <span className="ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse bg-foreground/60" />}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">Writing the answer from the rows…</div>
          )}
        </div>
        {run.answer?.prompt && (
          <Disclosure title={<>Prompt sent to {run.model}: question, Cypher and rows only</>}>
            <PromptText text={run.answer.prompt} />
          </Disclosure>
        )}
      </Step>,
    )
  }
  return (
    <div className="space-y-3">
      <ol className="list-none">{blocks}</ol>
      {run.error && (
        <div className="flex gap-2 rounded-md border border-red-500/30 bg-red-500/8 px-3 py-2.5 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-red-600" />
          <div>
            <div className="font-medium">The question could not be answered</div>
            <div className="mt-0.5 text-xs text-muted-foreground">{run.error}</div>
          </div>
        </div>
      )}
    </div>
  )
}
