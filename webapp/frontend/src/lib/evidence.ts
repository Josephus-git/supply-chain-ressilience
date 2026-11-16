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
