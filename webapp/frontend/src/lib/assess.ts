/**
 * Risk Assessment client: types for the stored run (runs/assess/), the SSE
 * stream of POST /api/assess, a reducer that builds the same run shape from
 * live events (so a live run and a reopened one render the same way), and the
 * catalogue, history and citation helpers.
 */
import { useQuery } from '@tanstack/react-query'
import { getJson } from './api'
import { postSSE, type CheckStep, type Feedback, type RunStep } from './ask'

export const STUDY_START = '2025-01-01'
export const STUDY_END = '2026-09-30'
export const MAX_ITEMS = 20
export const INSUFFICIENT = "I don't have enough data to support that."

export type AssessMode = 'parts' | 'describe'
export type DateMode = 'chosen' | 'random'
export type AssessStatus = 'running' | 'answered' | 'country_level' | 'insufficient_data' | 'failed' | 'cancelled'
export type AssessStep =
  | 'generate_cypher' | 'check_cypher' | 'run_query'
  | 'build_profiles' | 'lookup_evidence' | 'write_report' | 'check_citations'
export type DecidingFactor = 'match' | 'risk' | 'track_record'
export type ItemStatus = 'answered' | 'country_level' | 'insufficient_data'

export interface Item {
  n?: number
  text: string
  source: 'catalogue' | 'typed'
  product_id: string | null
}

export interface CandGenerate {
  prompt: string
  feedback: Feedback | null
  raw: unknown
  parsing_error: string | null
  cypher: string
  suggested_countries: { code: string; reason: string }[]
  interpretation: string | null
  elapsed_ms: number
}

export interface CandAttempt {
  attempt: number
  generate: CandGenerate | null
  check: CheckStep | null
  run: RunStep | null
  problem?: string | null
  retry_of?: Feedback | null
}

export interface MatchedProduct {
  item: number
  supplier_id: string
  product_id: string
  product_description: string
  hs_code: number | null
  shipments: number
  last_arrival: string
}

export interface Candidate {
  supplier_id: string
  supplier_name: string | null
  product_ids: string[]
  products: MatchedProduct[]
  active: boolean
}

export interface Exposure {
  name?: string
  code?: string
  country?: string
  coast?: string
  shipments: number
}

export interface Profile {
  supplier_id: string
  supplier_name: string
  country: string
  parent_companies: string[]
  hs_codes: Exposure[]
  exit_ports: Exposure[]
  entry_ports: Exposure[]
  buyers: Exposure[]
  carriers: Exposure[]
  vessels: Exposure[]
  currency: string
  footprint_window: { first_arrival: string; last_arrival: string; shipments: number }
  _context?: { company: string | null; address: string | null }
}

export interface QueryLog {
  name: string
  cypher: string
  params: Record<string, unknown>
  row_count: number
  elapsed_ms: number
}

export interface InactiveSupplier {
  supplier_id: string
  supplier_name: string
  company: string
  country: string
}

export interface Profiles {
  profiles: Record<string, Profile>
  inactive: InactiveSupplier[]
  unknown: string[]
  queries: QueryLog[]
  elapsed_ms: number
}

export interface Candidates {
  by_item: Record<string, Candidate[]>
  after_as_of: { item: number; supplier_id: string; product_id: string }[]
}

export interface EngineLink {
  evidence_id: string
  risk_type: string
  link_basis: string
  link_strength: 'strong' | 'medium' | 'weak'
  matched_values: string[]
  date_status: string
  in_scope_reason: string
  labels: string[]
  approximated: boolean
}

export interface RecordBrief {
  evidence_id: string
  risk_type: string
  risk_label: string
  title: string
  description: string | null
  start: string | null
  end: string | null
  date_family: string
  verification_status: string | null
  limitations: string[]
  measures: { label: string; value: number; unit: string | null }[]
  countries: string[]
  publisher: string | null
}

export interface EngineCall {
  payload: Record<string, unknown>
  status: 'completed' | 'rejected'
  errors: unknown
  links: EngineLink[]
  result: Record<string, unknown>
}

