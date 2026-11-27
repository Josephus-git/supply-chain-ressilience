/**
 * Layer 3, "How this answer was reached": the timeline of one run in pipeline
 * order. Candidate finding (parts list: catalogue ids or vector search, then a
 * fixed supplier query; describe: Cypher LLM query, checks, rows, any retry, any
 * labelled country suggestion) -> fixed profile queries -> risk engine evidence -> risk LLM ->
 * citation check. Each step appears as it starts and fills in when done; the
 * finished timeline is exactly what the risk LLM was given. "Reasoning" here
 * means that input, not the model's hidden reasoning.
 */
import { AlertTriangle, Globe2, RotateCcw } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { CypherBlock, Disclosure, ms, PromptText, StepIcon } from '@/components/ask/parts'
import { RowsGraphView, RowsTable } from '@/components/ask/RowsView'
import {
  anchor, explorerSupplierHref, scrollToAnchor, STEP_LABEL, supplierName, supplierNodeId,
  type AssessStep, type CandAttempt, type EngineLink, type LiveAssess, type Profile, type RetrievalTrace,
} from '@/lib/assess'
import { dateLabel, fmt } from '@/lib/format'
import { cn } from '@/lib/utils'

type State = 'running' | 'done' | 'failed' | 'waiting'

function Step({ n, step, state, elapsed, retry, children, last }: {
  n: number; step: AssessStep; state: State; elapsed?: number | null; retry?: boolean; children?: ReactNode; last?: boolean
}) {
  return (
    <li className="relative flex gap-3 pb-6" data-step={step} data-state={state}>
      {!last && <span aria-hidden className="absolute top-7 bottom-0 left-3 w-px -translate-x-1/2 bg-border" />}
      <StepIcon state={state} />
      <div className="min-w-0 flex-1 space-y-2.5">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 pt-0.5">
          <span className="text-xs text-muted-foreground tabular">{n}.</span>
          <h3 className="text-sm font-medium">{STEP_LABEL[step]}</h3>
          {retry && <span className="rounded bg-amber-500/15 px-1.5 text-[10px] font-medium text-amber-800 dark:text-amber-300">retry</span>}
          {state === 'running' && <span className="text-xs text-muted-foreground">working…</span>}
          {elapsed != null && <span className="ml-auto text-[11px] text-muted-foreground tabular">{ms(elapsed)}</span>}
        </div>
        {children}
      </div>
    </li>
  )
}

const isPending = (run: LiveAssess, step: AssessStep, attempt: number | null = null) =>
  run.pending?.step === step && (attempt === null || run.pending.attempt === attempt)

function stateOf(run: LiveAssess, step: AssessStep, has: boolean, ok = true, attempt: number | null = null): State {
  if (isPending(run, step, attempt)) return 'running'
  if (run.failed_step === step && !has) return 'failed'
  if (!has) return 'waiting'
  return ok ? 'done' : 'failed'
}

