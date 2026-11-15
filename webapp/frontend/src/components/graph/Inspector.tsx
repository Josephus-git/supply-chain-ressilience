import {
  ArrowRight, ChevronsDownUp, ChevronsUpDown, Copy, EyeOff, Focus, Loader2, Network, Plus, Ship, X,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useNeighbours } from '@/lib/api'
import { dateLabel, fmt } from '@/lib/format'
import { KIND_META, KIND_ORDER, REL_LABEL, type NodeKind } from '@/lib/kinds'
import type { DateFilter, GEdge, GNode } from '@/lib/types'
import { KindSwatch } from './KindBadge'

function copy(text: string) {
  navigator.clipboard?.writeText(text).then(
    () => toast.success('Copied', { description: text }),
    () => toast.error('Could not copy'),
  )
}

function fmtValue(v: unknown): string {
  if (v == null) return '—'
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function PropertyTable({ props }: { props: Record<string, unknown> }) {
  const [q, setQ] = useState('')
  const entries = Object.entries(props)
    .filter(([k, v]) => !q || k.toLowerCase().includes(q.toLowerCase()) || fmtValue(v).toLowerCase().includes(q.toLowerCase()))
    .sort(([a], [b]) => a.localeCompare(b))
  return (
    <div className="space-y-2">
      {Object.keys(props).length > 8 && (
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter properties" className="h-7 text-xs" />
      )}
      <dl className="divide-y rounded-md border text-xs">
        {entries.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-2 px-2.5 py-1.5">
            <dt className="truncate font-mono text-[11px] text-muted-foreground" title={k}>{k}</dt>
            <dd className="break-words">{fmtValue(v)}</dd>
          </div>
        ))}
        {entries.length === 0 && <div className="px-2.5 py-2 text-muted-foreground">No matching properties</div>}
      </dl>
    </div>
  )
}

function Header({ kind, title, subtitle, id, onClose }: { kind?: NodeKind; title: string; subtitle: string; id: string; onClose: () => void }) {
  return (
    <div className="flex items-start gap-2.5 border-b p-4">
      {kind && <div className="mt-1"><KindSwatch kind={kind} size={16} /></div>}
      <div className="min-w-0 flex-1">
        <div className="text-xs font-medium text-muted-foreground">{subtitle}</div>
        <div className="break-words font-semibold leading-snug">{title}</div>
        <button onClick={() => copy(id)} className="mt-1 flex max-w-full items-center gap-1 font-mono text-[10px] text-muted-foreground hover:text-foreground">
          <span className="truncate">{id}</span>
          <Copy className="size-3 shrink-0" />
        </button>
      </div>
      <Button variant="ghost" size="icon" className="-mr-2 -mt-1 size-7" onClick={onClose} aria-label="Close inspector">
        <X className="size-4" />
      </Button>
    </div>
  )
}

interface NodeProps {
  node: GNode
  dates: DateFilter
  onCanvas: Set<string>
  isSnapshotSupplier: boolean
  busy: boolean
  onClose: () => void
  onExpand: (aggregate: boolean) => void
  onHide: () => void
  onFocus: () => void
  onAddSupplier: () => void
  onAddNeighbour: (n: GNode, e: GEdge) => void
}

