import { Download, Expand, Maximize, Network, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { GraphCanvas, type GraphCanvasHandle, type Selection } from '@/components/graph/GraphCanvas'
import { PropertyTable } from '@/components/graph/Inspector'
import { hiddenNeighbours, pickStartNodes } from '@/components/graph/startView'
import { KindSwatch } from '@/components/graph/KindBadge'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
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
export function RowsGraphView({ graph, question, highlight }: { graph: RowsGraph; question?: string; highlight?: string[] }) {
  const { mode } = useTheme()
  const navigate = useNavigate()
  const ref = useRef<GraphCanvasHandle>(null)
  const [selected, setSelected] = useState<Selection>(null)
  // Start with ~15 nodes; double-clicking a node reveals more of its links from the result.
  const start = useMemo(() => {
    const s = pickStartNodes(graph.nodes, graph.edges)
    const ids = new Set(graph.nodes.map((n) => n.id))
    for (const id of highlight ?? []) if (ids.has(id)) s.add(id)
    return s
  }, [graph, highlight])
  const [shown, setShown] = useState(start)
  useEffect(() => setShown(start), [start])
  const visible = useMemo(() => {
    const nodes = graph.nodes.filter((n) => shown.has(n.id))
    const edges = graph.edges.filter((e) => shown.has(e.source) && shown.has(e.target))
    return { nodes, edges }
  }, [graph, shown])
  const reveal = (id: string) => {
    const { ids, remaining } = hiddenNeighbours(id, graph.edges, shown)
    if (ids.length === 0) {
      toast.info('Every link of this node in the result is already shown')
      return
    }
    setShown((s) => new Set([...s, ...ids]))
    if (remaining > 0) toast.info(`Showing ${ids.length} more; double-click again for the other ${remaining}`)
  }
  const roots = useMemo(() => visible.nodes.filter((n) => n.kind === 'buyer').map((n) => n.id), [visible.nodes])
  const kinds = useMemo(() => KIND_ORDER.filter((k) => visible.nodes.some((n) => n.kind === k)), [visible.nodes])
  const node = selected?.type === 'node' ? graph.nodes.find((n) => n.id === selected.id) : undefined

  const openInExplorer = () => navigate('/explorer', { state: { askGraph: { nodes: graph.nodes, edges: graph.edges, question, shown: [...shown] } } })
  const fromQuery = graph.source === 'query' && (
    <div className="text-[11px] text-muted-foreground" title={graph.cypher}>
      The rows hold values, not nodes, so these are the nodes the query matched to produce them.
      {graph.rows_capped && ' (capped)'}
    </div>
  )

  if (graph.omitted) {
    return (
      <div className="grid h-full min-h-40 place-items-center rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
        <div className="space-y-2">
          <Network className="mx-auto size-5" />
          <p>The result touches {graph.node_count} nodes, too many to draw. Narrow the question to explore them.</p>
          {fromQuery}
        </div>
      </div>
    )
  }
  return (
    <div className="flex h-full flex-col gap-2">
      <div className="relative min-h-[400px] flex-1 overflow-hidden rounded-md border bg-card">
        <GraphCanvas
          ref={ref}
          nodes={visible.nodes}
          edges={visible.edges}
          mode={mode}
          selected={selected}
          onSelect={setSelected}
          onExpand={reveal}
          layoutName="fcose"
          roots={roots}
          highlight={highlight}
        />
        <div className="absolute top-2 right-2 flex gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline" size="icon" className="size-7" onClick={() => ref.current?.fit()} aria-label="Fit graph">
                <Maximize className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Fit to view</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline" size="icon" className="size-7" aria-label="Open in Graph Explorer"
                onClick={openInExplorer}
              >
                <Expand className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Open in Graph Explorer</TooltipContent>
          </Tooltip>
        </div>
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
          {visible.nodes.length < graph.nodes.length
            ? `Showing ${visible.nodes.length} of ${graph.nodes.length} nodes. Double-click a node to show more of its links; click for its properties.`
            : `${graph.nodes.length} nodes · ${graph.edges.length} relationships. Click a node for its properties.`}
        </div>
      )}
      {fromQuery}
    </div>
  )
}