function Checks({ checks }: { checks: { name: string; ok: boolean; detail: string }[] }) {
  return (
    <ul className="grid gap-1 text-xs sm:grid-cols-2">
      {checks.map((c, i) => (
        <li key={i} className={cn('flex items-start gap-1.5 rounded px-2 py-1', !c.ok && 'bg-red-500/8')}>
          <span className={cn('mt-px font-semibold', c.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>{c.ok ? '✓' : '✕'}</span>
          <span className={cn(!c.ok && 'text-red-700 dark:text-red-300', c.name === 'server_note' && 'text-muted-foreground')}>{c.detail}</span>
        </li>
      ))}
    </ul>
  )
}

function attemptSteps(run: LiveAssess, a: CandAttempt, n: number, highlight: string[]): { nodes: ReactNode[]; next: number } {
  const out: ReactNode[] = []
  const feedback = a.generate?.feedback ?? a.retry_of
  const g = a.generate
  out.push(
    <Step key={`g${a.attempt}`} n={n++} step="generate_cypher" retry={a.attempt > 1}
      state={stateOf(run, 'generate_cypher', !!g, !g?.parsing_error, a.attempt)} elapsed={g?.elapsed_ms}>
      {feedback && (
        <div className="flex gap-2 rounded-md border border-amber-500/30 bg-amber-500/8 px-3 py-2 text-xs">
          <RotateCcw className="mt-0.5 size-3.5 shrink-0 text-amber-600" />
          <div><div className="font-medium">Retry: the previous attempt's problem was sent back to the model</div><div className="mt-0.5 text-muted-foreground">{feedback.problem}</div></div>
        </div>
      )}
      {g && (
        <>
          {g.interpretation && <p className="text-xs text-muted-foreground">Read as: {g.interpretation}</p>}
          {g.parsing_error && <div className="rounded-md border border-red-500/30 bg-red-500/8 px-3 py-2 font-mono text-xs text-red-700 dark:text-red-300">{g.parsing_error}</div>}
          <CypherBlock cypher={g.cypher || '(no Cypher)'} />
          {g.suggested_countries.length > 0 && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/8 px-3 py-2 text-xs">
              <div className="flex items-center gap-1.5 font-medium"><Globe2 className="size-3.5" /> Countries suggested to the risk engine (a recommendation, not retrieved data)</div>
              <ul className="mt-1 space-y-0.5">
                {g.suggested_countries.map((c, i) => <li key={i}><span className="font-mono font-semibold">{c.code}</span> · {c.reason}</li>)}
              </ul>
            </div>
          )}
          <Disclosure title={<>Prompt sent to {run.models.cypher}: the request, rules, an example and the schema</>}><PromptText text={g.prompt} /></Disclosure>
          <Disclosure title="Raw reply"><pre className="max-h-60 overflow-auto font-mono text-[11px] whitespace-pre-wrap">{typeof g.raw === 'string' ? g.raw : JSON.stringify(g.raw, null, 2)}</pre></Disclosure>
        </>
      )}
    </Step>,
  )
  if (a.check || isPending(run, 'check_cypher', a.attempt)) {
    out.push(
      <Step key={`c${a.attempt}`} n={n++} step="check_cypher" retry={a.attempt > 1}
        state={stateOf(run, 'check_cypher', !!a.check, a.check?.ok, a.attempt)} elapsed={a.check?.elapsed_ms}>
        {a.check && <Checks checks={a.check.checks} />}
      </Step>,
    )
  }
  if (a.run || isPending(run, 'run_query', a.attempt)) {
    const r = a.run
    const graph = r?.graph && (r.graph.nodes.length > 0 || r.graph.omitted) ? r.graph : null
    out.push(
      <Step key={`r${a.attempt}`} n={n++} step="run_query" retry={a.attempt > 1}
        state={stateOf(run, 'run_query', !!r, r?.ok, a.attempt)} elapsed={r?.elapsed_ms}>
        {r && !r.ok && <div className="rounded-md border border-red-500/30 bg-red-500/8 px-3 py-2 font-mono text-xs text-red-700 dark:text-red-300">{r.error}</div>}
        {r?.ok && (
          <div className={cn('grid gap-3', graph && 'xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]')}>
            <RowsTable result={r} fileName={`${run.run_id}-candidates-attempt${a.attempt}`} />
            {graph && <div className="h-[420px]"><RowsGraphView graph={graph} question={run.goal ?? run.items[0]?.text} highlight={highlight} /></div>}
          </div>
        )}
        {a.problem && a.attempt < run.attempts.length && <div className="text-xs text-amber-700 dark:text-amber-300">Problem: {a.problem} The request goes back to the model once.</div>}
      </Step>,
    )
  }
  return { nodes: out, next: n }
}

function RetrievalBody({ t, run }: { t: RetrievalTrace; run: LiveAssess }) {
  const q = t.supplier_query
  return (
    <>
      <p className="text-xs text-muted-foreground">
        No LLM in this step. A catalogue item matches its own product id. A typed item is embedded with {t.embedding_model} and
        compared with every product's stored embedding; the top {t.top_k} are kept if their score is at least{' '}
        <span className="font-medium text-foreground tabular">{t.min_score}</span> (scores are Neo4j's {t.score_scale}).
        An item with nothing above the threshold gets no candidates.
      </p>
      <div className="space-y-1.5">
        {t.items.map((it) => (
          <div key={it.item} className="rounded-md border px-3 py-2 text-xs">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-medium">{it.item}. {it.text}</span>
              <span className="text-muted-foreground">{it.method === 'catalogue' ? 'catalogue product' : 'vector search'}</span>
              {it.method === 'vector' && it.product_ids.length === 0 && (
                <span className="rounded bg-amber-500/15 px-1.5 text-[10px] font-medium text-amber-800 dark:text-amber-300">nothing above {it.threshold}</span>
              )}
            </div>
            {it.method === 'catalogue' ? (
              <div className="mt-0.5 font-mono text-[11px]">{it.product_ids.join(', ')}</div>
            ) : (
              <table className="mt-1 w-full text-left">
                <thead className="text-[10.5px] text-muted-foreground">
                  <tr><th className="font-normal">product</th><th className="font-normal">description</th><th className="text-right font-normal">score</th><th className="text-right font-normal">shipments by the date</th><th className="text-right font-normal">kept</th></tr>
                </thead>
                <tbody>
                  {it.results.map((r) => (
                    <tr key={r.product_id} className={cn(!r.passed && 'text-muted-foreground')}>
                      <td className="pr-2 font-mono text-[11px]">{r.product_id}</td>
                      <td className="pr-2">{r.product_description ?? r.hs_code_description ?? ''}</td>
                      <td className="text-right tabular">{r.score.toFixed(4)}</td>
                      <td className="text-right tabular">{fmt(r.shipments)}</td>
                      <td className={cn('text-right font-semibold', r.passed ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground')}>{r.passed ? '✓' : '✕'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ))}
      </div>
      {q.targets.length === 0 ? (
        <p className="text-xs text-muted-foreground">No product was kept, so the supplier query did not run.</p>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">Fixed query: every supplier that shipped a kept product ({q.row_count} rows). Dates are applied in the next step.</p>
          <RowsTable result={{ ok: true, columns: q.columns, rows: q.rows, row_count: q.row_count, truncated: false, elapsed_ms: q.elapsed_ms }} fileName={`${run.run_id}-candidates`} />
        </>
      )}
      <Disclosure title={`The ${t.queries.length} fixed queries of this step`}>
        <div className="space-y-3">
          {t.queries.map((x, i) => (
            <div key={i} className="space-y-1">
              <div className="flex gap-2 text-[11px] text-muted-foreground"><span className="font-mono">{x.name}</span><span>{x.row_count} rows</span><span>{ms(x.elapsed_ms)}</span></div>
              <CypherBlock cypher={x.cypher} />
              <div className="font-mono text-[10.5px] text-muted-foreground">params: {JSON.stringify(x.params)}</div>
            </div>
          ))}
        </div>
      </Disclosure>
    </>
  )
}

function ProfileCard({ p, run }: { p: Profile; run: LiveAssess }) {
  const fw = p.footprint_window
  const list = (xs: { name?: string; code?: string; shipments: number }[], max = 4) =>
    xs.slice(0, max).map((x) => `${x.name ?? x.code} (${x.shipments})`).join(', ') + (xs.length > max ? `, +${xs.length - max}` : '')
  const links = run.evidence?.by_supplier[p.supplier_id]?.links
  return (
    <div id={anchor.supplier(p.supplier_id)} className="scroll-mt-20 rounded-md border bg-background p-3 text-xs" data-anchor>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <Link to={explorerSupplierHref(p.supplier_id)} className="text-sm font-medium hover:underline">{p.supplier_name}</Link>
        <span className="font-mono text-[10px] text-muted-foreground">{p.supplier_id}</span>
      </div>
      <dl className="mt-2 grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-0.5">
        <dt className="text-muted-foreground">shipments</dt><dd className="tabular">{fmt(fw.shipments)} <span className="font-mono text-[10px] text-muted-foreground">graph:…:shipments</span></dd>
        <dt className="text-muted-foreground">first / last arrival</dt><dd>{dateLabel(fw.first_arrival)} → {dateLabel(fw.last_arrival)}</dd>
        <dt className="text-muted-foreground">country (reported)</dt><dd>{p.country} · currency {p.currency}</dd>
        <dt className="text-muted-foreground">parent</dt><dd>{p.parent_companies.join(', ')}</dd>
        <dt className="text-muted-foreground">exit ports</dt><dd>{list(p.exit_ports)}</dd>
        <dt className="text-muted-foreground">entry ports</dt><dd>{list(p.entry_ports)}</dd>
        <dt className="text-muted-foreground">carriers</dt><dd>{list(p.carriers)}</dd>
        <dt className="text-muted-foreground">HS codes</dt><dd className="font-mono text-[11px]">{list(p.hs_codes, 6)}</dd>
        {links && (
          <>
            <dt className="text-muted-foreground">evidence linked</dt>
            <dd>{links.length === 0 ? 'none as of the date' : <LinkList links={links} />}</dd>
          </>
        )}
      </dl>
    </div>
  )
}

function LinkList({ links }: { links: EngineLink[] }) {
  return (
    <span className="flex flex-wrap gap-1">
      {links.map((l) => (
        <button type="button" key={l.evidence_id} onClick={() => scrollToAnchor(anchor.evidence(l.evidence_id))}
          className={cn('rounded border px-1 font-mono text-[10.5px] hover:bg-muted', l.link_strength === 'weak' && 'border-dashed text-muted-foreground')}
          title={`${l.link_basis} (${l.link_strength})${l.matched_values.length ? `: ${l.matched_values.join(', ')}` : ''}`}>
          {l.evidence_id}
        </button>
      ))}
    </span>
  )
}

export function Timeline({ run }: { run: LiveAssess }) {
  const blocks: ReactNode[] = []
  let n = 1
  const highlight = Object.values(run.candidates?.by_item ?? {}).flat().map((c) => supplierNodeId(c.supplier_id))
  const rt = run.retrieval_trace
  if (rt || isPending(run, 'retrieve_candidates') || run.failed_step === 'retrieve_candidates') {
    blocks.push(
      <Step key="v" n={n++} step="retrieve_candidates" state={stateOf(run, 'retrieve_candidates', !!rt)} elapsed={rt?.elapsed_ms}>
        {rt && <RetrievalBody t={rt} run={run} />}
      </Step>,
    )
  }
  for (const a of run.attempts) {
    const r = attemptSteps(run, a, n, highlight)
    blocks.push(...r.nodes)
    n = r.next
  }

  const profiles = run.profiles
  if (profiles || isPending(run, 'build_profiles') || run.failed_step === 'build_profiles') {
    const byItem = run.candidates?.by_item ?? {}
    blocks.push(
      <Step key="p" n={n++} step="build_profiles" state={stateOf(run, 'build_profiles', !!profiles)} elapsed={profiles?.elapsed_ms}>
        {profiles && (
          <>
            <p className="text-xs text-muted-foreground">
              Fixed queries, not written by an LLM: every count below includes only shipments that arrived on or before {dateLabel(run.as_of_date)}.
            </p>
            <div className="space-y-1.5">
              {run.items.map((it) => {
                const cs = byItem[String(it.n)] ?? []
                return (
                  <div key={it.n} id={anchor.match(it.n)} className="scroll-mt-20 rounded-md border px-3 py-2 text-xs" data-anchor>
                    <div className="font-medium">{it.n}. {it.text}</div>
                    {cs.length === 0 ? (
                      <div className="text-muted-foreground">No candidate found by the query.</div>
                    ) : (
                      <ul className="mt-1 space-y-0.5">
                        {cs.map((c) => (
                          <li key={c.supplier_id}>
                            <span className={cn(!c.active && 'text-muted-foreground line-through')}>{supplierName(run, c.supplier_id)}</span>
                            {!c.active && <span className="ml-1 text-muted-foreground">(no shipments by the date)</span>}
                            {c.products.length > 0 && (
                              <span className="text-muted-foreground"> · {c.products.map((p) => `${p.product_id} ×${p.shipments}, last ${p.last_arrival}`).join('; ')}</span>
                            )}
                            {c.active && c.product_ids.length > 0 && c.products.length === 0 && (
                              <span className="text-muted-foreground"> · matched products had no shipments by the date</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )
              })}
            </div>
            {(profiles.inactive.length > 0 || profiles.unknown.length > 0 || (run.candidates?.after_as_of.length ?? 0) > 0) && (
              <div className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
                {profiles.inactive.length > 0 && <div>Not yet supplying on the date (no profile): {profiles.inactive.map((s) => s.supplier_name).join(', ')}.</div>}
                {profiles.unknown.length > 0 && <div>Supplier ids from the query that are not in the graph: {profiles.unknown.join(', ')}.</div>}
                {(run.candidates?.after_as_of.length ?? 0) > 0 && <div>{run.candidates!.after_as_of.length} matched (item, supplier, product) pairs only shipped after the date and were dropped.</div>}
              </div>
            )}
            <div className="grid gap-2 lg:grid-cols-2">
              {Object.values(profiles.profiles).map((p) => <ProfileCard key={p.supplier_id} p={p} run={run} />)}
            </div>
            <Disclosure title={`The ${profiles.queries.length} fixed queries that built these profiles`}>
              <div className="space-y-3">
                {profiles.queries.map((q, i) => (
                  <div key={i} className="space-y-1">
                    <div className="flex gap-2 text-[11px] text-muted-foreground"><span className="font-mono">{q.name}</span><span>{q.row_count} rows</span><span>{ms(q.elapsed_ms)}</span></div>
                    <CypherBlock cypher={q.cypher} />
                    <div className="font-mono text-[10.5px] text-muted-foreground">params: {JSON.stringify(q.params)}</div>
                  </div>
                ))}
              </div>
            </Disclosure>
          </>
        )}
      </Step>,
    )
  }

  const ev = run.evidence
  if (ev || isPending(run, 'lookup_evidence') || run.failed_step === 'lookup_evidence') {
    blocks.push(
      <Step key="e" n={n++} step="lookup_evidence" state={stateOf(run, 'lookup_evidence', !!ev)} elapsed={ev?.elapsed_ms}>
        {ev && (
          <>
            <p className="text-xs text-muted-foreground">
              The deterministic engine, with as_of_date {ev.as_of_date} and a {ev.event_window_days}-day event window. One call per supplier
              {Object.keys(ev.by_country).length > 0 && ', plus country-level lookups'}. Snapshot <span className="font-mono">{ev.snapshot_id}</span>.
            </p>
            {Object.keys(ev.by_supplier).length > 0 && (
              <ul className="space-y-1 text-xs">
                {Object.entries(ev.by_supplier).map(([sid, c]) => (
                  <li key={sid} className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-medium">{supplierName(run, sid)}</span>
                    <span className="text-muted-foreground">{c.links.length} linked</span>
                    {c.status !== 'completed' && <span className="text-red-600">engine {c.status}</span>}
                    <LinkList links={c.links} />
                  </li>
                ))}
              </ul>
            )}
            {Object.keys(ev.by_country).length > 0 && (
              <div className="space-y-1 rounded-md border px-3 py-2 text-xs">
                <div className="flex items-center gap-1.5 font-medium"><Globe2 className="size-3.5" /> Country-level lookups</div>
                {Object.values(ev.by_country).map((c) => (
                  <div key={c.code} className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-mono font-semibold">{c.code}</span>
                    <span className={cn('rounded border px-1 text-[10px]', c.basis === 'suggested' && 'border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300')}>
                      {c.basis === 'suggested' ? 'suggested by the Cypher LLM' : 'named in the request'}
                    </span>
                    <span className="text-muted-foreground">{c.reason}</span>
                    <LinkList links={c.links} />
                  </div>
                ))}
                {ev.countries_skipped.map((c) => <div key={c.code} className="text-muted-foreground">{c.code}: skipped. {c.reason_skipped}</div>)}
              </div>
            )}
            {Object.keys(ev.records).length > 0 ? (
              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">Evidence records given to the risk LLM ({Object.keys(ev.records).length})</div>
                <div className="grid gap-1.5 lg:grid-cols-2">
                  {Object.values(ev.records).map((r) => (
                    <div key={r.evidence_id} id={anchor.evidence(r.evidence_id)} data-anchor className="scroll-mt-20 rounded-md border bg-background px-3 py-2 text-xs">
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <Link to={`/evidence/${encodeURIComponent(r.evidence_id)}`} className="font-mono text-[11px] font-medium hover:underline">{r.evidence_id}</Link>
                        <span className="text-muted-foreground">{r.risk_label}</span>
                        <span className="ml-auto text-muted-foreground">{r.start ? `${dateLabel(r.start)}${r.end ? ` → ${dateLabel(r.end)}` : ''}` : 'Undated'}</span>
                      </div>
                      <div className="mt-0.5">{r.title}</div>
                      {r.verification_status && <div className="mt-0.5 text-[10.5px] text-muted-foreground">{r.verification_status.replace(/_/g, ' ')}</div>}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">No evidence record links to these suppliers or countries as of the date.</p>
            )}
          </>
        )}
      </Step>,
    )
  }

  const rep = run.report
  if (rep || isPending(run, 'write_report') || run.failed_step === 'write_report') {
    const done = !!rep && (rep.parsed !== null || rep.parsing_error !== null)
    blocks.push(
      <Step key="w" n={n++} step="write_report" state={stateOf(run, 'write_report', done, !!rep?.parsed)} elapsed={rep?.elapsed_ms}>
        {rep?.source === 'pipeline' && <p className="text-xs text-muted-foreground">{rep.reason} The fixed answer "I don't have enough data to support that" was returned and no tokens were spent.</p>}
        {rep?.parsing_error && <div className="rounded-md border border-red-500/30 bg-red-500/8 px-3 py-2 font-mono text-xs text-red-700 dark:text-red-300">{rep.parsing_error}</div>}
        {rep?.prompt && (
          <Disclosure title={<>Exactly what {run.models.report} was given: rules, items, supplier profiles, country lookups and evidence</>}>
            <PromptText text={rep.prompt} />
          </Disclosure>
        )}
        {rep?.raw != null && (
          <Disclosure title="Raw structured output (kept unchanged)">
            <pre className="max-h-80 overflow-auto font-mono text-[11px] whitespace-pre-wrap">{typeof rep.raw === 'string' ? rep.raw : JSON.stringify(rep.raw, null, 2)}</pre>
          </Disclosure>
        )}
      </Step>,
    )
  }

  const cit = run.citations
  if (cit || isPending(run, 'check_citations')) {
    const bad = cit?.checks.filter((c) => c.status === 'not_found' || c.note) ?? []
    blocks.push(
      <Step key="k" n={n++} step="check_citations" state={stateOf(run, 'check_citations', !!cit)} last>
        {cit && (
          <div className="space-y-1.5 text-xs">
            <p>
              {cit.total} citations checked against the {cit.given.length} ids the risk LLM was given:{' '}
              <span className="text-emerald-700 dark:text-emerald-400">{cit.verified} verified</span>,{' '}
              <span className={cit.not_found ? 'text-red-700 dark:text-red-400' : ''}>{cit.not_found} not found</span>.
              Nothing was removed or corrected.
            </p>
            {bad.length > 0 && (
              <ul className="space-y-0.5">
                {bad.map((c, i) => (
                  <li key={i} className={c.status === 'not_found' ? 'text-red-700 dark:text-red-300' : 'text-amber-700 dark:text-amber-300'}>
                    <span className="font-mono">{c.citation}</span> at <span className="font-mono text-muted-foreground">{c.path}</span>: {c.status === 'not_found' ? 'not found' : c.note}
                  </li>
                ))}
              </ul>
            )}
            {cit.uncited_claims.length > 0 && <p className="text-muted-foreground">Claims with no citation: {cit.uncited_claims.join(', ')}.</p>}
          </div>
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
            <div className="font-medium">The assessment stopped{run.failed_step ? ` at "${STEP_LABEL[run.failed_step]}"` : ''}</div>
            <div className="mt-0.5 text-xs text-muted-foreground">{run.error}</div>
          </div>
        </div>
      )}
    </div>
  )
}
