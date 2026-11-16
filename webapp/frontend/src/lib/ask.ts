/**
 * Ask the Graph client: types for the stored run, the SSE reader for
 * POST /api/ask, and a reducer that builds the same run shape from the live
 * events, so a live run and a reopened one render through the same components.
 */
import { useQuery } from '@tanstack/react-query'
import { getJson } from './api'
import type { NodeKind } from './kinds'
import type { GEdge, GNode } from './types'

export type StepName = 'generate_cypher' | 'check_cypher' | 'run_query' | 'write_answer'
export type RunStatus = 'running' | 'answered' | 'no_rows' | 'failed' | 'cancelled'

export interface Feedback {
  cypher: string
  problem: string
}

export interface GenerateStep {
  prompt: string
  feedback: Feedback | null
  raw: string
  elapsed_ms: number
}

export interface CheckItem {
  name: string
  ok: boolean
  detail: string
}

export interface CheckStep {
  ok: boolean
  cypher: string
  checks: CheckItem[]
  elapsed_ms: number
}

export interface RowsGraph {
  nodes: GNode[]
  edges: GEdge[]
  omitted: boolean
  node_count: number
}

export interface RunStep {
  ok: boolean
  error?: string
  columns?: string[]
  rows?: Record<string, unknown>[]
  row_count?: number
  truncated?: boolean
  elapsed_ms: number
  graph?: RowsGraph | null
}

export interface Attempt {
  attempt: number
  generate: GenerateStep | null
  check: CheckStep | null
  run: RunStep | null
  problem?: string | null
  /** Live only: why this attempt is a retry (the stored run has it in generate.feedback). */
  retry_of?: Feedback | null
}

export interface AskRun {
  run_id: string
  kind?: 'ask'
  question: string
  model: string
  started_at: string
  finished_at: string | null
  status: RunStatus
  max_rows: number
  attempts: Attempt[]
  answer: { text: string; prompt?: string; elapsed_ms: number | null } | null
  error: string | null
}

export interface LiveRun extends AskRun {
  /** The step running right now (live runs only). */
  pending: { step: StepName; attempt: number | null } | null
}

export type AskEvent =
  | { event: 'run'; run: Pick<AskRun, 'run_id' | 'question' | 'model' | 'started_at' | 'max_rows'> }
  | { event: 'step'; step: StepName; attempt: number | null; status: 'running' | 'done' | 'failed'; data: Record<string, unknown> }
  | { event: 'token'; text: string }
  | { event: 'done'; run: AskRun }
  | { event: 'error'; message: string }

export interface RunSummary {
  run_id: string
  question: string
  status: RunStatus
  model: string
  started_at: string
  attempts: number
  row_count: number | null
}

export interface NodeRef {
  id: string
  kind: NodeKind | null
  name: string
}

// ---------------------------------------------------------------------------- reducer

export function reduceEvent(state: LiveRun | null, e: AskEvent): LiveRun | null {
  if (e.event === 'run') {
    return {
      ...e.run, finished_at: null, status: 'running', attempts: [], answer: null, error: null, pending: null,
    }
  }
  if (e.event === 'done') return { ...e.run, pending: null }
  if (!state) return state
  if (e.event === 'error') return { ...state, error: e.message, pending: null }
  if (e.event === 'token') {
    const answer = state.answer ?? { text: '', elapsed_ms: null }
    return { ...state, answer: { ...answer, text: answer.text + e.text } }
  }
  // step
  const s = { ...state, attempts: state.attempts.map((a) => ({ ...a })) }
  if (e.step === 'write_answer') {
    if (e.status === 'running') {
      s.answer = { text: '', prompt: e.data.prompt as string, elapsed_ms: null }
      s.pending = { step: e.step, attempt: null }
    } else {
      s.answer = { ...(s.answer ?? { text: '' }), text: e.data.text as string, elapsed_ms: e.data.elapsed_ms as number }
      s.pending = null
    }
    return s
  }
  const n = e.attempt ?? 1
  let a = s.attempts.find((x) => x.attempt === n)
  if (!a) {
    a = { attempt: n, generate: null, check: null, run: null, retry_of: (e.data.retry_of as Feedback | null) ?? null }
    s.attempts.push(a)
  }
  if (e.status === 'running') {
    s.pending = { step: e.step, attempt: n }
    return s
  }
  if (e.step === 'generate_cypher') a.generate = e.data as unknown as GenerateStep
  if (e.step === 'check_cypher') a.check = e.data as unknown as CheckStep
  if (e.step === 'run_query') a.run = e.data as unknown as RunStep
  s.pending = null
  return s
}

// ---------------------------------------------------------------------------- SSE over POST

/** POST the question and call `onEvent` for each Server-Sent Event until the stream ends. */
export async function streamAsk(question: string, onEvent: (e: AskEvent) => void, signal: AbortSignal): Promise<void> {
  const res = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ question }),
    signal,
  })
  if (!res.ok || !res.body) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : (body.detail?.[0]?.msg ?? JSON.stringify(body.detail ?? body))
    } catch {
      /* not JSON */
    }
    throw new Error(detail || `HTTP ${res.status}`)
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += value
    let cut: number
    while ((cut = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, cut)
      buf = buf.slice(cut + 2)
      const data = block.split('\n').filter((l) => l.startsWith('data: ')).map((l) => l.slice(6)).join('\n')
      if (data) onEvent(JSON.parse(data) as AskEvent)
    }
  }
}

// ---------------------------------------------------------------------------- queries

export const useAskExamples = () =>
  useQuery({
    queryKey: ['ask', 'examples'],
    queryFn: ({ signal }) => getJson<{ questions: { id: string; question: string; angle: string }[] }>('/ask/examples', {}, signal),
    staleTime: Infinity,
  })

export const useAskRuns = () =>
  useQuery({
    queryKey: ['ask', 'runs'],
    queryFn: ({ signal }) => getJson<{ runs: RunSummary[] }>('/ask/runs', { limit: 40 }, signal),
  })

export const useAskRun = (runId: string | null, enabled: boolean) =>
  useQuery({
    queryKey: ['ask', 'run', runId],
    queryFn: ({ signal }) => getJson<AskRun>(`/ask/runs/${encodeURIComponent(runId!)}`, {}, signal),
    enabled: !!runId && enabled,
    staleTime: Infinity,
  })

export const STEP_LABEL: Record<StepName, string> = {
  generate_cypher: 'Generate Cypher',
  check_cypher: 'Check the query',
  run_query: 'Run on Neo4j (read-only)',
  write_answer: 'Write the answer',
}

export const STATUS_META: Record<RunStatus, { label: string; tone: 'ok' | 'warn' | 'bad' | 'busy' }> = {
  running: { label: 'Running', tone: 'busy' },
  answered: { label: 'Answered', tone: 'ok' },
  no_rows: { label: 'No rows', tone: 'warn' },
  failed: { label: 'Failed', tone: 'bad' },
  cancelled: { label: 'Stopped', tone: 'warn' },
}
