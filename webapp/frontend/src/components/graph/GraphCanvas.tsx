/**
 * Cytoscape.js canvas. The parent owns which nodes and edges are visible; the
 * canvas diffs them into the live instance so existing nodes keep their
 * positions, new ones appear next to the node they hang off, and an
 * incremental layout settles them.
 */
import cytoscape, { type Core, type ElementDefinition, type LayoutOptions, type StylesheetJson } from 'cytoscape'
import fcose from 'cytoscape-fcose'
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { KIND_META, kindColor, REL_LABEL } from '@/lib/kinds'
import { CHROME, type Mode } from '@/lib/palette'
import type { GEdge, GNode } from '@/lib/types'

cytoscape.use(fcose)

export type Selection = { type: 'node' | 'edge'; id: string } | null
export type LayoutName = 'fcose' | 'concentric' | 'breadthfirst' | 'circle' | 'grid'

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
  /** Node IDs to emphasise (e.g. snapshot suppliers). */
  roots: string[]
}

const truncate = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

/** Always-on canvas label: short enough not to collide. The full name shows on hover and selection. */
function shortLabel(n: GNode): string {
  if (n.kind === 'vessel' || n.kind === 'shipment') return ''
  if (n.kind === 'product') {
    const hs = n.properties.hs_code
    return typeof hs === 'number' ? `HS ${String(hs).padStart(6, '0')}` : truncate(n.name, 14)
  }
  return truncate(n.name, 26)
}

function layoutOptions(name: LayoutName, randomize: boolean, roots: string[], count: number): LayoutOptions {
  const animate = count < 400
  switch (name) {
    case 'fcose': {
      const big = count > 300
      return {
        name: 'fcose',
        // @ts-expect-error fcose-specific options
        quality: 'default',
        randomize,
        animate,
        animationDuration: 450,
        nodeRepulsion: big ? 6000 : 12000,
        idealEdgeLength: big ? 70 : 130,
        edgeElasticity: 0.3,
        nodeSeparation: big ? 40 : 90,
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
        concentric: (n: cytoscape.NodeSingular) => (roots.includes(n.id()) ? 10 : n.data('kind') === 'shipment' ? 1 : n.data('kind') === 'parent' || n.data('kind') === 'buyer' ? 6 : 4),
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
  return [
    {
      selector: 'node',
      style: {
        'background-color': 'data(color)',
        shape: 'data(shape)' as never,
        width: 'data(size)',
        height: 'data(size)',
        'border-width': 2,
        'border-color': ch.surface,
        label: 'data(short)',
        color: ch.ink2,
        'font-size': 10,
        'font-family': 'Geist Variable, system-ui, sans-serif',
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'text-wrap': 'ellipsis',
        'text-max-width': '130px',
        'text-background-color': ch.surface,
        'text-background-opacity': 0.75,
        'text-background-padding': '1px',
        'min-zoomed-font-size': 7,
        'transition-property': 'opacity',
        'transition-duration': 150,
      },
    },
    { selector: 'node.root', style: { 'border-width': 3, 'border-color': ch.ink2, 'font-weight': 600, color: ch.ink, 'font-size': 12 } },

    {
      selector: 'edge',
      style: {
        width: 'data(w)',
        'line-color': ch.axis,
        'target-arrow-color': ch.axis,
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.7,
        'curve-style': 'bezier',
        opacity: 0.9,
        'transition-property': 'opacity',
        'transition-duration': 150,
      },
    },
    {
      selector: 'edge[label]',
      style: {
        label: 'data(label)',
        'font-size': 9,
        color: ch.ink2,
        'text-background-color': ch.surface,
        'text-background-opacity': 1,
        'text-background-padding': '2px',
        'text-background-shape': 'roundrectangle',
        'text-border-width': 1,
        'text-border-color': ch.grid,
        'text-border-opacity': 1,
        'min-zoomed-font-size': 8,
      },
    },
    { selector: 'edge.raw', style: { 'line-style': 'dashed', 'line-dash-pattern': [4, 3] } },
    { selector: '.faded', style: { opacity: 0.12 } },
    { selector: 'node.hl', style: { label: 'data(mid)', color: ch.ink, 'z-index': 8 } },
    { selector: 'edge.hl', style: { 'line-color': ch.ink2, 'target-arrow-color': ch.ink2, opacity: 1, 'z-index': 9 } },
    { selector: 'node:selected', style: { 'border-width': 3, 'border-color': selectRing, 'overlay-opacity': 0, label: 'data(name)', 'text-max-width': '220px', 'text-wrap': 'wrap', 'z-index': 10 } },
    { selector: 'edge:selected', style: { 'line-color': selectRing, 'target-arrow-color': selectRing, width: 'mapData(w, 1, 8, 3, 9)', 'overlay-opacity': 0, opacity: 1, 'z-index': 10 } },
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
    cy.layout(layoutOptions(name, randomize, r, cy.nodes().length)).run()
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
    cy.on('tap', 'node', (e) => handlers.current.onSelect({ type: 'node', id: e.target.id() }))
    cy.on('tap', 'edge', (e) => handlers.current.onSelect({ type: 'edge', id: e.target.id() }))
    cy.on('tap', (e) => {
      if (e.target === cy) handlers.current.onSelect(null)
    })
    cy.on('dbltap', 'node', (e) => handlers.current.onExpand(e.target.id()))
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
    return () => {
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
        short: shortLabel(n),
        mid: truncate(n.name, 40),
        color: kindColor(n.kind, mode),
        shape: KIND_META[n.kind]?.shape ?? 'ellipse',
        size: KIND_META[n.kind]?.size ?? 24,
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
          label: e.aggregated && e.shipments ? String(e.shipments) : undefined,
          title: REL_LABEL[e.type] ?? e.type,
          w: e.aggregated && e.shipments ? 1 + 6 * Math.sqrt(e.shipments / maxShip) : 1.2,
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

/** Fade everything except the selection and its immediate neighbourhood. */
function applySelectionFocus(cy: Core) {
  cy.elements().removeClass('faded hl')
  const sel = cy.$(':selected')
  if (sel.empty()) return
  const keep = sel.nodes().nonempty() ? sel.nodes().closedNeighborhood() : sel.union(sel.edges().connectedNodes())
  cy.elements().not(keep).addClass('faded')
  keep.addClass('hl')
}
