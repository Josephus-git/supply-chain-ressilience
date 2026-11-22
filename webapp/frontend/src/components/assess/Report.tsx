/**
 * Layers 1 and 2 of an assessment.
 *
 * Layer 1 (summary): the answer to the goal, then one row per item
 * (recommended supplier, closest alternative, main risk, deciding factor).
 * The table is built from the risk LLM's structured fields, so it cannot say
 * something the reasoning does not.
 * Layer 2 (expand a row): every ranked candidate with its cited claims, the
 * candidates set aside, country notes, and the mini graph of what the Cypher
 * LLM retrieved (candidate suppliers ringed).
 */
import { ChevronRight, ExternalLink, Flag, Globe2, Network } from 'lucide-react'
import { Fragment, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { RowsGraphView } from '@/components/ask/RowsView'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  explorerSupplierHref, FACTOR_LABEL, INSUFFICIENT, supplierName, supplierNodeId,
  type AssessRun, type DecidingFactor, type ItemAssessment,
} from '@/lib/assess'
import { cn } from '@/lib/utils'
import { ClaimText } from './Citations'
import { SourceBadge } from './Catalogue'

const FACTOR_TONE: Record<DecidingFactor, string> = {
  match: 'border-sky-500/40 bg-sky-500/10 text-sky-800 dark:text-sky-300',
  risk: 'border-rose-500/40 bg-rose-500/10 text-rose-800 dark:text-rose-300',
  track_record: 'border-violet-500/40 bg-violet-500/10 text-violet-800 dark:text-violet-300',
}

export function FactorBadge({ factor }: { factor: DecidingFactor }) {
  return <span className={cn('inline-flex rounded-full border px-2 py-px text-[11px] font-medium whitespace-nowrap', FACTOR_TONE[factor])}>{FACTOR_LABEL[factor] ?? factor}</span>
}

function SupplierLink({ run, sid, className }: { run: AssessRun; sid: string; className?: string }) {
  const p = run.profiles?.profiles[sid]
  return (
    <span className={cn('inline-flex min-w-0 items-baseline gap-1', className)}>
      <Link to={explorerSupplierHref(sid)} className="truncate font-medium hover:underline" title={`${sid} · open in Graph Explorer`}>
        {supplierName(run, sid)}
      </Link>
      {p && <span className="shrink-0 text-[11px] text-muted-foreground">{p.country}</span>}
    </span>
  )
}

const ITEM_STATUS: Record<string, string> = {
  answered: 'Answered',
  country_level: 'Country level',
  insufficient_data: 'Not enough data',
}

function NoSupport({ children }: { children?: ReactNode }) {
  return <span className="text-muted-foreground italic">{children ?? INSUFFICIENT}</span>
}

// ---------------------------------------------------------------------------- layer 2

