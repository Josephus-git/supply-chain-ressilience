/**
 * The Explorer's working graph: the snapshot plus whatever the user has
 * expanded, minus what they hid. Aggregated links are deduplicated by node
 * pair (a supplier-product link reached from the product side would otherwise
 * arrive again as SHIPPED), and expanding a link swaps it for its shipments.
 */
import { useCallback, useMemo, useState } from 'react'
import type { GEdge, GNode } from '@/lib/types'

interface Expansion {
  nodes: string[]
  edges: string[]
}

interface State {
  nodes: Map<string, GNode>
  edges: Map<string, GEdge>
  hidden: Set<string>
  /** aggregated edge id -> what its expansion added */
  expanded: Map<string, Expansion>
}

const pairKey = (e: GEdge) => [e.source, e.target].sort().join('||')

const empty = (): State => ({ nodes: new Map(), edges: new Map(), hidden: new Set(), expanded: new Map() })

export function useGraphState() {
  const [state, setState] = useState<State>(empty)

  const reset = useCallback((nodes: GNode[], edges: GEdge[]) => {
    setState({
      nodes: new Map(nodes.map((n) => [n.id, n])),
      edges: new Map(edges.map((e) => [e.id, e])),
      hidden: new Set(),
      expanded: new Map(),
    })
  }, [])

  /** Merge nodes and edges in (and unhide them). */
  const add = useCallback((nodes: GNode[], edges: GEdge[]) => {
    setState((s) => {
      const n = new Map(s.nodes)
      const e = new Map(s.edges)
      const hidden = new Set(s.hidden)
      for (const node of nodes) {
        n.set(node.id, { ...n.get(node.id), ...node })
      }
      const aggPairs = new Set([...e.values()].filter((x) => x.aggregated).map(pairKey))
      const expandedPairs = new Set(
        [...s.expanded.keys()].map((id) => s.edges.get(id)).filter((x): x is GEdge => !!x).map(pairKey),
      )
      for (const edge of edges) {
        if (e.has(edge.id)) continue
        if (edge.aggregated) {
          const k = pairKey(edge)
          if (aggPairs.has(k) || expandedPairs.has(k)) continue
          aggPairs.add(k)
        }
        e.set(edge.id, edge)
      }
      for (const node of nodes) hidden.delete(node.id)
      return { ...s, nodes: n, edges: e, hidden }
    })
  }, [])

  const hide = useCallback((ids: string[]) => {
    setState((s) => ({ ...s, hidden: new Set([...s.hidden, ...ids]) }))
  }, [])

  const unhideAll = useCallback(() => setState((s) => ({ ...s, hidden: new Set() })), [])

  /** Replace an aggregated edge with the shipments behind it. */
  const expandEdge = useCallback((edgeId: string, shipments: GNode[], edges: GEdge[]) => {
    setState((s) => {
      const n = new Map(s.nodes)
      const e = new Map(s.edges)
      const addedNodes = shipments.filter((sh) => !n.has(sh.id)).map((sh) => sh.id)
      const addedEdges = edges.filter((x) => !e.has(x.id)).map((x) => x.id)
      shipments.forEach((sh) => n.set(sh.id, sh))
      edges.forEach((x) => e.set(x.id, x))
      const expanded = new Map(s.expanded).set(edgeId, { nodes: addedNodes, edges: addedEdges })
      const hidden = new Set(s.hidden)
      shipments.forEach((sh) => hidden.delete(sh.id))
      return { ...s, nodes: n, edges: e, expanded, hidden }
    })
  }, [])

  const collapseEdge = useCallback((edgeId: string) => {
    setState((s) => {
      const exp = s.expanded.get(edgeId)
      if (!exp) return s
      const n = new Map(s.nodes)
      const e = new Map(s.edges)
      exp.edges.forEach((id) => e.delete(id))
      // Only drop shipment nodes that nothing else still connects to.
      const stillUsed = new Set([...e.values()].flatMap((x) => [x.source, x.target]))
      exp.nodes.forEach((id) => {
        if (!stillUsed.has(id)) n.delete(id)
      })
      const expanded = new Map(s.expanded)
      expanded.delete(edgeId)
      return { ...s, nodes: n, edges: e, expanded }
    })
  }, [])

  const visible = useMemo(() => {
    const nodes = [...state.nodes.values()].filter((n) => !state.hidden.has(n.id))
    const ids = new Set(nodes.map((n) => n.id))
    const edges = [...state.edges.values()].filter(
      (e) => !state.expanded.has(e.id) && ids.has(e.source) && ids.has(e.target),
    )
    return { nodes, edges }
  }, [state])

  return { state, visible, reset, add, hide, unhideAll, expandEdge, collapseEdge }
}
