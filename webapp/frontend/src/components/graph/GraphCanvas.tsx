/**
 * Cytoscape.js canvas. The parent owns which nodes and edges are visible; the
 * canvas diffs them into the live instance so existing nodes keep their
 * positions, new ones appear next to the node they hang off, and an
 * incremental layout settles them.
 */
import cytoscape, { type Core, type ElementDefinition, type LayoutOptions, type StylesheetJson } from 'cytoscape'
import fcose from 'cytoscape-fcose'
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { KIND_META, kindColor, kindInk } from '@/lib/kinds'
import { CHROME, type Mode } from '@/lib/palette'
import type { GEdge, GNode } from '@/lib/types'

cytoscape.use(fcose)

export type Selection = { type: 'node' | 'edge'; id: string } | null
export type LayoutName = 'radial' | 'fcose' | 'concentric' | 'breadthfirst' | 'circle' | 'grid'

export interface GraphCanvasHandle {
  fit: (ids?: string[]) => void
  layout: (randomize?: boolean) => void
  png: () => string | undefined
}

interface Props {
  nodes: GNode[]
  edges: GEdge[]
  mode: Mode
  selected: Selection
  onSelect: (s: Selection) => void
  onExpand: (nodeId: string) => void
  layoutName: LayoutName
  /** Node IDs to keep at the centre (e.g. Dyson). */
  roots: string[]
}

const truncate = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

/** Caption drawn inside the circle, Bloom-style. The full name shows on selection and in the inspector. */
function caption(n: GNode): string {
  if (n.kind === 'product') {
    const hs = n.properties.hs_code
    return typeof hs === 'number' ? `HS ${String(hs).padStart(6, '0')}` : truncate(n.name, 18)
  }
  if (n.kind === 'shipment') return truncate(n.name, 18)
  return truncate(n.name, n.kind === 'buyer' ? 22 : 20)
}

function layoutOptions(name: LayoutName, randomize: boolean, roots: string[], count: number): LayoutOptions {
  const animate = count < 400
  switch (name) {
    case 'radial': // incremental steps of the radial view settle with fcose, keeping placed nodes
    case 'fcose': {
      const big = count > 300
      return {
        name: 'fcose',
        // @ts-expect-error fcose-specific options
        quality: 'default',
        randomize,
        // Keep the centre (Dyson) pinned in the middle on a fresh layout.
        fixedNodeConstraint: randomize && roots.length ? roots.map((nodeId, i) => ({ nodeId, position: { x: i * 220, y: 0 } })) : undefined,
        animate,
        animationDuration: 450,
        nodeRepulsion: big ? 6000 : 16000,
        idealEdgeLength: big ? 80 : 170,
        edgeElasticity: 0.3,
        nodeSeparation: big ? 40 : 110,
        numIter: big ? 3000 : 2500,
        gravity: big ? 0.4 : 0.25,
        packComponents: true,
        fit: true,
        padding: 40,
      }
    }
    case 'concentric':
      return {
        name: 'concentric', animate, padding: 40, minNodeSpacing: 18,
        concentric: (n: cytoscape.NodeSingular) => (roots.includes(n.id()) ? 10 : n.data('kind') === 'shipment' ? 6 : n.data('kind') === 'parent' ? 1 : 3),
        levelWidth: () => 1,
      } as LayoutOptions
    case 'breadthfirst':
      return { name: 'breadthfirst', animate, padding: 40, directed: false, spacingFactor: 1.1, roots: roots.length ? roots : undefined } as LayoutOptions
    default:
      return { name, animate, padding: 40 } as LayoutOptions
  }
}

