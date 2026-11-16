import { Download, Maximize, Network, X } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { GraphCanvas, type GraphCanvasHandle, type Selection } from '@/components/graph/GraphCanvas'
import { PropertyTable } from '@/components/graph/Inspector'
import { KindSwatch } from '@/components/graph/KindBadge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { RowsGraph, RunStep } from '@/lib/ask'
import { KIND_META, KIND_ORDER } from '@/lib/kinds'
import { useTheme } from '@/lib/theme'
import { Cell, cellText } from './parts'

const PAGE = 50

function downloadCsv(columns: string[], rows: Record<string, unknown>[], name: string) {
  const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s)
  const lines = [columns.map(esc).join(','), ...rows.map((r) => columns.map((c) => esc(cellText(r[c]))).join(','))]
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `${name}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export function RowsTable({ result, fileName }: { result: RunStep; fileName: string }) {
  const [shown, setShown] = useState(PAGE)
  const rows = result.rows ?? []
  const columns = result.columns ?? []
  const numeric = new Set(columns.filter((c) => rows.length > 0 && rows.every((r) => r[c] == null || typeof r[c] === 'number')))
  if (rows.length === 0) {
    return <div className="rounded-md border border-dashed px-3 py-6 text-center text-sm text-muted-foreground">The query returned no rows.</div>
  }
  return (
    <div className="space-y-2">
      <div className="max-h-[420px] overflow-auto rounded-md border">
        <Table className="text-xs">
          <TableHeader className="sticky top-0 z-10 bg-muted/80 backdrop-blur">
            <TableRow>
              <TableHead className="w-8 text-right text-muted-foreground">#</TableHead>
              {columns.map((c) => (
                <TableHead key={c} className={numeric.has(c) ? 'text-right font-mono text-[11px]' : 'font-mono text-[11px]'}>{c}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.slice(0, shown).map((r, i) => (
              <TableRow key={i}>
                <TableCell className="text-right align-top text-muted-foreground tabular">{i + 1}</TableCell>
                {columns.map((c) => (
                  <TableCell key={c} className={`max-w-[28rem] align-top whitespace-normal ${numeric.has(c) ? 'text-right' : ''}`}>
                    <Cell value={r[c]} />
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>
          {rows.length} row{rows.length === 1 ? '' : 's'}
          {result.truncated && ' (capped; the query returned more)'}
        </span>
        {rows.length > shown && (
          <Button variant="outline" size="sm" className="h-6 text-xs" onClick={() => setShown((s) => s + PAGE)}>
            Show {Math.min(PAGE, rows.length - shown)} more
          </Button>
        )}
        <Button variant="ghost" size="sm" className="ml-auto h-6 text-xs" onClick={() => downloadCsv(columns, rows, fileName)}>
          <Download className="size-3" /> CSV
        </Button>
      </div>
    </div>
  )
}

/** Bloom-style view of the nodes in the rows (and the relationships among them). */
export function RowsGraphView({ graph }: { graph: RowsGraph }) {
  const { mode } = useTheme()
  const ref = useRef<GraphCanvasHandle>(null)
  const [selected, setSelected] = useState<Selection>(null)
  const roots = useMemo(() => graph.nodes.filter((n) => n.kind === 'buyer').map((n) => n.id), [graph.nodes])
  const kinds = useMemo(() => KIND_ORDER.filter((k) => graph.nodes.some((n) => n.kind === k)), [graph.nodes])
  const node = selected?.type === 'node' ? graph.nodes.find((n) => n.id === selected.id) : undefined

  if (graph.omitted) {
    return (
      <div className="grid h-full min-h-40 place-items-center rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
        <div>
          <Network className="mx-auto mb-2 size-5" />
          The rows hold {graph.node_count} nodes, too many to draw here. Use the Graph Explorer for big views.
        </div>
      </div>
    )
  }
  return (
    <div className="flex h-full flex-col gap-2">
      <div className="relative min-h-[400px] flex-1 overflow-hidden rounded-md border bg-card">
        <GraphCanvas
          ref={ref}
          nodes={graph.nodes}
          edges={graph.edges}
          mode={mode}
          selected={selected}
          onSelect={setSelected}
          onExpand={() => {}}
          layoutName="fcose"
          roots={roots}
        />
        <Button variant="outline" size="icon" className="absolute top-2 right-2 size-7" onClick={() => ref.current?.fit()} aria-label="Fit graph">
          <Maximize className="size-3.5" />
        </Button>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        {kinds.map((k) => (
          <span key={k} className="flex items-center gap-1"><KindSwatch kind={k} size={8} />{KIND_META[k].plural}</span>
        ))}
      </div>
      {node ? (
        <div className="rounded-md border">
          <div className="flex items-center gap-2 border-b px-3 py-2">
            <KindSwatch kind={node.kind} size={10} />
            <div className="min-w-0 flex-1">
              <div className="text-[11px] text-muted-foreground">{KIND_META[node.kind]?.label}</div>
              <div className="truncate text-sm font-medium" title={node.name}>{node.name}</div>
            </div>
            <Button variant="ghost" size="icon" className="size-6" onClick={() => setSelected(null)} aria-label="Close">
              <X className="size-3.5" />
            </Button>
          </div>
          <div className="max-h-56 overflow-auto p-2"><PropertyTable props={node.properties} /></div>
        </div>
      ) : (
        <div className="text-[11px] text-muted-foreground">
          {graph.nodes.length} nodes · {graph.edges.length} relationships. Click a node for its properties.
        </div>
      )}
    </div>
  )
}