export interface CountryCall extends EngineCall {
  code: string
  basis: 'mentioned' | 'suggested'
  reason: string | null
}

export interface Evidence {
  as_of_date: string
  event_window_days: number
  by_supplier: Record<string, EngineCall>
  by_country: Record<string, CountryCall>
  countries_skipped: { code: string; basis: string; reason_skipped: string }[]
  records: Record<string, RecordBrief>
  snapshot_id: string
  elapsed_ms: number
}

export interface Claim {
  text: string
  citations: string[]
}

export interface RankedCandidate {
  supplier_id: string
  match_reason: Claim
  risks: Claim[]
  track_record: Claim
  deciding_factor: DecidingFactor
  deciding_reason: string
}

export interface ItemAssessment {
  item: number
  status: ItemStatus
  candidates: RankedCandidate[]
  set_aside: { supplier_id: string; reason: Claim }[]
  country_notes: { country_code: string; from_suggestion: boolean; note: Claim }[]
  /** One-line answer for this item (absent in runs saved before it existed). */
  answer?: Claim
}

export interface Report {
  summary: Claim
  items: ItemAssessment[]
}

export interface ReportStep {
  source: 'llm' | 'pipeline'
  reason?: string
  prompt: string | null
  raw: unknown
  parsed: Report | null
  parsing_error: string | null
  elapsed_ms: number | null
}

export interface CitationCheck {
  path: string
  citation: string
  kind: 'evidence' | 'graph' | 'match'
  status: 'verified' | 'not_found'
  note: string | null
}

export interface Citations {
  checks: CitationCheck[]
  total: number
  verified: number
  not_found: number
  with_note: number
  uncited_claims: string[]
  given: string[]
}

export interface Usage {
  input_tokens: number
  output_tokens: number
  total_tokens: number
  reasoning_tokens: number
  calls: number
  by_model: Record<string, { input_tokens: number; output_tokens: number; total_tokens: number; reasoning_tokens: number }>
}

export interface AssessRun {
  run_id: string
  kind: 'assess'
  mode: AssessMode
  items: (Item & { n: number })[]
  goal: string | null
  as_of_date: string
  date_mode: DateMode
  rerun_of: string | null
  models: { cypher: string; report: string }
  started_at: string
  finished_at: string | null
  status: AssessStatus
  attempts: CandAttempt[]
  candidates: Candidates | null
  profiles: Profiles | null
  evidence: Evidence | null
  report: ReportStep | null
  citations: Citations | null
  usage: Usage | null
  error: string | null
  failed_step: AssessStep | null
}

export interface LiveAssess extends AssessRun {
  pending: { step: AssessStep; attempt: number | null } | null
}

type Header = Pick<AssessRun, 'run_id' | 'kind' | 'mode' | 'items' | 'goal' | 'as_of_date' | 'date_mode' | 'rerun_of' | 'models' | 'started_at'>

export type AssessEvent =
  | { event: 'run'; run: Header }
  | { event: 'step'; step: AssessStep; attempt: number | null; status: 'running' | 'done' | 'failed'; data: Record<string, unknown> }
  | { event: 'done'; run: AssessRun }
  | { event: 'error'; message: string; step: AssessStep | null }

export interface AssessRequest {
  mode: AssessMode
  items: Item[]
  goal: string | null
  description: string | null
  as_of_date: string
  date_mode: DateMode
  rerun_of: string | null
}

// ---------------------------------------------------------------------------- reducer