function stylesheet(mode: Mode): StylesheetJson {
  const ch = CHROME[mode]
  const selectRing = mode === 'dark' ? '#f0efec' : '#0b0b0b'
  const edgeLine = mode === 'dark' ? '#8a8984' : '#9b9a94'
  return [
    {
      selector: 'node',
      style: {
        'background-color': 'data(color)',
        shape: 'ellipse',
        width: 'data(size)',
        height: 'data(size)',
        'border-width': 0,
        label: 'data(caption)',
        color: 'data(ink)',
        'font-size': 8,
        'font-family': 'Geist Variable, system-ui, sans-serif',
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'wrap',
        'text-max-width': '46px',
        'text-overflow-wrap': 'anywhere',
        'line-height': 1.15,
        'min-zoomed-font-size': 5,
        'transition-property': 'opacity',
        'transition-duration': 150,
      },
    },
    { selector: 'node.root', style: { 'font-size': 10, 'font-weight': 600, 'text-max-width': '62px' } },
    {
      selector: 'edge',
      style: {
        width: 'data(w)',
        'line-color': edgeLine,
        'target-arrow-color': edgeLine,
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.8,
        'curve-style': 'bezier',
        label: 'data(label)',
        'font-size': 7,
        'font-family': 'Geist Variable, system-ui, sans-serif',
        color: ch.ink2,
        'text-rotation': 'autorotate',
        'text-background-color': ch.surface,
        'text-background-opacity': 0.85,
        'text-background-padding': '1px',
        'min-zoomed-font-size': 6,
        'transition-property': 'opacity',
        'transition-duration': 150,
      },
    },
    { selector: 'edge.agg', style: { 'line-style': 'dashed', 'line-dash-pattern': [5, 3] } },
    { selector: '.faded', style: { opacity: 0.15 } },
    { selector: 'edge.hl', style: { 'line-color': ch.ink2, 'target-arrow-color': ch.ink2, color: ch.ink, opacity: 1, 'z-index': 9 } },
    { selector: 'node:selected', style: { 'border-width': 3, 'border-color': selectRing, 'overlay-opacity': 0, 'z-index': 10 } },
    { selector: 'edge:selected', style: { 'line-color': selectRing, 'target-arrow-color': selectRing, width: 2.5, 'overlay-opacity': 0, opacity: 1, 'z-index': 10 } },
    { selector: 'node:active, edge:active', style: { 'overlay-opacity': 0.08 } },
  ]
}

