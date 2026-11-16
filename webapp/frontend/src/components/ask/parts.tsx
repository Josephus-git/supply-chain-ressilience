import { Check, ChevronRight, Copy, Loader2, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { toast } from 'sonner'
import { KindSwatch } from '@/components/graph/KindBadge'
import { Button } from '@/components/ui/button'
import { STATUS_META, type NodeRef, type RunStatus } from '@/lib/ask'
import { cn } from '@/lib/utils'

export function copyText(text: string, what = 'Copied') {
  navigator.clipboard?.writeText(text).then(
    () => toast.success(what),
    () => toast.error('Could not copy'),
  )
}

const KEYWORDS = new Set(
  (
    'MATCH OPTIONAL WHERE RETURN WITH ORDER BY DESC ASC LIMIT SKIP AS AND OR NOT IN IS NULL DISTINCT ' +
    'UNWIND CALL YIELD UNION ALL CASE WHEN THEN ELSE END CONTAINS STARTS ENDS EXISTS COUNT COLLECT TRUE FALSE'
  ).split(' '),
)

/** Light Cypher highlighting: keywords, strings, labels/relationship types, comments. */
function highlight(cypher: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(\/\/[^\n]*)|('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")|(:`[^`]*`|:[A-Z_][A-Za-z_]*)|(\b[A-Za-z_]+\b)/g
  let last = 0
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(cypher))) {
    if (m.index > last) out.push(cypher.slice(last, m.index))
    const [tok, comment, str, label, word] = m
    if (comment) out.push(<span key={i++} className="text-muted-foreground italic">{tok}</span>)
    else if (str) out.push(<span key={i++} className="text-emerald-700 dark:text-emerald-400">{tok}</span>)
    else if (label) out.push(<span key={i++} className="text-amber-700 dark:text-amber-300">{tok}</span>)
    else if (word && KEYWORDS.has(word.toUpperCase())) out.push(<span key={i++} className="font-semibold text-sky-700 dark:text-sky-300">{tok}</span>)
    else out.push(tok)
    last = m.index + tok.length
  }
  if (last < cypher.length) out.push(cypher.slice(last))
  return out
}

export function CypherBlock({ cypher, className }: { cypher: string; className?: string }) {
  return (
    <div className={cn('group relative rounded-md border bg-muted/40', className)}>
      <pre className="overflow-x-auto p-3 pr-10 font-mono text-[12px] leading-relaxed whitespace-pre">{highlight(cypher)}</pre>
      <Button
        variant="ghost"
        size="icon"
        className="absolute top-1.5 right-1.5 size-7 opacity-60 group-hover:opacity-100"
        onClick={() => copyText(cypher, 'Cypher copied')}
        aria-label="Copy Cypher"
      >
        <Copy className="size-3.5" />
      </Button>
    </div>
  )
}

/** A collapsed block for long text such as the full prompt sent to the model. */
export function Disclosure({ title, children, className }: { title: ReactNode; children: ReactNode; className?: string }) {
  return (
    <details className={cn('group/d rounded-md border', className)}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-xs text-muted-foreground select-none hover:text-foreground">
        <ChevronRight className="size-3.5 transition-transform group-open/d:rotate-90" />
        {title}
      </summary>
      <div className="border-t p-3">{children}</div>
    </details>
  )
}

export function PromptText({ text }: { text: string }) {
  return (
    <div className="relative">
      <pre className="max-h-80 overflow-auto font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-muted-foreground">{text}</pre>
      <Button variant="outline" size="sm" className="mt-2 h-7 text-xs" onClick={() => copyText(text, 'Prompt copied')}>
        <Copy className="size-3" /> Copy prompt
      </Button>
    </div>
  )
}

const TONE = {
  ok: 'bg-emerald-500/12 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
  warn: 'bg-amber-500/12 text-amber-800 dark:text-amber-300 border-amber-500/30',
  bad: 'bg-red-500/12 text-red-700 dark:text-red-300 border-red-500/30',
  busy: 'bg-sky-500/12 text-sky-700 dark:text-sky-300 border-sky-500/30',
}

export function StatusBadge({ status, className }: { status: RunStatus; className?: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.failed
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium', TONE[meta.tone], className)}>
      {meta.tone === 'busy' && <Loader2 className="size-3 animate-spin" />}
      {meta.label}
    </span>
  )
}

export function StepIcon({ state }: { state: 'running' | 'done' | 'failed' | 'waiting' }) {
  return (
    <span
      className={cn(
        'grid size-6 shrink-0 place-items-center rounded-full border bg-background',
        state === 'done' && 'border-emerald-500/50 text-emerald-600 dark:text-emerald-400',
        state === 'failed' && 'border-red-500/50 text-red-600 dark:text-red-400',
        state === 'running' && 'border-sky-500/50 text-sky-600 dark:text-sky-400',
        state === 'waiting' && 'text-muted-foreground',
      )}
    >
      {state === 'done' && <Check className="size-3.5" />}
      {state === 'failed' && <X className="size-3.5" />}
      {state === 'running' && <Loader2 className="size-3.5 animate-spin" />}
      {state === 'waiting' && <span className="size-1.5 rounded-full bg-current" />}
    </span>
  )
}

export function ms(v: number | null | undefined): string {
  if (v == null) return ''
  return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`
}

// ---------------------------------------------------------------------------- table cells

function NodeChip({ node }: { node: NodeRef }) {
  return (
    <span className="inline-flex max-w-[22rem] items-center gap-1.5 rounded-full border bg-background px-2 py-0.5 text-xs" title={node.id}>
      {node.kind && <KindSwatch kind={node.kind} size={9} />}
      <span className="truncate">{node.name}</span>
    </span>
  )
}

type Obj = Record<string, unknown>
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)

export function Cell({ value }: { value: unknown }): ReactNode {
  if (value === null || value === undefined) return <span className="text-muted-foreground">null</span>
  if (typeof value === 'boolean') return <span className="font-mono text-xs">{String(value)}</span>
  if (typeof value === 'number') return <span className="tabular">{Number.isInteger(value) ? value : Math.round(value * 1000) / 1000}</span>
  if (typeof value === 'string') return <span className="break-words">{value}</span>
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-muted-foreground">[ ]</span>
    const simple = value.every((v) => typeof v !== 'object' || v === null)
    if (simple) return <span className="break-words">{value.map((v) => (v === null ? 'null' : String(v))).join(', ')}</span>
    return (
      <span className="flex flex-wrap gap-1">
        {value.map((v, i) => <Cell key={i} value={v} />)}
      </span>
    )
  }
  if (isObj(value)) {
    if (isObj(value.$node)) return <NodeChip node={value.$node as unknown as NodeRef} />
    if (isObj(value.$rel)) return <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">:{String((value.$rel as Obj).type)}</span>
    if (Array.isArray(value.$path)) {
      const nodes = value.$path as NodeRef[]
      return (
        <span className="flex flex-wrap items-center gap-1">
          {nodes.map((n, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-muted-foreground">→</span>}
              <NodeChip node={n} />
            </span>
          ))}
        </span>
      )
    }
    return <span className="font-mono text-[11px] break-words">{JSON.stringify(value)}</span>
  }
  return String(value)
}

export function cellText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (isObj(value) && isObj(value.$node)) return String((value.$node as Obj).name)
  if (isObj(value) && isObj(value.$rel)) return String((value.$rel as Obj).type)
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