export function reduceAssess(state: LiveAssess | null, e: AssessEvent): LiveAssess | null {
  if (e.event === 'run') {
    return {
      ...e.run, finished_at: null, status: 'running', attempts: [], candidates: null, profiles: null, evidence: null,
      report: null, citations: null, usage: null, error: null, failed_step: null, pending: null,
    }
  }
  if (e.event === 'done') return { ...e.run, pending: null }
  if (!state) return state
  if (e.event === 'error') return { ...state, error: e.message, failed_step: e.step, pending: null }
  const s: LiveAssess = { ...state, attempts: state.attempts.map((a) => ({ ...a })) }
  if (e.status === 'running') s.pending = { step: e.step, attempt: e.attempt }
  else s.pending = null
  const d = e.data
  if (e.step === 'generate_cypher' || e.step === 'check_cypher' || e.step === 'run_query') {
    const n = e.attempt ?? 1
    let a = s.attempts.find((x) => x.attempt === n)
    if (!a) {
      a = { attempt: n, generate: null, check: null, run: null, retry_of: (d.retry_of as Feedback | null) ?? null }
      s.attempts.push(a)
    }
    if (e.status !== 'running') {
      if (e.step === 'generate_cypher') a.generate = d as unknown as CandGenerate
      if (e.step === 'check_cypher') a.check = d as unknown as CheckStep
      if (e.step === 'run_query') a.run = d as unknown as RunStep
    }
    return s
  }
  if (e.status === 'running') {
    if (e.step === 'write_report') s.report = { source: 'llm', prompt: (d.prompt as string) ?? null, raw: null, parsed: null, parsing_error: null, elapsed_ms: null }
    return s
  }
  if (e.step === 'build_profiles') {
    const { candidates, ...profiles } = d as unknown as Profiles & { candidates: Candidates }
    s.candidates = candidates
    s.profiles = profiles
  }
  if (e.step === 'lookup_evidence') s.evidence = d as unknown as Evidence
  if (e.step === 'write_report') s.report = d as unknown as ReportStep
  if (e.step === 'check_citations') s.citations = d as unknown as Citations
  return s
}

export function streamAssess(body: AssessRequest, onEvent: (e: AssessEvent) => void, signal: AbortSignal) {
  return postSSE<AssessEvent>('/api/assess', body, onEvent, signal)
}

// ---------------------------------------------------------------------------- queries

export interface CatalogueProduct {
  id: string
  node_id: string
  name: string
  description: string
  hs_code: number | null
  hs_description: string | null
  category: string
  note: string | null
  shipments: number
  companies: string[]
}

export interface CatalogueCategory {
  key: string
  label: string
  description: string
  icon: string
  products: number
  shipments: number
  companies: number
}

export interface Catalogue {
  as_of: string
  status: string | null
  basis: string | null
  categories: CatalogueCategory[]
  products: CatalogueProduct[]
}

export const useCatalogue = (asOf: string | null) =>
  useQuery({
    queryKey: ['products', asOf],
    queryFn: ({ signal }) => getJson<Catalogue>('/products', { as_of: asOf }, signal),
    staleTime: 5 * 60_000,
  })

export interface AssessSummary {
  run_id: string
  mode: AssessMode
  status: AssessStatus
  started_at: string
  as_of_date: string
  date_mode: DateMode
  rerun_of: string | null
  item_count: number
  first_items: string[]
  goal: string | null
  summary: string | null
  tokens: number | null
  models: { cypher: string; report: string } | null
}

export const useAssessRuns = (mode: AssessMode | null) =>
  useQuery({
    queryKey: ['assess', 'runs', mode],
    queryFn: ({ signal }) => getJson<{ runs: AssessSummary[] }>('/runs', { mode, limit: 200 }, signal),
  })

export const useAssessRun = (runId: string | null, enabled = true) =>
  useQuery({
    queryKey: ['assess', 'run', runId],
    queryFn: ({ signal }) => getJson<AssessRun>(`/runs/${encodeURIComponent(runId!)}`, {}, signal),
    enabled: !!runId && enabled,
    staleTime: Infinity,
  })

// ---------------------------------------------------------------------------- labels and helpers

export const STEP_LABEL: Record<AssessStep, string> = {
  generate_cypher: 'Cypher LLM: find candidates',
  check_cypher: 'Check the query',
  run_query: 'Run on Neo4j (read-only)',
  build_profiles: 'Supplier profiles (fixed queries, as of the date)',
  lookup_evidence: 'Risk engine evidence (as of the date)',
  write_report: 'Risk LLM: compare and rank',
  check_citations: 'Citation check (flag only)',
}