export const GraphCanvas = forwardRef<GraphCanvasHandle, Props>(function GraphCanvas(
  { nodes, edges, mode, selected, onSelect, onExpand, layoutName, roots },
  ref,
) {
  const container = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  const positions = useRef(new Map<string, { x: number; y: number }>())
  const handlers = useRef({ onSelect, onExpand })
  handlers.current = { onSelect, onExpand }
  const layoutRef = useRef({ layoutName, roots })
  layoutRef.current = { layoutName, roots }

  const runLayout = (randomize: boolean) => {
    const cy = cyRef.current
    if (!cy || cy.nodes().length === 0) return
    const { layoutName: name, roots: r } = layoutRef.current
    const opts = layoutOptions(name, randomize, r, cy.nodes().length)
    const centre = r.length === 1 ? cy.getElementById(r[0]) : null
    if (name === 'radial' && randomize && centre?.nonempty()) {
      const pos = radialPositions(cy, centre)
      cy.layout({ name: 'preset', positions: (n: cytoscape.NodeSingular) => pos.get(n.id()) ?? n.position(), fit: false, animate: false } as LayoutOptions).run()
      centreOn(cy, centre)
      return
    }
    if (randomize && centre?.nonempty() && (name === 'fcose' || name === 'concentric')) {
      // Fit around the centre node rather than the bounding box, so Dyson sits mid-canvas.
      const l = cy.layout({ ...opts, fit: false, animate: false } as LayoutOptions)
      l.one('layoutstop', () => centreOn(cy, centre))
      l.run()
      return
    }
    cy.layout(opts).run()
  }

  useImperativeHandle(ref, () => ({
    fit: (ids) => {
      const cy = cyRef.current
      if (!cy) return
      let target = cy.elements()
      if (ids?.length) {
        let picked = cy.collection()
        ids.forEach((id) => { picked = picked.union(cy.getElementById(id)) })
        target = picked.closedNeighborhood()
      }
      cy.animate({ fit: { eles: target, padding: 60 }, duration: 300 })
    },
    layout: (randomize = true) => runLayout(randomize),
    png: () => cyRef.current?.png({ full: true, scale: 2, bg: CHROME[mode].surface }),
  }))

  // Create once.
  useEffect(() => {
    const cy = cytoscape({
      container: container.current,
      minZoom: 0.05,
      maxZoom: 4,
      boxSelectionEnabled: false,
      selectionType: 'single',
    })
    cyRef.current = cy
    // Dev only: lets browser tests and the console reach the instance.
    if (import.meta.env.DEV) (window as unknown as { __cy?: Core }).__cy = cy
    // Wait briefly before selecting a node: opening the inspector narrows the canvas,
    // which would otherwise pull the node from under the second click of a double-click.
    let tapTimer: ReturnType<typeof setTimeout> | undefined
    cy.on('tap', 'node', (e) => {
      const id = e.target.id()
      clearTimeout(tapTimer)
      tapTimer = setTimeout(() => handlers.current.onSelect({ type: 'node', id }), 320)
    })
    cy.on('tap', 'edge', (e) => handlers.current.onSelect({ type: 'edge', id: e.target.id() }))
    cy.on('tap', (e) => {
      if (e.target === cy) handlers.current.onSelect(null)
    })
    cy.on('dbltap', 'node', (e) => {
      clearTimeout(tapTimer)
      handlers.current.onExpand(e.target.id())
    })
    cy.on('mouseover', 'node', (e) => {
      const n = e.target
      cy.elements().addClass('faded')
      n.closedNeighborhood().removeClass('faded').addClass('hl')
    })
    cy.on('mouseout', 'node', () => {
      cy.elements().removeClass('faded hl')
      applySelectionFocus(cy)
    })
    cy.on('position', 'node', (e) => positions.current.set(e.target.id(), { ...e.target.position() }))
    // The canvas narrows when the inspector opens: tell Cytoscape, or taps land in the wrong place.
    let lastW = container.current?.clientWidth ?? 0
    let lastH = container.current?.clientHeight ?? 0
    const ro = new ResizeObserver(() => {
      const w = container.current?.clientWidth ?? 0
      const h = container.current?.clientHeight ?? 0
      cy.resize()
      // Keep what was in the middle in the middle.
      if (lastW && lastH) cy.panBy({ x: (w - lastW) / 2, y: (h - lastH) / 2 })
      lastW = w
      lastH = h
    })
    if (container.current) ro.observe(container.current)
    return () => {
      ro.disconnect()
      clearTimeout(tapTimer)
      cy.destroy()
      cyRef.current = null
    }
  }, [])

  useEffect(() => {
    cyRef.current?.style(stylesheet(mode))
  }, [mode])

  // Diff elements into the instance.
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    const nodeIds = new Set(nodes.map((n) => n.id))
    const edgeIds = new Set(edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target)).map((e) => e.id))
    const hadNodes = cy.nodes().length

    cy.batch(() => {
      cy.edges().forEach((el) => {
        if (!edgeIds.has(el.id())) el.remove()
      })
      cy.nodes().forEach((el) => {
        if (!nodeIds.has(el.id())) {
          positions.current.set(el.id(), { ...el.position() })
          el.remove()
        }
      })
    })

    const maxShip = Math.max(1, ...edges.map((e) => e.shipments ?? 1))
    const added: ElementDefinition[] = []
    let placedFromCache = 0
    for (const n of nodes) {
      const existing = cy.getElementById(n.id)
      const data = {
        id: n.id,
        kind: n.kind,
        name: n.name,
        caption: caption(n),
        color: kindColor(n.kind),
        ink: kindInk(n.kind),
        size: KIND_META[n.kind]?.size ?? 54,
      }
      if (existing.nonempty()) {
        existing.data(data)
        continue
      }
      const cached = positions.current.get(n.id)
      if (cached) placedFromCache++
      added.push({ group: 'nodes', data, position: cached ? { ...cached } : undefined })
    }
    for (const e of edges) {
      if (!edgeIds.has(e.id) || cy.getElementById(e.id).nonempty()) continue
      added.push({
        group: 'edges',
        data: {
          id: e.id,
          source: e.source,
          target: e.target,
          type: e.type,
          label: e.aggregated && e.shipments ? `${e.type} · ${e.shipments}` : e.type,
          w: e.aggregated && e.shipments ? 1 + 3 * Math.sqrt(e.shipments / maxShip) : 1,
        },
        classes: e.aggregated ? 'agg' : 'raw',
      })
    }

    if (added.length) {
      const newNodes = added.filter((a) => a.group === 'nodes')
      const els = cy.add(added)
      // Put new, unplaced nodes beside an existing neighbour so the incremental layout starts close.
      els.nodes().forEach((n) => {
        if (positions.current.has(n.id())) return
        const anchor = n.neighborhood('node').filter((m: cytoscape.NodeSingular) => !els.contains(m))[0]
        if (anchor) {
          const p = anchor.position()
          n.position({ x: p.x + (Math.random() - 0.5) * 120, y: p.y + (Math.random() - 0.5) * 120 })
        }
      })
      const allCached = newNodes.length > 0 && placedFromCache === newNodes.length
      // Mostly-new graph (fresh snapshot, full graph): lay out from scratch.
      const fresh = hadNodes === 0 || newNodes.length > cy.nodes().length / 2
      if (!allCached && newNodes.length) runLayout(fresh)
    }
    cy.nodes().forEach((n) => {
      n.toggleClass('root', layoutRef.current.roots.includes(n.id()))
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges])

  // Root styling when roots change.
  useEffect(() => {
    cyRef.current?.nodes().forEach((n) => {
      n.toggleClass('root', roots.includes(n.id()))
    })
  }, [roots])

  // Re-run the layout when the user picks another one.
  useEffect(() => {
    runLayout(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutName])

  // Reflect the selection.
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().unselect()
    if (selected) {
      const el = cy.getElementById(selected.id)
      if (el.nonempty()) el.select()
    }
    applySelectionFocus(cy)
  }, [selected, nodes, edges])

  return <div ref={container} className="graph-canvas" />
})

