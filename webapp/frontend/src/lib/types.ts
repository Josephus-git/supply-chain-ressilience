import type { NodeKind } from './kinds'

export interface Health {
  status: string
  neo4j: string
  evidence_records: number
  evidence_snapshot_id: string
  engine_version: string
  warnings: string[]
}

export interface HomeStats {
  suppliers: number
  supplier_companies: number
  parent_companies: number
  shipments: number
  products: number
  ports: number
  exit_ports: number
  entry_ports: number
  carriers: number
  vessels: number
  buyers: number
  evidence_records: number
  evidence_snapshot_id: string
  first_arrival: string
  last_arrival: string
  study_window: { start: string; end: string }
}

export interface Place {
  lat: number
  lon: number
  label: string | null
  country_code?: string | null
  level: 'city' | 'port' | 'country' | string
  basis?: string | null
  source: string
}

export interface Breakdown {
  id: string
  name: string
  shipments: number
}

export interface NetworkSupplier {
  id: string
  supplier_id: string
  name: string
  company: string
  parent: string | null
  parent_id: string | null
  reported_country_code: string | null
  address: string | null
  location: Place | null
  shipments: number
  first_arrival: string | null
  last_arrival: string | null
  products: Breakdown[]
  exit_ports: Breakdown[]
  entry_ports: Breakdown[]
  carriers: Breakdown[]
}

export interface NetworkBuyer {
  id: string
  buyer_id: string
  name: string
  reported_country_code: string | null
  address: string | null
  location: Place | null
  shipments: number
}

export interface NetworkPort {
  id: string
  kind: 'exit_port' | 'entry_port'
  name: string
  code: number | null
  location: Place | null
  shipments: number
}

export interface Network {
  suppliers: NetworkSupplier[]
  buyers: NetworkBuyer[]
  ports: NetworkPort[]
  links: { supplier: string; buyer: string; shipments: number }[]
  routes: { supplier: string; exit_port: string; entry_port: string; buyer: string; shipments: number }[]
  missing_locations: string[]
  notes: string[]
}

export interface TopSuppliers {
  months: string[]
  grouping: string
  series: { company: string; total: number; monthly: number[]; supplier_ids: string[]; parents: string[] }[]
}

export interface GNode {
  id: string
  kind: NodeKind
  label: string
  name: string
  properties: Record<string, unknown>
  matched?: string[]
}

export interface GEdge {
  id: string
  source: string
  target: string
  type: string
  aggregated: boolean
  via?: string
  label?: string
  shipments?: number
  first_arrival?: string
  last_arrival?: string
}

export interface DateFilter {
  date_from: string | null
  date_to: string | null
}

export interface Snapshot {
  mode: 'snapshot' | 'full'
  suppliers?: string[]
  filters: DateFilter
  nodes: GNode[]
  edges: GEdge[]
}

export interface Neighbours {
  node: GNode
  aggregate: boolean
  neighbours: GNode[]
  edges: GEdge[]
  total: number
  truncated: boolean
}

export interface EdgeShipments {
  source: string
  target: string
  shipments: GNode[]
  edges: GEdge[]
  count: number
}

export interface SupplierPicker {
  companies: {
    company: string
    shipments: number
    parent: string | null
    suppliers: { id: string; name: string; reported_country_code: string | null; shipments: number }[]
  }[]
}

export interface SearchResults {
  q: string
  total: number
  results: GNode[]
}
