import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { getJson } from './api'

export type DateFamily = 'event_interval' | 'observation_point' | 'observation_start' | 'effective_interval'

export interface EvidenceDates {
  family: DateFamily
  start_field: string
  end_field: string | null
  start: string | null
  end: string | null
  /** Set when an effective interval has no end: it runs to the end of the study window. */
  open_end: string | null
  /** No start date: the record is an undated candidate, filtered by its search window. */
  undated: boolean
  known_from: string | null
  published_at: string | null
  filter_range: { start: string; end: string; basis: 'dates' | 'search_window' } | null
}

export interface EvidenceCountry {
  code: string
  name: string
  fields: string[]
  import_side: boolean
}

export interface EvidenceMeasure {
  label: string
  value: number
  unit: string | null
  note: string | null
}

export interface EvidenceSummary {
  evidence_id: string
  risk_type: string
  risk_label: string
  title: string
  description: string | null
  countries: EvidenceCountry[]
  dates: EvidenceDates
  measures: EvidenceMeasure[]
  entities: { field: string; value: string }[]
  verification_status: string | null
  limitations: string[]
  source: { publisher: string | null; url: string | null; published_at: string | null; licence_notes: string | null }
  related_evidence_ids: string[]
  incident_group_id: string | null
  graph_supplier_ids: string[]
}

export interface Facet {
  value: string
  label: string
  count: number
}

export interface GraphSupplier {
  id: string
  name: string
  company: string
}

export interface EvidenceList {
  total: number
  count: number
  records: EvidenceSummary[]
  facets: { risk_type: Facet[]; country: Facet[] }
  study_window: { start: string; end: string }
  graph_suppliers_by_country: Record<string, GraphSupplier[]>
  graph_error: string | null
  data_snapshot_id: string
}

export interface EvidenceBrief {
  evidence_id: string
  risk_type?: string
  risk_label?: string
  title?: string
  missing?: boolean
}

export interface EvidenceDetail {
  summary: EvidenceSummary
  record: Record<string, unknown>
  related: EvidenceBrief[]
  incident_group_id: string | null
  incident_group: EvidenceBrief[]
  graph_suppliers: GraphSupplier[]
  graph_error: string | null
  engine_version: string
  data_snapshot_id: string
}

export interface EvidenceFilters {
  risk_type: string | null
  country: string | null
  date_from: string | null
  date_to: string | null
  q: string | null
}

const STATIC = { staleTime: 5 * 60_000 }

export const useEvidenceList = (filters: EvidenceFilters) =>
  useQuery({
    queryKey: ['evidence', 'list', filters],
    queryFn: ({ signal }) => getJson<EvidenceList>('/evidence', { ...filters }, signal),
    placeholderData: keepPreviousData,
    ...STATIC,
  })

export const useEvidenceRecord = (id: string | undefined) =>
  useQuery({
    queryKey: ['evidence', 'record', id],
    queryFn: ({ signal }) => getJson<EvidenceDetail>(`/evidence/${encodeURIComponent(id!)}`, {}, signal),
    enabled: !!id,
    retry: false,
    ...STATIC,
  })

export const FAMILY_LABEL: Record<DateFamily, string> = {
  event_interval: 'Event',
  observation_point: 'Observed on',
  observation_start: 'Observation window',
  effective_interval: 'In effect',
}

/** "official_cbp_guidance_reviewed" -> "Official cbp guidance reviewed" */
export function humanise(s: string | null | undefined): string {
  if (!s) return '—'
  const t = s.replace(/_/g, ' ')
  return t.charAt(0).toUpperCase() + t.slice(1)
}

/** Explorer link for the suppliers whose reported country matches the record. */
export function explorerHref(supplierIds: string[]): string {
  return `/explorer?suppliers=${encodeURIComponent(supplierIds.join(','))}`
}

export type RiskGroupKey = 'supplier' | 'logistics' | 'policy' | 'hazard'

export interface RiskGroup {
  key: RiskGroupKey
  label: string
  blurb: string
  /** Tailwind class for the group's colour dot. */
  dot: string
  types: string[]
}

/** Four broad groups, so the 18 risk types read as a short outline, not a flat list. */
export const RISK_GROUPS: RiskGroup[] = [
  {
    key: 'supplier',
    label: 'Supplier and operations',
    blurb: 'Problems at or around the supplier itself.',
    dot: 'bg-violet-500',
    types: [
      'supplier_operational_disruption',
      'supplier_financial_distress',
      'product_quality_compliance',
      'labour_disruption',
      'cyberattack',
      'supplier_or_route_concentration',
    ],
  },
  {
    key: 'logistics',
    label: 'Logistics and transport',
    blurb: 'Disruption to goods on the move between supplier and Dyson.',
    dot: 'bg-sky-500',
    types: [
      'port_disruption',
      'carrier_vessel_disruption',
      'route_chokepoint_disruption',
      'goods_in_transit_loss_theft_or_damage',
      'border_customs_delays',
    ],
  },
  {
    key: 'policy',
    label: 'Trade policy and markets',
    blurb: 'Government action, conflict, and cost or supply shifts in markets.',
    dot: 'bg-amber-500',
    types: [
      'tariffs_and_duties',
      'government_restrictions',
      'geopolitical_conflict',
      'currency_fluctuations',
      'energy_or_transport_cost_increase',
      'input_material_shortage',
    ],
  },
  {
    key: 'hazard',
    label: 'Natural hazards',
    blurb: 'Earthquakes, storms, floods and other natural events.',
    dot: 'bg-rose-500',
    types: ['natural_hazards'],
  },
]

const GROUP_BY_TYPE: Record<string, RiskGroup> = Object.fromEntries(
  RISK_GROUPS.flatMap((g) => g.types.map((t) => [t, g])),
)

/** The group a risk type belongs to (unknown types fall back to trade policy and markets). */
export const riskGroup = (riskType: string): RiskGroup => GROUP_BY_TYPE[riskType] ?? RISK_GROUPS[2]

/** One plain line per risk type, shown on the overview tiles and the type header. */
export const RISK_BLURB: Record<string, string> = {
  supplier_operational_disruption: 'Fires, outages and shutdowns that stop a supplier producing.',
  supplier_financial_distress: 'Losses, insolvency or credit warnings at a supplier.',
  product_quality_compliance: 'Recalls, defects and failed regulatory checks.',
  labour_disruption: 'Strikes, walkouts and labour shortages.',
  cyberattack: 'Ransomware and other attacks that halt systems.',
  supplier_or_route_concentration: 'Heavy reliance on one supplier, country or route.',
  port_disruption: 'Closures, congestion and delays at ports.',
  carrier_vessel_disruption: 'Problems with shipping lines, vessels or aircraft.',
  route_chokepoint_disruption: 'Blocked or diverted straits, canals and key routes.',
  goods_in_transit_loss_theft_or_damage: 'Cargo lost, stolen or damaged on the way.',
  border_customs_delays: 'Holds, inspections and slow clearance at borders.',
  tariffs_and_duties: 'New or changed duties on imported goods.',
  government_restrictions: 'Export controls, sanctions, bans and similar rules.',
  geopolitical_conflict: 'Wars, unrest and political tension between countries.',
  currency_fluctuations: 'Exchange rate moves that change what parts cost.',
  energy_or_transport_cost_increase: 'Rising fuel, power or freight prices.',
  input_material_shortage: 'Shortages or price spikes in raw materials and parts.',
  natural_hazards: 'Earthquakes, storms, floods and other natural events.',
}
