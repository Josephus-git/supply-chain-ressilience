/**
 * Start small: pick about 15 nodes of a result to show first, and reveal the
 * rest a few at a time as the user expands nodes (Bloom style, no noise).
 *
 * Non-shipment nodes (suppliers, parents, buyers, ports, products…) carry the
 * story, so they go first, busiest first. Shipments fill the remaining slots,
 * shared round-robin across the nodes already shown so every hub gets a few.
 */
import type { GEdge, GNode } from '@/lib/types'

export const START_NODES = 15
/** Hidden neighbours revealed per double-click. */
export const REVEAL_STEP = 10

function adjacency(edges: GEdge[]) {
  const adj = new Map<string, string[]>()
  for (const e of edges) {
    if (e.source === e.target) continue
    ;(adj.get(e.source) ?? adj.set(e.source, []).get(e.source)!).push(e.target)
    ;(adj.get(e.target) ?? adj.set(e.target, []).get(e.target)!).push(e.source)
  }
  return adj
}

export function pickStartNodes(nodes: GNode[], edges: GEdge[], max = START_NODES): Set<string> {
  if (nodes.length <= max) return new Set(nodes.map((n) => n.id))
  const adj = adjacency(edges)
  const degree = (id: string) => adj.get(id)?.length ?? 0
  const byDegree = (a: GNode, b: GNode) => degree(b.id) - degree(a.id)

  const hubs = nodes.filter((n) => n.kind !== 'shipment').sort(byDegree)
  const shown = new Set(hubs.slice(0, max).map((n) => n.id))
  if (shown.size >= max) return shown

  const isShipment = new Map(nodes.map((n) => [n.id, n.kind === 'shipment']))
  // Each shown hub's shipments, best-connected first.
  const queues = [...shown]
    .map((id) => (adj.get(id) ?? []).filter((x) => isShipment.get(x)).sort((a, b) => degree(b) - degree(a)))
    .filter((q) => q.length > 0)
  while (shown.size < max && queues.some((q) => q.length > 0)) {
    for (const q of queues) {
      while (q.length > 0 && shown.has(q[0])) q.shift()
      const next = q.shift()
      if (next) shown.add(next)
      if (shown.size >= max) break
    }
  }
  // No hubs to hang shipments on: just take the busiest shipments.
  for (const n of nodes.filter((x) => x.kind === 'shipment').sort(byDegree)) {
    if (shown.size >= max) break
    shown.add(n.id)
  }
  return shown
}

/** Up to `step` neighbours of `id` (within the result) that are not shown yet. */
export function hiddenNeighbours(id: string, edges: GEdge[], shown: Set<string>, step = REVEAL_STEP): { ids: string[]; remaining: number } {
  const all = [...new Set(adjacency(edges).get(id) ?? [])].filter((x) => !shown.has(x))
  return { ids: all.slice(0, step), remaining: all.length - Math.min(step, all.length) }
}