/**
 * Radial tree around the centre node: a BFS tree where each subtree gets an arc
 * proportional to its leaf count, one ring per hop. Nodes not reached go on an
 * outer ring.
 */
function radialPositions(cy: Core, centre: cytoscape.NodeSingular) {
  const RING = 170
  const children = new Map<string, string[]>()
  const depth = new Map<string, number>([[centre.id(), 0]])
  const queue = [centre.id()]
  while (queue.length) {
    const id = queue.shift()!
    const kids: string[] = []
    cy.getElementById(id).neighborhood('node').forEach((m: cytoscape.NodeSingular) => {
      if (depth.has(m.id())) return
      depth.set(m.id(), depth.get(id)! + 1)
      kids.push(m.id())
      queue.push(m.id())
    })
    // Bigger subtrees are placed after leaves so the ring reads tidily.
    children.set(id, kids)
  }
  const leaves = new Map<string, number>()
  const count = (id: string): number => {
    const k = children.get(id) ?? []
    const n = k.length ? k.reduce((a, c) => a + count(c), 0) : 1
    leaves.set(id, n)
    return n
  }
  count(centre.id())
  const c = centre.position()
  const pos = new Map<string, { x: number; y: number }>([[centre.id(), { ...c }]])
  const place = (id: string, from: number, to: number) => {
    const kids = (children.get(id) ?? []).sort((a, b) => leaves.get(a)! - leaves.get(b)!)
    const total = kids.reduce((a, k) => a + leaves.get(k)!, 0)
    let at = from
    for (const k of kids) {
      const span = ((to - from) * leaves.get(k)!) / total
      const angle = at + span / 2
      const r = RING * depth.get(k)!
      pos.set(k, { x: c.x + r * Math.cos(angle), y: c.y + r * Math.sin(angle) })
      place(k, at, at + span)
      at += span
    }
  }
  place(centre.id(), -Math.PI / 2, (3 * Math.PI) / 2)
  const maxDepth = Math.max(0, ...depth.values())
  const stray = cy.nodes().filter((n: cytoscape.NodeSingular) => !pos.has(n.id()))
  stray.forEach((n: cytoscape.NodeSingular, i: number) => {
    const a = (2 * Math.PI * i) / Math.max(1, stray.length)
    const r = RING * (maxDepth + 1)
    pos.set(n.id(), { x: c.x + r * Math.cos(a), y: c.y + r * Math.sin(a) })
  })
  return pos
}

/** Zoom so every node fits while the given node stays in the middle of the canvas. */
function centreOn(cy: Core, centre: cytoscape.NodeSingular) {
  const c = centre.position()
  let dx = 0
  let dy = 0
  cy.nodes().forEach((n) => {
    const p = n.position()
    const r = n.outerWidth() / 2
    dx = Math.max(dx, Math.abs(p.x - c.x) + r)
    dy = Math.max(dy, Math.abs(p.y - c.y) + r)
  })
  const pad = 40
  const w = cy.width()
  const h = cy.height()
  const zoom = Math.min(1.6, (w / 2 - pad) / Math.max(dx, 1), (h / 2 - pad) / Math.max(dy, 1))
  cy.viewport({ zoom, pan: { x: w / 2 - c.x * zoom, y: h / 2 - c.y * zoom } })
}

/** Fade everything except the selection and its immediate neighbourhood. */
function applySelectionFocus(cy: Core) {
  cy.elements().removeClass('faded hl')
  const sel = cy.$(':selected')
  if (sel.empty()) return
  const keep = sel.nodes().nonempty() ? sel.nodes().closedNeighborhood() : sel.union(sel.edges().connectedNodes())
  cy.elements().not(keep).addClass('faded')
  keep.addClass('hl')
}