export function NodeInspector(p: NodeProps) {
  const { node } = p
  const meta = KIND_META[node.kind]
  const isShipment = node.kind === 'shipment'
  const nb = useNeighbours(node.id, p.dates, !isShipment)

  const groups = useMemo(() => {
    if (!nb.data) return []
    const byId = new Map(nb.data.neighbours.map((n) => [n.id, n]))
    const rows = nb.data.edges.map((e) => {
      const other = e.source === node.id ? e.target : e.source
      return { edge: e, node: byId.get(other)! }
    }).filter((r) => r.node)
    const out = new Map<NodeKind, typeof rows>()
    for (const r of rows) out.set(r.node.kind, [...(out.get(r.node.kind) ?? []), r])
    return KIND_ORDER.filter((k) => out.has(k)).map((k) => ({
      kind: k,
      rows: out.get(k)!.sort((a, b) => (b.edge.shipments ?? 0) - (a.edge.shipments ?? 0) || a.node.name.localeCompare(b.node.name)),
    }))
  }, [nb.data, node.id])

  return (
    <div className="flex h-full flex-col">
      <Header kind={node.kind} title={node.name} subtitle={meta?.label ?? node.label} id={node.id} onClose={p.onClose} />
      <div className="flex flex-wrap gap-1.5 border-b p-3">
        <Button size="sm" onClick={() => p.onExpand(false)} disabled={p.busy}>
          {p.busy ? <Loader2 className="size-3.5 animate-spin" /> : <Network className="size-3.5" />} Expand
        </Button>
        {!isShipment && (
          <Button size="sm" variant="outline" onClick={() => p.onExpand(true)} disabled={p.busy}>
            <Ship className="size-3.5" /> Summarise shipments
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={p.onFocus}><Focus className="size-3.5" /> Focus</Button>
        <Button size="sm" variant="outline" onClick={p.onHide}><EyeOff className="size-3.5" /> Hide</Button>
        {node.kind === 'supplier' && !p.isSnapshotSupplier && (
          <Button size="sm" variant="secondary" onClick={p.onAddSupplier}><Plus className="size-3.5" /> Focus on supplier</Button>
        )}
      </div>
      <Tabs defaultValue="neighbours" className="min-h-0 flex-1 gap-0">
        <TabsList className="mx-3 mt-3 w-[calc(100%-1.5rem)]">
          <TabsTrigger value="neighbours">Neighbours{nb.data ? ` (${nb.data.total})` : ''}</TabsTrigger>
          <TabsTrigger value="properties">Properties ({Object.keys(node.properties).length})</TabsTrigger>
        </TabsList>
        <TabsContent value="properties" className="min-h-0 overflow-y-auto p-3">
          <PropertyTable props={node.properties} />
        </TabsContent>
        <TabsContent value="neighbours" className="min-h-0 overflow-y-auto p-3">
          {nb.isPending && <div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin" /> Loading neighbours</div>}
          {nb.isError && <div className="text-xs text-destructive">{(nb.error as Error).message}</div>}
          {nb.data && (
            <div className="space-y-3">
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                {isShipment
                  ? 'Direct relationships of this shipment.'
                  : 'Reached directly or through a shared shipment; counts are shipments. Click one to add it to the canvas.'}
                {nb.data.truncated && ` Showing ${nb.data.edges.length} of ${nb.data.total}.`}
              </p>
              {groups.map((g) => (
                <div key={g.kind}>
                  <div className="mb-1 flex items-center gap-1.5 text-xs font-medium">
                    <KindSwatch kind={g.kind} size={11} /> {KIND_META[g.kind].plural}
                    <span className="font-normal text-muted-foreground">{g.rows.length}</span>
                  </div>
                  <ul className="space-y-px">
                    {g.rows.slice(0, 40).map(({ edge, node: n }) => {
                      const shown = p.onCanvas.has(n.id)
                      return (
                        <li key={edge.id}>
                          <button
                            onClick={() => p.onAddNeighbour(n, edge)}
                            className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-accent"
                            title={n.name}
                          >
                            <span className={`size-1.5 shrink-0 rounded-full ${shown ? 'bg-foreground/60' : 'border border-muted-foreground/50'}`} title={shown ? 'On canvas' : 'Not on canvas'} />
                            <span className="flex-1 truncate">{n.name}</span>
                            <span className="shrink-0 text-[10px] text-muted-foreground">{REL_LABEL[edge.type] ?? edge.type}</span>
                            {edge.shipments != null && <span className="tabular w-6 shrink-0 text-right font-medium">{edge.shipments}</span>}
                          </button>
                        </li>
                      )
                    })}
                    {g.rows.length > 40 && <li className="px-1.5 text-[11px] text-muted-foreground">+{g.rows.length - 40} more: use Expand</li>}
                  </ul>
                </div>
              ))}
              {groups.length === 0 && <div className="text-xs text-muted-foreground">No neighbours in this date range.</div>}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}

function EdgeEnd({ n, id, onSelect }: { n?: GNode; id: string; onSelect: (id: string) => void }) {
  return (
    <button onClick={() => onSelect(id)} className="flex w-full items-center gap-2 rounded-md border px-2.5 py-2 text-left text-xs hover:bg-accent">
      {n && <KindSwatch kind={n.kind} />}
      <span className="min-w-0 flex-1">
        <span className="block text-[10px] text-muted-foreground">{n ? KIND_META[n.kind].label : 'Node'}</span>
        <span className="block truncate font-medium">{n?.name ?? id}</span>
      </span>
      <ArrowRight className="size-3.5 text-muted-foreground" />
    </button>
  )
}

interface EdgeProps {
  edge: GEdge
  source?: GNode
  target?: GNode
  expanded: boolean
  busy: boolean
  onClose: () => void
  onExpand: () => void
  onCollapse: () => void
  onSelectNode: (id: string) => void
}

export function EdgeInspector({ edge, source, target, expanded, busy, onClose, onExpand, onCollapse, onSelectNode }: EdgeProps) {
  return (
    <div className="flex h-full flex-col">
      <Header
        title={REL_LABEL[edge.type] ? `${edge.type}` : edge.type}
        subtitle={edge.aggregated ? 'Aggregated link' : 'Relationship'}
        id={edge.id}
        onClose={onClose}
      />
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <div className="space-y-1.5">
          <EdgeEnd n={source} id={edge.source} onSelect={onSelectNode} />
          <div className="pl-3 text-[11px] text-muted-foreground">↓ {REL_LABEL[edge.type] ?? edge.type}</div>
          <EdgeEnd n={target} id={edge.target} onSelect={onSelectNode} />
        </div>
        {edge.aggregated ? (
          <>
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div className="rounded-md border p-2"><div className="text-muted-foreground">Shipments</div><div className="text-lg font-semibold">{fmt(edge.shipments)}</div></div>
              <div className="rounded-md border p-2"><div className="text-muted-foreground">First</div><div className="font-medium">{dateLabel(edge.first_arrival)}</div></div>
              <div className="rounded-md border p-2"><div className="text-muted-foreground">Last</div><div className="font-medium">{dateLabel(edge.last_arrival)}</div></div>
            </div>
            <div className="text-xs">
              <div className="mb-1 text-muted-foreground">Collapsed path</div>
              <code className="block rounded-md bg-muted px-2 py-1.5 font-mono text-[11px] break-all">{edge.via}</code>
            </div>
            {expanded ? (
              <Button className="w-full" variant="outline" size="sm" onClick={onCollapse}><ChevronsDownUp className="size-4" /> Collapse shipments</Button>
            ) : (
              <Button className="w-full" size="sm" onClick={onExpand} disabled={busy}>
                {busy ? <Loader2 className="size-4 animate-spin" /> : <ChevronsUpDown className="size-4" />} Expand into {fmt(edge.shipments)} shipments
              </Button>
            )}
          </>
        ) : (
          <div className="text-xs text-muted-foreground">
            <Badge variant="outline" className="mr-1 font-mono">{edge.type}</Badge> A relationship stored in the graph.
          </div>
        )}
        <Separator />
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          The snapshot hides shipment nodes and links each supplier straight to what its shipments touch. Numbers on links count those shipments.
        </p>
      </div>
    </div>
  )
}
