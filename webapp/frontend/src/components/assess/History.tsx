/**
 * History tab: past assessment runs (runs/assess/), filterable by mode.
 * Opening a run shows it in the normal three-layer view. "Re-run" pre-fills
 * the form with the run's mode, items and goal; the result is a new record
 * linked to the original by `rerun_of`. No side-by-side view.
 */
import { Loader2, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { STATUS_META, useAssessRuns, type AssessMode, type AssessStatus } from '@/lib/assess'
import { dateLabel, fmt } from '@/lib/format'
import { cn } from '@/lib/utils'

const TONE = {
  ok: 'bg-emerald-500/12 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
  warn: 'bg-amber-500/12 text-amber-800 dark:text-amber-300 border-amber-500/30',
  bad: 'bg-red-500/12 text-red-700 dark:text-red-300 border-red-500/30',
  busy: 'bg-sky-500/12 text-sky-700 dark:text-sky-300 border-sky-500/30',
}

export function AssessStatusBadge({ status, className }: { status: AssessStatus; className?: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.failed
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap', TONE[meta.tone], className)}>
      {meta.tone === 'busy' && <Loader2 className="size-3 animate-spin" />}
      {meta.label}
    </span>
  )
}

export function DateModeBadge({ mode }: { mode: 'chosen' | 'random' }) {
  return mode === 'random'
    ? <span className="rounded border border-violet-500/40 bg-violet-500/10 px-1 text-[10px] text-violet-800 dark:text-violet-300">random</span>
    : <span className="rounded border px-1 text-[10px] text-muted-foreground">chosen</span>
}

function when(iso: string) {
  const d = new Date(iso)
  return `${d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} ${d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`
}

export function History({ onOpen, onRerun }: { onOpen: (id: string) => void; onRerun: (id: string) => void }) {
  const [mode, setMode] = useState<AssessMode | 'all'>('all')
  const runs = useAssessRuns(mode === 'all' ? null : mode)
  const ids = new Set(runs.data?.runs.map((r) => r.run_id))

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <ToggleGroup type="single" variant="outline" size="sm" value={mode} onValueChange={(v) => v && setMode(v as typeof mode)}>
          <ToggleGroupItem value="all">All</ToggleGroupItem>
          <ToggleGroupItem value="parts">Parts list</ToggleGroupItem>
          <ToggleGroupItem value="describe">Describe</ToggleGroupItem>
        </ToggleGroup>
        <span className="text-xs text-muted-foreground">Saved in runs/assess/ for the evaluation. A re-run is a new record linked to its original.</span>
      </div>
      {runs.isPending && <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>}
      {runs.isError && <p className="text-sm text-muted-foreground">Could not load runs: {runs.error.message}</p>}
      {runs.data && runs.data.runs.length === 0 && (
        <p className="rounded-md border border-dashed px-3 py-6 text-center text-sm text-muted-foreground">No assessments yet{mode !== 'all' ? ' in this mode' : ''}.</p>
      )}
      {runs.data && runs.data.runs.length > 0 && (
        <div className="overflow-x-auto rounded-lg border">
          <Table className="text-sm">
            <TableHeader className="bg-muted/50">
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Mode</TableHead>
                <TableHead className="w-[40%]">Request</TableHead>
                <TableHead>As of</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Tokens</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.data.runs.map((r) => (
                <TableRow key={r.run_id} className="cursor-pointer align-top" onClick={() => onOpen(r.run_id)} data-run={r.run_id}>
                  <TableCell className="whitespace-nowrap text-xs text-muted-foreground tabular">{when(r.started_at)}</TableCell>
                  <TableCell className="text-xs">{r.mode === 'parts' ? `Parts list (${r.item_count})` : 'Describe'}</TableCell>
                  <TableCell className="whitespace-normal">
                    <div className="line-clamp-2 text-sm">{r.mode === 'parts' ? r.first_items.join(', ') + (r.item_count > 3 ? ` +${r.item_count - 3}` : '') : r.first_items[0]}</div>
                    {r.summary && <div className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{r.summary}</div>}
                    {r.rerun_of && (
                      <button
                        type="button" className="mt-0.5 text-[11px] text-muted-foreground hover:text-foreground hover:underline"
                        onClick={(e) => { e.stopPropagation(); onOpen(r.rerun_of!) }}
                      >
                        re-run of {ids.has(r.rerun_of) ? 'an earlier run' : r.rerun_of}
                      </button>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs">
                    <div className="tabular">{dateLabel(r.as_of_date)}</div>
                    <DateModeBadge mode={r.date_mode} />
                  </TableCell>
                  <TableCell><AssessStatusBadge status={r.status} /></TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground tabular">{r.tokens ? fmt(r.tokens) : '0'}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="outline" size="sm" className="h-7 text-xs"
                      onClick={(e) => { e.stopPropagation(); onRerun(r.run_id) }}
                    >
                      <RotateCcw className="size-3" /> Re-run
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