function ItemReasoning({ run, item, index, graphFor }: { run: AssessRun; item: ItemAssessment; index: number; graphFor: (sids: string[]) => ReactNode }) {
  const base = `items.${index}`
  const sids = item.candidates.map((c) => c.supplier_id)
  const known = new Set(Object.keys(run.profiles?.profiles ?? {}))
  return (
    <div className="space-y-4 py-2">
      {item.candidates.length > 0 && (
        <ol className="space-y-3">
          {item.candidates.map((c, j) => (
            <li key={`${c.supplier_id}-${j}`} className="rounded-lg border bg-background p-3" data-testid="ranked-candidate">
              <div className="flex flex-wrap items-center gap-2">
                <span className="grid size-6 place-items-center rounded-full bg-muted text-xs font-semibold tabular">{j + 1}</span>
                <SupplierLink run={run} sid={c.supplier_id} className="text-sm" />
                {!known.has(c.supplier_id) && (
                  <span className="rounded border border-red-500/40 bg-red-500/10 px-1 text-[10px] text-red-700 dark:text-red-300">not among the profiles given</span>
                )}
                <span className="ml-auto flex items-center gap-1.5 text-[11px] text-muted-foreground">decided by <FactorBadge factor={c.deciding_factor} /></span>
              </div>
              {c.deciding_reason && <p className="mt-1.5 text-xs text-muted-foreground">{c.deciding_reason}</p>}
              <dl className="mt-2.5 grid gap-2 text-sm sm:grid-cols-[7.5rem_minmax(0,1fr)]">
                <dt className="text-xs font-medium text-muted-foreground">Why it matches</dt>
                <dd><ClaimText claim={c.match_reason} path={`${base}.candidates.${j}.match_reason`} /></dd>
                <dt className="text-xs font-medium text-muted-foreground">Risks</dt>
                <dd>
                  {c.risks.length === 0 ? (
                    <span className="text-muted-foreground">None linked as of the date.</span>
                  ) : (
                    <ul className="list-disc space-y-1 pl-4">
                      {c.risks.map((r, k) => <li key={k}><ClaimText claim={r} path={`${base}.candidates.${j}.risks.${k}`} /></li>)}
                    </ul>
                  )}
                </dd>
                <dt className="text-xs font-medium text-muted-foreground">Track record</dt>
                <dd><ClaimText claim={c.track_record} path={`${base}.candidates.${j}.track_record`} /></dd>
              </dl>
            </li>
          ))}
        </ol>
      )}

      {item.set_aside.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-medium text-muted-foreground">Set aside</h4>
          <ul className="space-y-1 text-sm">
            {item.set_aside.map((s, j) => (
              <li key={j} className="flex flex-wrap gap-x-2">
                <SupplierLink run={run} sid={s.supplier_id} />
                <span className="text-muted-foreground">·</span>
                <ClaimText claim={s.reason} path={`${base}.set_aside.${j}.reason`} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {item.country_notes.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><Globe2 className="size-3.5" /> Country-level notes</h4>
          <ul className="space-y-1.5 text-sm">
            {item.country_notes.map((n, j) => {
              const basis = run.evidence?.by_country[n.country_code]?.basis
              const suggested = n.from_suggestion || basis === 'suggested'
              return (
                <li key={j} className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-mono text-xs font-semibold">{n.country_code}</span>
                  {suggested && (
                    <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1 text-[10px] text-amber-800 dark:text-amber-300" title="The Cypher LLM recommended this country to the risk engine; it was not retrieved from the graph.">
                      suggested by the Cypher LLM
                    </span>
                  )}
                  {basis === 'mentioned' && <span className="rounded border px-1 text-[10px] text-muted-foreground">named in the request</span>}
                  <ClaimText claim={n.note} path={`${base}.country_notes.${j}.note`} />
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {item.candidates.length === 0 && item.set_aside.length === 0 && item.country_notes.length === 0 && <NoSupport />}

      {sids.length > 0 && graphFor(sids)}
    </div>
  )
}

// ---------------------------------------------------------------------------- layer 1 + 2

export function Report({ run }: { run: AssessRun }) {
  const report = run.report?.parsed
  const [open, setOpen] = useState<Set<number>>(() => new Set())
  const graph = useMemo(() => {
    const used = [...run.attempts].reverse().find((a) => a.run?.ok)
    const g = used?.run?.graph
    return g && (g.nodes.length > 0 || g.omitted) ? g : null
  }, [run.attempts])
  if (!report) return null

  const toggle = (i: number) => setOpen((s) => {
    const next = new Set(s)
    if (next.has(i)) next.delete(i)
    else next.add(i)
    return next
  })
  const graphFor = (sids: string[]) =>
    graph ? (
      <div className="space-y-1.5">
        <h4 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><Network className="size-3.5" /> What the Cypher LLM retrieved (ranked suppliers ringed)</h4>
        <div className="h-[380px]"><RowsGraphView graph={graph} question={run.goal ?? run.items[0]?.text} highlight={sids.map(supplierNodeId)} /></div>
      </div>
    ) : null
  const itemsByN = new Map(run.items.map((it) => [it.n, it]))

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-primary/25 bg-primary/[0.03] p-4 shadow-xs" data-testid="assess-summary">
        <div className="mb-1 text-xs font-medium text-muted-foreground">
          {run.report?.source === 'pipeline' ? 'Answer (fixed by the pipeline; the risk LLM was not called)' : 'Answer'}
        </div>
        {report.items.some((item) => item.answer?.text) ? (
          <>
            <ul className="divide-y divide-primary/10" data-testid="assess-item-answers">
              {report.items.map((item, i) => (
                <li key={`${item.item}-${i}`} className="py-2 first:pt-1 last:pb-1">
                  <div className="text-xs font-semibold text-muted-foreground">{item.item}. {itemsByN.get(item.item)?.text ?? `Item ${item.item}`}</div>
                  <div className="text-[15px] leading-relaxed">
                    {item.answer?.text ? <ClaimText claim={item.answer} path={`items.${i}.answer`} /> : <NoSupport />}
                  </div>
                </li>
              ))}
            </ul>
            {report.summary?.text?.trim() && (
              <p className="mt-2 border-t border-primary/15 pt-2 text-sm leading-relaxed text-muted-foreground">
                <span className="font-medium">Across all items: </span><ClaimText claim={report.summary} path="summary" />
              </p>
            )}
          </>
        ) : (
          <p className="text-[15px] leading-relaxed"><ClaimText claim={report.summary} path="summary" /></p>
        )}
      </div>

      {run.mode === 'parts' ? (
        <div className="overflow-x-auto rounded-lg border">
          <Table className="text-sm">
            <TableHeader className="bg-muted/50">
              <TableRow>
                <TableHead className="w-8" />
                <TableHead className="w-[22%]">Item</TableHead>
                <TableHead>Recommended supplier</TableHead>
                <TableHead>Closest alternative</TableHead>
                <TableHead className="w-[30%]">Main risk</TableHead>
                <TableHead>Decided by</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.items.map((item, i) => {
                const it = itemsByN.get(item.item)
                const best = item.candidates[0]
                const alt = item.candidates[1]
                const isOpen = open.has(i)
                return (
                  <Fragment key={`${item.item}-${i}`}>
                    <TableRow className="cursor-pointer align-top" onClick={() => toggle(i)} data-state={isOpen ? 'open' : 'closed'}>
                      <TableCell className="pt-3"><ChevronRight className={cn('size-4 text-muted-foreground transition-transform', isOpen && 'rotate-90')} /></TableCell>
                      <TableCell className="whitespace-normal">
                        <div className="font-medium">{item.item}. {it?.text ?? '—'}</div>
                        <div className="mt-0.5 flex gap-1.5">
                          {it && <SourceBadge source={it.source} />}
                          {item.status !== 'answered' && <span className="rounded border border-amber-500/40 px-1 text-[10px] text-amber-800 dark:text-amber-300">{ITEM_STATUS[item.status]}</span>}
                        </div>
                      </TableCell>
                      <TableCell className="whitespace-normal" onClick={(e) => e.stopPropagation()}>
                        {best ? <SupplierLink run={run} sid={best.supplier_id} /> : <NoSupport>{item.status === 'country_level' ? 'Country level only' : 'Not enough data'}</NoSupport>}
                      </TableCell>
                      <TableCell className="whitespace-normal" onClick={(e) => e.stopPropagation()}>
                        {alt ? <SupplierLink run={run} sid={alt.supplier_id} /> : <span className="text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell className="whitespace-normal" onClick={(e) => e.stopPropagation()}>
                        {best?.risks[0] ? <ClaimText claim={best.risks[0]} path={`items.${i}.candidates.0.risks.0`} /> : best ? <span className="text-muted-foreground">None linked</span> : <span className="text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell>{best ? <FactorBadge factor={best.deciding_factor} /> : <span className="text-muted-foreground">—</span>}</TableCell>
                    </TableRow>
                    {isOpen && (
                      <TableRow className="bg-muted/20 hover:bg-muted/20">
                        <TableCell />
                        <TableCell colSpan={5} className="whitespace-normal">
                          <ItemReasoning run={run} item={item} index={i} graphFor={graphFor} />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                )
              })}
            </TableBody>
          </Table>
          <div className="border-t px-3 py-2 text-[11px] text-muted-foreground">
            Click a row for the reasoning behind it: every candidate considered, why, and the cited evidence.
          </div>
        </div>
      ) : (
        report.items.map((item, i) => (
          <div key={i} className="rounded-lg border">
            <ol className="divide-y">
              {item.candidates.map((c, j) => (
                <li key={j} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                  <span className="grid size-6 place-items-center rounded-full bg-muted text-xs font-semibold tabular">{j + 1}</span>
                  <SupplierLink run={run} sid={c.supplier_id} />
                  <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{c.deciding_reason}</span>
                  <FactorBadge factor={c.deciding_factor} />
                </li>
              ))}
              {item.candidates.length === 0 && (
                <li className="flex items-center gap-2 px-3 py-2 text-sm">
                  <Flag className="size-3.5 text-muted-foreground" />
                  {item.status === 'country_level' ? 'No supplier matched; the answer is at country level.' : <NoSupport />}
                </li>
              )}
            </ol>
            <button type="button" onClick={() => toggle(i)} className="flex w-full items-center gap-1.5 border-t px-3 py-2 text-left text-xs text-muted-foreground hover:bg-muted/40 hover:text-foreground">
              <ChevronRight className={cn('size-3.5 transition-transform', open.has(i) && 'rotate-90')} />
              Reasoning: every candidate considered, why, and the cited evidence
            </button>
            {open.has(i) && <div className="border-t px-3"><ItemReasoning run={run} item={item} index={i} graphFor={graphFor} /></div>}
          </div>
        ))
      )}
      {graph && (
        <Link to="/explorer" state={{ askGraph: { nodes: graph.nodes, edges: graph.edges, question: run.goal ?? run.items[0]?.text } }} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ExternalLink className="size-3" /> Open what was retrieved in Graph Explorer
        </Link>
      )}
    </div>
  )
}
