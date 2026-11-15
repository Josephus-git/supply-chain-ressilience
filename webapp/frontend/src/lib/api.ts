import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type {
  DateFilter, EdgeShipments, Health, HomeStats, Neighbours, Network, SearchResults, Snapshot,
  SupplierPicker, TopSuppliers,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type Params = Record<string, string | number | boolean | null | undefined>

function qs(params: Params = {}): string {
  const search = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== '') search.set(k, String(v))
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

export async function getJson<T>(path: string, params?: Params, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`/api${path}${qs(params)}`, { signal })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

// Graph data only changes when the KG is rebuilt, so cache generously.
const STATIC = { staleTime: 5 * 60_000 }

export const useHealth = () =>
  useQuery({ queryKey: ['health'], queryFn: ({ signal }) => getJson<Health>('/health', {}, signal), refetchInterval: 60_000, retry: false })

export const useHomeStats = () =>
  useQuery({ queryKey: ['home', 'stats'], queryFn: ({ signal }) => getJson<HomeStats>('/home/stats', {}, signal), ...STATIC })

export const useNetwork = () =>
  useQuery({ queryKey: ['home', 'network'], queryFn: ({ signal }) => getJson<Network>('/home/network', {}, signal), ...STATIC })

export const useTopSuppliers = (limit = 10) =>
  useQuery({
    queryKey: ['home', 'top-suppliers', limit],
    queryFn: ({ signal }) => getJson<TopSuppliers>('/home/top-suppliers', { limit }, signal),
    ...STATIC,
  })

export const useSupplierPicker = () =>
  useQuery({ queryKey: ['graph', 'suppliers'], queryFn: ({ signal }) => getJson<SupplierPicker>('/graph/suppliers', {}, signal), ...STATIC })

export const useSnapshot = (suppliers: string[], dates: DateFilter, full: boolean) =>
  useQuery({
    queryKey: ['graph', full ? 'full' : 'start', suppliers, dates],
    queryFn: ({ signal }) =>
      full
        ? getJson<Snapshot>('/graph/snapshot', { full, ...dates }, signal)
        : getJson<Snapshot>('/graph/start', { suppliers: suppliers.join(',') || null, ...dates }, signal),
    ...STATIC,
  })

export const useNeighbours = (nodeId: string | null, dates: DateFilter, aggregate = true) =>
  useQuery({
    queryKey: ['graph', 'neighbours', nodeId, dates, aggregate],
    queryFn: ({ signal }) =>
      getJson<Neighbours>(`/graph/nodes/${encodeURIComponent(nodeId!)}/neighbours`, { aggregate, ...dates }, signal),
    enabled: !!nodeId,
    ...STATIC,
  })

export const fetchNeighbours = (nodeId: string, dates: DateFilter, aggregate: boolean, limit?: number) =>
  getJson<Neighbours>(`/graph/nodes/${encodeURIComponent(nodeId)}/neighbours`, { aggregate, limit: limit ?? null, ...dates })

export const fetchEdgeShipments = (source: string, target: string, dates: DateFilter) =>
  getJson<EdgeShipments>('/graph/edges/shipments', { source, target, ...dates })

export const useSearch = (q: string) =>
  useQuery({
    queryKey: ['graph', 'search', q],
    queryFn: ({ signal }) => getJson<SearchResults>('/graph/search', { q, limit: 30 }, signal),
    enabled: q.trim().length >= 2,
    placeholderData: keepPreviousData,
    ...STATIC,
  })
