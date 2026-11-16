/**
 * Citation chips. Each chip shows the citation as the risk LLM wrote it, and
 * whether the check found it among the inputs the LLM was given (verified) or
 * not (not found). Wrong citations are flagged, never removed (R8).
 * Evidence ids link to the Risk Library; every chip can jump to the exact
 * input in layer 3 ("show in trace").
 */
import { BookOpenText, CircleAlert, CircleCheck, Crosshair, Network, Package } from 'lucide-react'
import { createContext, useContext, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { anchor, parseCitation, supplierName, type AssessRun, type CitationCheck, type Claim } from '@/lib/assess'
import { cn } from '@/lib/utils'

interface Ctx {
  run: AssessRun
  checks: Map<string, CitationCheck>
  /** Open layer 3 and scroll to an anchor. */
  showInTrace: (anchorId: string) => void
}

const CitationContext = createContext<Ctx | null>(null)

export function CitationProvider({ run, showInTrace, children }: { run: AssessRun; showInTrace: (id: string) => void; children: ReactNode }) {
  const checks = new Map((run.citations?.checks ?? []).map((c) => [`${c.path}|${c.citation}`, c]))
  return <CitationContext.Provider value={{ run, checks, showInTrace }}>{children}</CitationContext.Provider>
}

const FIELD_LABEL: Record<string, string> = {
  shipments: 'shipments',
  first_arrival: 'first arrival',
  last_arrival: 'last arrival',
  country: 'country',
  parent: 'parent',
  exit_ports: 'exit ports',
  carriers: 'carriers',
}

function shortName(name: string) {
  return name.length > 22 ? `${name.slice(0, 21)}…` : name
}

export function CitationChip({ citation, path }: { citation: string; path: string }) {
  const ctx = useContext(CitationContext)
  if (!ctx) return null
  const check = ctx.checks.get(`${path}|${citation}`)
  const parsed = parseCitation(citation)
  const status = check?.status ?? (ctx.run.citations ? 'not_found' : undefined)
  const verified = status === 'verified'
  const target =
    parsed.kind === 'evidence' ? anchor.evidence(citation)
      : parsed.kind === 'graph' ? anchor.supplier(parsed.supplierId!)
        : anchor.match(parsed.item!)
  let label: ReactNode
  let Icon = BookOpenText
  if (parsed.kind === 'evidence') label = citation
  else if (parsed.kind === 'graph') {
    Icon = Network
    label = `${shortName(supplierName(ctx.run, parsed.supplierId!))} · ${FIELD_LABEL[parsed.field!] ?? parsed.field}`
  } else {
    Icon = Package
    label = `item ${parsed.item} match · ${shortName(supplierName(ctx.run, parsed.supplierId!))}`
  }
  const record = parsed.kind === 'evidence' ? ctx.run.evidence?.records[citation] : undefined

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          data-citation={citation}
          data-status={status}
          className={cn(
            'mx-0.5 inline-flex max-w-full items-center gap-1 rounded border px-1.5 py-px align-baseline font-mono text-[10.5px] leading-4',
            verified && !check?.note && 'border-emerald-500/35 bg-emerald-500/8 text-emerald-800 dark:text-emerald-300',
            verified && check?.note && 'border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300',
            status === 'not_found' && 'border-red-500/40 bg-red-500/10 text-red-700 line-through decoration-red-500/60 dark:text-red-300',
            !status && 'text-muted-foreground',
          )}
        >
          {verified ? <CircleCheck className="size-3 shrink-0" /> : status === 'not_found' ? <CircleAlert className="size-3 shrink-0" /> : <Icon className="size-3 shrink-0" />}
          {parsed.kind === 'evidence' && verified ? (
            <Link to={`/evidence/${encodeURIComponent(citation)}`} className="truncate hover:underline">{label}</Link>
          ) : (
            <span className="truncate">{label}</span>
          )}
          {status === 'verified' && (
            <button
              type="button"
              className="shrink-0 opacity-60 hover:opacity-100"
              aria-label="Show in trace"
              onClick={(e) => {
                e.preventDefault()
                ctx.showInTrace(target)
              }}
            >
              <Crosshair className="size-3" />
            </button>
          )}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-sm space-y-1">
        <div className="font-medium">
          {status === 'verified' ? 'Verified: this was in the input the risk LLM was given' : status === 'not_found' ? 'Not found: the risk LLM was never given this id' : 'Not checked yet'}
        </div>
        {check?.note && <div>Note: {check.note}.</div>}
        {record && <div className="opacity-80">{record.risk_label}: {record.title}</div>}
        {status === 'verified' && <div className="opacity-70">The crosshair jumps to the exact input in "How this answer was reached".</div>}
        {status === 'not_found' && <div className="opacity-70">Kept as the model wrote it, so the mistake can be studied.</div>}
      </TooltipContent>
    </Tooltip>
  )
}

export function ClaimText({ claim, path, className }: { claim: Claim | null | undefined; path: string; className?: string }) {
  if (!claim) return null
  return (
    <span className={className}>
      {claim.text}
      {claim.citations.length > 0 && ' '}
      {claim.citations.map((c, i) => <CitationChip key={`${c}-${i}`} citation={c} path={path} />)}
    </span>
  )
}

export function CitationTotals({ run }: { run: AssessRun }) {
  const c = run.citations
  if (!c) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 text-[11px] text-muted-foreground">
      <span className="text-emerald-700 dark:text-emerald-400">{c.verified} verified</span>
      <span className={c.not_found ? 'text-red-700 dark:text-red-400' : ''}>{c.not_found} not found</span>
      {c.with_note > 0 && <span className="text-amber-700 dark:text-amber-400">{c.with_note} with a note</span>}
      {c.uncited_claims.length > 0 && <span>{c.uncited_claims.length} uncited claim{c.uncited_claims.length === 1 ? '' : 's'}</span>}
    </span>
  )
}
