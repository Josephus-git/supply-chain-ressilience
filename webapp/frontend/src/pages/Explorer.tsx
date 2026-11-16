import {
  AlertTriangle, Check, ChevronDown, Download, Eye, Loader2, Maximize, RefreshCw, Search, Settings2, X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { GraphCanvas, type GraphCanvasHandle, type LayoutName, type Selection } from '@/components/graph/GraphCanvas'
import { EdgeInspector, NodeInspector } from '@/components/graph/Inspector'
import { KindSwatch } from '@/components/graph/KindBadge'
import { pickStartNodes } from '@/components/graph/startView'
import { useGraphState } from '@/components/graph/useGraphState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { fetchEdgeShipments, fetchNeighbours, useSearch, useSnapshot, useSupplierPicker } from '@/lib/api'
import { fmt } from '@/lib/format'
import { KIND_META, KIND_ORDER, type NodeKind } from '@/lib/kinds'
import { useTheme } from '@/lib/theme'
import type { DateFilter, GEdge, GNode } from '@/lib/types'

/** A query result handed over from Ask the Graph (router state, so it survives a reload but not a new tab). */
interface AskGraph {
  nodes: GNode[]
  edges: GEdge[]
  question?: string
  /** Ids the Ask page was showing; the rest start hidden (unhide or expand to see them). */
  shown?: string[]
}

/** Cap on neighbours added by one expansion, so a busy node (Dyson has ~450 shipments) stays readable. */
const EXPAND_LIMIT = 25
const STUDY = { start: '2025-01-01', end: '2026-09-30' }
const PRESETS: { label: string; from: string | null; to: string | null }[] = [
  { label: 'All dates', from: null, to: null },
  { label: '2025', from: '2025-01-01', to: '2025-12-31' },
  { label: '2026', from: '2026-01-01', to: '2026-09-30' },
  { label: 'Last 6 months', from: '2026-04-01', to: '2026-09-30' },
]

function Section({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

function SupplierPicker({ selected, onChange }: { selected: string[]; onChange: (ids: string[]) => void }) {
  const picker = useSupplierPicker()
  const [open, setOpen] = useState(false)
  const nameOf = useMemo(() => {
    const m = new Map<string, string>()
    picker.data?.companies.forEach((c) => c.suppliers.forEach((s) => m.set(s.id, s.name)))
    return m
  }, [picker.data])
  const toggle = (ids: string[]) => {
    const all = ids.every((id) => selected.includes(id))
    onChange(all ? selected.filter((id) => !ids.includes(id)) : [...new Set([...selected, ...ids])])
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {selected.length === 0 && <Badge variant="outline" className="font-normal text-muted-foreground">All suppliers</Badge>}
        {selected.map((id) => (
          <Badge key={id} variant="secondary" className="max-w-full gap-1 pr-1">
            <span className="truncate">{nameOf.get(id) ?? id.replace('supplier:org:', '')}</span>
            {(
              <button onClick={() => onChange(selected.filter((x) => x !== id))} aria-label="Remove" className="rounded hover:bg-foreground/10">
                <X className="size-3" />
              </button>
            )}
          </Badge>
        ))}
      </div>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" className="w-full justify-between font-normal">
            Focus on a supplier <ChevronDown className="size-4 opacity-60" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-80 p-0" align="start">
          <Command>
            <CommandInput placeholder="Search companies" />
            <CommandList className="max-h-80">
              <CommandEmpty>No supplier found.</CommandEmpty>
              {picker.data?.companies.map((c) => (
                <CommandGroup key={c.company} heading={`${c.company} · ${c.shipments}`}>
                  {c.suppliers.length > 1 && (
                    <CommandItem value={`${c.company} all`} onSelect={() => toggle(c.suppliers.map((s) => s.id))}>
                      <Check className={c.suppliers.every((s) => selected.includes(s.id)) ? 'opacity-100' : 'opacity-0'} />
                      All {c.suppliers.length} supplier nodes
                    </CommandItem>
                  )}
                  {c.suppliers.map((s) => (
                    <CommandItem key={s.id} value={`${c.company} ${s.name} ${s.id}`} onSelect={() => toggle([s.id])}>
                      <Check className={selected.includes(s.id) ? 'opacity-100' : 'opacity-0'} />
                      <span className="flex-1 truncate">{s.name}</span>
                      <span className="text-xs text-muted-foreground">{s.reported_country_code} · {s.shipments}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              ))}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  )
}

function GraphSearch({ onPick }: { onPick: (n: GNode) => void }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const dq = useDebounced(q, 250)
  const res = useSearch(dq)
  return (
    <Popover open={open && q.trim().length >= 2} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <div className="relative">
          <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={q}
            onChange={(e) => { setQ(e.target.value); setOpen(true) }}
            onFocus={() => setOpen(true)}
            placeholder="Name, HS code, BOL, port…"
            className="h-8 pl-8 text-sm"
          />
        </div>
      </PopoverTrigger>
      <PopoverContent className="w-[340px] p-0" align="start" onOpenAutoFocus={(e) => e.preventDefault()}>
        <Command shouldFilter={false}>
          <CommandList className="max-h-80">
            {res.isFetching && !res.data && <div className="p-3 text-xs text-muted-foreground">Searching…</div>}
            {res.data && res.data.results.length === 0 && <CommandEmpty>No matches</CommandEmpty>}
            {res.data && res.data.results.length > 0 && (
              <CommandGroup heading={`${res.data.total} match${res.data.total === 1 ? '' : 'es'}${res.data.total > res.data.results.length ? ` · top ${res.data.results.length}` : ''}`}>
                {res.data.results.map((n) => (
                  <CommandItem key={n.id} value={n.id} onSelect={() => { onPick(n); setOpen(false) }}>
                    <KindSwatch kind={n.kind} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{n.name}</span>
                      <span className="block truncate text-[10px] text-muted-foreground">{KIND_META[n.kind].label} · matched {n.matched?.join(', ')}</span>
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

export default function Explorer() {
  const { mode } = useTheme()
  const [params, setParams] = useSearchParams()
  const urlSuppliers = useMemo(() => (params.get('suppliers') ?? '').split(',').filter(Boolean), [params])
  const dates: DateFilter = useMemo(() => ({ date_from: params.get('from'), date_to: params.get('to') }), [params])
  const full = params.get('full') === '1'
  const location = useLocation()
  const navigate = useNavigate()
  const askGraph = (location.state as { askGraph?: AskGraph } | null)?.askGraph
  const askRoots = useMemo(() => askGraph?.nodes.filter((n) => n.kind === 'buyer').map((n) => n.id) ?? [], [askGraph])
  const leaveAsk = () => navigate('/explorer', { replace: true, state: null })

  const setParam = useCallback(
    (patch: Record<string, string | null>) =>
      setParams((p) => {
        const next = new URLSearchParams(p)
        for (const [k, v] of Object.entries(patch)) {
          if (v == null || v === '') next.delete(k)
          else next.set(k, v)
        }
        return next
      }, { replace: true }),
    [setParams],
  )

  const snapshot = useSnapshot(urlSuppliers, dates, full)
  const graph = useGraphState()
  const canvas = useRef<GraphCanvasHandle>(null)
  const [selected, setSelected] = useState<Selection>(null)
  const [hiddenKinds, setHiddenKinds] = useState<Set<NodeKind>>(new Set())
  const [layout, setLayout] = useState<LayoutName>(() => (askGraph && askRoots.length === 0 ? 'fcose' : 'radial'))
  const [busy, setBusy] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(full)

  const snapshotSuppliers = snapshot.data?.suppliers ?? []

  useEffect(() => {
    if (askGraph) {
      graph.reset(askGraph.nodes, askGraph.edges)
      const shown = askGraph.shown ? new Set(askGraph.shown) : pickStartNodes(askGraph.nodes, askGraph.edges)
      const rest = askGraph.nodes.filter((n) => !shown.has(n.id)).map((n) => n.id)
      if (rest.length) graph.hide(rest)
      setSelected(null)
    } else if (snapshot.data) {
      graph.reset(snapshot.data.nodes, snapshot.data.edges)
      setSelected(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshot.data, askGraph])

  const visible = useMemo(() => {
    const nodes = graph.visible.nodes.filter((n) => !hiddenKinds.has(n.kind))
    return { nodes, edges: graph.visible.edges }
  }, [graph.visible, hiddenKinds])
  const onCanvas = useMemo(() => new Set(visible.nodes.map((n) => n.id)), [visible.nodes])

  const kindCounts = useMemo(() => {
    const c = new Map<NodeKind, number>()
    graph.visible.nodes.forEach((n) => c.set(n.kind, (c.get(n.kind) ?? 0) + 1))
    return c
  }, [graph.visible.nodes])

  const selectedNode = selected?.type === 'node' ? graph.state.nodes.get(selected.id) : undefined
  const selectedEdge = selected?.type === 'edge' ? graph.state.edges.get(selected.id) : undefined

  const expandNode = useCallback(
    async (id: string, aggregate = false) => {
      const node = graph.state.nodes.get(id)
      const agg = aggregate && node?.kind !== 'shipment'
      setBusy(true)
      try {
        const res = await fetchNeighbours(id, dates, agg, agg ? undefined : EXPAND_LIMIT)
        graph.add([res.node, ...res.neighbours], res.edges)
        const newKinds = new Set(res.neighbours.map((n) => n.kind))
        if ([...newKinds].some((k) => hiddenKinds.has(k)))
          toast.info('Some new neighbours are of hidden node types', { description: 'Turn the type back on under Node types to see them.' })
        if (res.truncated) toast.info(`Added the ${res.edges.length} most recent of ${fmt(res.total)} neighbours`, { description: 'Open the inspector to browse the rest.' })
      } catch (e) {
        toast.error('Could not expand', { description: (e as Error).message })
      } finally {
        setBusy(false)
      }
    },
    [dates, graph, hiddenKinds],
  )

  const expandEdge = async (edgeId: string) => {
    const edge = graph.state.edges.get(edgeId)
    if (!edge) return
    setBusy(true)
    try {
      const res = await fetchEdgeShipments(edge.source, edge.target, dates)
      graph.expandEdge(edgeId, res.shipments, res.edges)
      setHiddenKinds((h) => {
        if (!h.has('shipment')) return h
        const n = new Set(h)
        n.delete('shipment')
        return n
      })
      setSelected(null)
      toast.success(`Expanded into ${res.count} shipment${res.count === 1 ? '' : 's'}`)
    } catch (e) {
      toast.error('Could not expand link', { description: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  /** Add a node found by search, plus its links to anything already on the canvas. */
  const addFromSearch = async (n: GNode) => {
    const isNew = !graph.state.nodes.has(n.id)
    graph.add([n], [])
    setSelected({ type: 'node', id: n.id })
    if (hiddenKinds.has(n.kind)) setHiddenKinds((h) => { const x = new Set(h); x.delete(n.kind); return x })
    if (isNew) try {
      const res = await fetchNeighbours(n.id, dates, false)
      const present = new Set(graph.state.nodes.keys())
      const links = res.edges.filter((e) => present.has(e.source === n.id ? e.target : e.source))
      if (links.length) graph.add([], links)
    } catch {
      /* the node is on the canvas either way */
    }
    setTimeout(() => canvas.current?.fit([n.id]), 600)
  }

  const setSuppliers = (ids: string[]) => setParam({ suppliers: ids.join(',') || null, full: null })
  const total = { nodes: visible.nodes.length, edges: visible.edges.length }

  return (
    <div className="grid grid-rows-[auto_480px_auto] lg:h-full lg:min-h-[640px] lg:grid-cols-[272px_minmax(0,1fr)_auto] lg:grid-rows-1">
      {/* Controls */}
      <aside className="space-y-5 border-b p-4 lg:overflow-y-auto lg:border-r lg:border-b-0">
        {askGraph && (
          <div className="space-y-1.5 rounded-md border border-primary/30 bg-primary/5 px-2.5 py-2 text-xs">
            <div className="font-medium">Showing an Ask the Graph result</div>
            {askGraph.question && <p className="line-clamp-3 text-muted-foreground" title={askGraph.question}>“{askGraph.question}”</p>}
            <div className="flex gap-3">
              <button className="underline underline-offset-2" onClick={() => navigate(-1)}>Back to the answer</button>
              <button className="text-muted-foreground underline underline-offset-2 hover:text-foreground" onClick={leaveAsk}>Dyson snapshot</button>
            </div>
          </div>
        )}
        <Section title="Shipments to Dyson from">
          {full ? (
            <div className="rounded-md bg-muted px-2.5 py-2 text-xs text-muted-foreground">
              Showing the full graph.{' '}
              <button className="underline underline-offset-2" onClick={() => setParam({ full: null })}>Back to snapshot</button>
            </div>
          ) : (
            <SupplierPicker selected={snapshotSuppliers} onChange={setSuppliers} />
          )}
        </Section>

        <Section title="Search the graph">
          <GraphSearch onPick={addFromSearch} />
        </Section>

        <Section
          title="Arrival dates"
          action={(dates.date_from || dates.date_to) && (
            <button className="text-[11px] text-muted-foreground hover:text-foreground" onClick={() => setParam({ from: null, to: null })}>Clear</button>
          )}
        >
          <div className="grid grid-cols-2 gap-1">
            {PRESETS.map((p) => {
              const active = (dates.date_from ?? null) === p.from && (dates.date_to ?? null) === p.to
              return (
                <Button key={p.label} size="xs" variant={active ? 'secondary' : 'ghost'} className="justify-start" onClick={() => setParam({ from: p.from, to: p.to })}>
                  {active && <Check className="size-3" />} {p.label}
                </Button>
              )
            })}
          </div>
          <div className="grid grid-cols-[36px_1fr] items-center gap-x-2 gap-y-1.5">
            <Label htmlFor="from" className="text-[11px] text-muted-foreground">From</Label>
            <Input id="from" type="date" min={STUDY.start} max={STUDY.end} value={dates.date_from ?? ''} onChange={(e) => setParam({ from: e.target.value || null })} className="h-8 px-2 text-xs" />
            <Label htmlFor="to" className="text-[11px] text-muted-foreground">To</Label>
            <Input id="to" type="date" min={STUDY.start} max={STUDY.end} value={dates.date_to ?? ''} onChange={(e) => setParam({ to: e.target.value || null })} className="h-8 px-2 text-xs" />
          </div>
          <p className="text-[11px] text-muted-foreground">Filters shipments by arrival date; the graph reloads.</p>
        </Section>

        <Section
          title="Node types"
          action={hiddenKinds.size > 0 && (
            <button className="text-[11px] text-muted-foreground hover:text-foreground" onClick={() => setHiddenKinds(new Set())}>Show all</button>
          )}
        >
          <div className="space-y-1">
            {KIND_ORDER.map((k) => {
              const n = kindCounts.get(k) ?? 0
              return (
                <label key={k} className={`flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-sm hover:bg-accent ${n === 0 ? 'opacity-50' : ''}`}>
                  <Checkbox
                    checked={!hiddenKinds.has(k)}
                    onCheckedChange={(v) => setHiddenKinds((h) => { const x = new Set(h); if (v) x.delete(k); else x.add(k); return x })}
                  />
                  <KindSwatch kind={k} />
                  <span className="flex-1">{KIND_META[k].plural}</span>
                  <span className="tabular text-xs text-muted-foreground">{n}</span>
                </label>
              )
            })}
          </div>
          {graph.state.hidden.size > 0 && (
            <Button variant="ghost" size="xs" onClick={graph.unhideAll} className="w-full">
              <Eye className="size-3" /> Unhide {graph.state.hidden.size} hidden node{graph.state.hidden.size === 1 ? '' : 's'}
            </Button>
          )}
        </Section>

        <Section title="Layout">
          <div className="flex gap-1.5">
            <Select value={layout} onValueChange={(v) => setLayout(v as LayoutName)}>
              <SelectTrigger size="sm" className="flex-1"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="radial">Radial (Dyson centre)</SelectItem>
                <SelectItem value="fcose">Force-directed</SelectItem>
                <SelectItem value="concentric">Concentric</SelectItem>
                <SelectItem value="breadthfirst">Hierarchy</SelectItem>
                <SelectItem value="circle">Circle</SelectItem>
                <SelectItem value="grid">Grid</SelectItem>
              </SelectContent>
            </Select>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="icon-sm" onClick={() => canvas.current?.layout(true)} aria-label="Re-run layout"><RefreshCw className="size-3.5" /></Button>
              </TooltipTrigger>
              <TooltipContent>Re-run layout</TooltipContent>
            </Tooltip>
          </div>
        </Section>

        <Separator />
        <div className="space-y-3">
          <button onClick={() => setShowAdvanced((v) => !v)} className="flex w-full items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground">
            <Settings2 className="size-3.5" /> Advanced
            <ChevronDown className={`ml-auto size-3.5 transition-transform ${showAdvanced ? 'rotate-180' : ''}`} />
          </button>
          {showAdvanced && (
            <div className="space-y-2">
              <label className="flex items-center justify-between gap-2 text-sm">
                <span>Show full graph</span>
                <Switch checked={full} onCheckedChange={(v) => setParam({ full: v ? '1' : null })} />
              </label>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                Every node and stored relationship, shipments included (about 740 nodes and 3,400 relationships). Slower to lay out.
              </p>
            </div>
          )}
        </div>
      </aside>

      {/* Canvas */}
      <div className="relative min-h-[420px] overflow-hidden bg-[color-mix(in_oklab,var(--muted)_35%,var(--background))]">
        <GraphCanvas
          ref={canvas}
          nodes={visible.nodes}
          edges={visible.edges}
          mode={mode}
          selected={selected}
          onSelect={setSelected}
          onExpand={(id) => expandNode(id)}
          layoutName={layout}
          roots={askGraph ? askRoots : !full && snapshot.data?.center ? [snapshot.data.center] : []}
        />
        <div className="pointer-events-none absolute inset-x-3 top-3 flex items-start justify-between gap-2">
          <div className="pointer-events-auto rounded-md border bg-background/90 px-2.5 py-1.5 text-xs text-muted-foreground shadow-sm backdrop-blur">
            {snapshot.isFetching && !askGraph ? (
              <span className="flex items-center gap-1.5"><Loader2 className="size-3 animate-spin" /> Loading graph</span>
            ) : (
              <>{fmt(total.nodes)} nodes · {fmt(total.edges)} relationships</>
            )}
          </div>
          <div className="pointer-events-auto flex gap-1 rounded-md border bg-background/90 p-0.5 shadow-sm backdrop-blur">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-sm" onClick={() => canvas.current?.fit()} aria-label="Fit to view"><Maximize className="size-3.5" /></Button>
              </TooltipTrigger>
              <TooltipContent>Fit to view</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost" size="icon-sm" aria-label="Download PNG"
                  onClick={() => {
                    const url = canvas.current?.png()
                    if (!url) return
                    const a = document.createElement('a')
                    a.href = url
                    a.download = 'dyson-graph.png'
                    a.click()
                  }}
                ><Download className="size-3.5" /></Button>
              </TooltipTrigger>
              <TooltipContent>Download PNG</TooltipContent>
            </Tooltip>
          </div>
        </div>
        {snapshot.isError && !askGraph && (
          <div className="absolute inset-0 grid place-items-center">
            <div className="flex items-center gap-2 rounded-md border bg-background px-3 py-2 text-sm shadow-sm">
              <AlertTriangle className="size-4 text-destructive" /> {(snapshot.error as Error).message}
            </div>
          </div>
        )}
        {!selected && !snapshot.isPending && (
          <div className="pointer-events-none absolute bottom-3 left-3 rounded-md border bg-background/90 px-2.5 py-1.5 text-[11px] text-muted-foreground shadow-sm backdrop-blur">
            Double-click a node to expand it · click to see its details · scroll to zoom
          </div>
        )}
      </div>

      {/* Inspector */}
      {(selectedNode || selectedEdge) && (
        <aside className="h-[560px] min-h-0 overflow-hidden border-t bg-background lg:h-auto lg:w-[340px] lg:border-t-0 lg:border-l">
          {selectedNode && (
            <NodeInspector
              key={selectedNode.id}
              node={selectedNode}
              dates={dates}
              onCanvas={onCanvas}
              isSnapshotSupplier={snapshotSuppliers.includes(selectedNode.id)}
              busy={busy}
              onClose={() => setSelected(null)}
              onExpand={(agg) => expandNode(selectedNode.id, agg)}
              onHide={() => { graph.hide([selectedNode.id]); setSelected(null) }}
              onFocus={() => canvas.current?.fit([selectedNode.id])}
              onAddSupplier={() => setSuppliers([selectedNode.id])}
              onAddNeighbour={(n, e) => graph.add([n], [e])}
            />
          )}
          {selectedEdge && (
            <EdgeInspector
              key={selectedEdge.id}
              edge={selectedEdge}
              source={graph.state.nodes.get(selectedEdge.source)}
              target={graph.state.nodes.get(selectedEdge.target)}
              expanded={graph.state.expanded.has(selectedEdge.id)}
              busy={busy}
              onClose={() => setSelected(null)}
              onExpand={() => expandEdge(selectedEdge.id)}
              onCollapse={() => graph.collapseEdge(selectedEdge.id)}
              onSelectNode={(id) => setSelected({ type: 'node', id })}
            />
          )}
        </aside>
      )}
    </div>
  )
}