export const STATUS_META: Record<AssessStatus, { label: string; tone: 'ok' | 'warn' | 'bad' | 'busy' }> = {
  running: { label: 'Running', tone: 'busy' },
  answered: { label: 'Answered', tone: 'ok' },
  country_level: { label: 'Country level', tone: 'warn' },
  insufficient_data: { label: 'Not enough data', tone: 'warn' },
  failed: { label: 'Failed', tone: 'bad' },
  cancelled: { label: 'Stopped', tone: 'warn' },
}

export const FACTOR_LABEL: Record<DecidingFactor, string> = {
  match: 'Match',
  risk: 'Risk',
  track_record: 'Track record',
}

export const GOAL_EXAMPLES = [
  'Best supplier per item',
  'Which risks should I watch for these items?',
  'Where are the single points of failure?',
]

export const DESCRIBE_EXAMPLES = [
  'Who supplies parts for air filters?',
  'Which hair care suppliers are least exposed to risk?',
  'Is sourcing vacuum spares from Malaysia risky right now?',
  'Should we source fans from Vietnam instead?',
]

/** Uniform random day in the study window (R12). */
export function randomStudyDate(): string {
  const a = Date.parse(`${STUDY_START}T00:00:00Z`)
  const b = Date.parse(`${STUDY_END}T00:00:00Z`)
  const days = Math.round((b - a) / 86_400_000)
  const pick = Math.floor(Math.random() * (days + 1))
  return new Date(a + pick * 86_400_000).toISOString().slice(0, 10)
}

export const inWindow = (d: string) => /^\d{4}-\d{2}-\d{2}$/.test(d) && d >= STUDY_START && d <= STUDY_END

/** Parse a citation id: evidence id, graph:<sid>:<field> or match:<n>:<sid>. */
export function parseCitation(c: string): { kind: 'evidence' | 'graph' | 'match'; supplierId?: string; field?: string; item?: number } {
  if (c.startsWith('graph:')) {
    const rest = c.slice(6)
    const cut = rest.lastIndexOf(':')
    return { kind: 'graph', supplierId: rest.slice(0, cut), field: rest.slice(cut + 1) }
  }
  if (c.startsWith('match:')) {
    const rest = c.slice(6)
    const cut = rest.indexOf(':')
    return { kind: 'match', item: Number(rest.slice(0, cut)), supplierId: rest.slice(cut + 1) }
  }
  return { kind: 'evidence' }
}

export const supplierNodeId = (sid: string) => `supplier:${sid}`
export const explorerSupplierHref = (sid: string) => `/explorer?suppliers=${encodeURIComponent(supplierNodeId(sid))}`

/** Anchor ids inside layer 3, so citation chips can jump to the exact input. */
export const anchor = {
  evidence: (id: string) => `trace-ev-${id}`,
  supplier: (sid: string) => `trace-sup-${sid.replace(/[^A-Za-z0-9_-]/g, '_')}`,
  match: (item: number) => `trace-match-${item}`,
}

/** Scroll to an anchor in layer 3 and flash it. */
export function scrollToAnchor(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.animate(
    [{ boxShadow: '0 0 0 3px color-mix(in oklab, var(--color-primary, #888) 45%, transparent)' }, { boxShadow: '0 0 0 0 transparent' }],
    { duration: 1600, easing: 'ease-out' },
  )
}

export function supplierName(run: AssessRun, sid: string): string {
  const p = run.profiles?.profiles[sid]
  if (p) return p.supplier_name
  for (const cs of Object.values(run.candidates?.by_item ?? {})) {
    const c = cs.find((x) => x.supplier_id === sid)
    if (c?.supplier_name) return c.supplier_name
  }
  return sid
}

export function requestTitle(run: Pick<AssessRun, 'mode' | 'items' | 'goal'>): string {
  if (run.mode === 'describe') return run.items[0]?.text ?? ''
  const first = run.items.slice(0, 3).map((i) => i.text).join(', ')
  return run.items.length > 3 ? `${first} +${run.items.length - 3} more` : first
}
