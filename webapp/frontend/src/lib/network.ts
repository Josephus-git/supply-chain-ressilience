/** Shape the /api/home/network payload into what the map and its side card need. */
import type { Breakdown, Network, NetworkSupplier, Place } from './types'

export interface MapCompany {
  key: string
  company: string
  parent: string | null
  parentId: string | null
  supplierIds: string[]
  suppliers: NetworkSupplier[]
  location: Place
  reportedCountries: string[]
  shipments: number
  firstArrival: string | null
  lastArrival: string | null
  products: Breakdown[]
  exitPorts: Breakdown[]
  entryPorts: Breakdown[]
  carriers: Breakdown[]
}

function mergeBreakdowns(lists: Breakdown[][]): Breakdown[] {
  const acc = new Map<string, Breakdown>()
  for (const list of lists)
    for (const b of list) {
      const cur = acc.get(b.id)
      acc.set(b.id, cur ? { ...cur, shipments: cur.shipments + b.shipments } : { ...b })
    }
  return [...acc.values()].sort((a, b) => b.shipments - a.shipments)
}

const minStr = (xs: (string | null)[]) => xs.filter(Boolean).sort()[0] ?? null
const maxStr = (xs: (string | null)[]) => xs.filter(Boolean).sort().at(-1) ?? null

/**
 * One map marker per supplier company (Supplier.supplier_basename) and
 * location. Supplier nodes of one company at one site merge into one marker.
 */
export function companiesOf(net: Network): { companies: MapCompany[]; companyOfSupplier: Map<string, string> } {
  const groups = new Map<string, NetworkSupplier[]>()
  for (const s of net.suppliers) {
    if (!s.location) continue
    const key = `${s.company}@${s.location.lat.toFixed(2)},${s.location.lon.toFixed(2)}`
    groups.set(key, [...(groups.get(key) ?? []), s])
  }
  const companyOfSupplier = new Map<string, string>()
  const companies: MapCompany[] = []
  for (const [key, ss] of groups) {
    ss.forEach((s) => companyOfSupplier.set(s.id, key))
    companies.push({
      key,
      company: ss[0].company,
      parent: ss[0].parent,
      parentId: ss[0].parent_id,
      supplierIds: ss.map((s) => s.id),
      suppliers: ss,
      location: ss[0].location!,
      reportedCountries: [...new Set(ss.map((s) => s.reported_country_code).filter((c): c is string => !!c))],
      shipments: ss.reduce((n, s) => n + s.shipments, 0),
      firstArrival: minStr(ss.map((s) => s.first_arrival)),
      lastArrival: maxStr(ss.map((s) => s.last_arrival)),
      products: mergeBreakdowns(ss.map((s) => s.products)),
      exitPorts: mergeBreakdowns(ss.map((s) => s.exit_ports)),
      entryPorts: mergeBreakdowns(ss.map((s) => s.entry_ports)),
      carriers: mergeBreakdowns(ss.map((s) => s.carriers)),
    })
  }
  companies.sort((a, b) => b.shipments - a.shipments)
  return { companies, companyOfSupplier }
}
