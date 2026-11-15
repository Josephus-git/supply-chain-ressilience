import { ArrowRight, Info, MapPin, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { dateLabel, fmt } from '@/lib/format'
import type { MapCompany } from '@/lib/network'
import type { Breakdown } from '@/lib/types'

function BarList({ title, items, max = 5 }: { title: string; items: Breakdown[]; max?: number }) {
  if (!items.length) return null
  const top = items.slice(0, max)
  const peak = top[0]?.shipments || 1
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between text-xs font-medium text-muted-foreground">
        <span>{title}</span>
        {items.length > max && <span className="font-normal">top {max} of {items.length}</span>}
      </div>
      <ul className="space-y-1">
        {top.map((b) => (
          <li key={b.id} className="relative overflow-hidden rounded-md px-2 py-1 text-xs">
            <div className="absolute inset-y-0 left-0 rounded-md bg-primary/10" style={{ width: `${(b.shipments / peak) * 100}%` }} />
            <div className="relative flex items-center gap-2">
              <span className="flex-1 truncate" title={b.name}>{b.name}</span>
              <span className="tabular font-medium">{b.shipments}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function SupplierCard({ company, onClose }: { company: MapCompany; onClose: () => void }) {
  const loc = company.location
  const mismatch = company.reportedCountries.some((c) => c !== loc.country_code)
  const explorerHref = `/explorer?suppliers=${encodeURIComponent(company.supplierIds.join(','))}`
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start gap-2 border-b p-4">
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold" title={company.company}>{company.company}</div>
          <div className="truncate text-xs text-muted-foreground">{company.parent ? `Subsidiary of ${company.parent}` : 'No parent company recorded'}</div>
        </div>
        <Button variant="ghost" size="icon" className="-mr-2 -mt-1 size-7" onClick={onClose} aria-label="Close">
          <X className="size-4" />
        </Button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <div className="text-xs text-muted-foreground">Shipments</div>
            <div className="text-xl font-semibold">{fmt(company.shipments)}</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Arrivals</div>
            <div className="text-xs leading-5">{dateLabel(company.firstArrival)}<br />{dateLabel(company.lastArrival)}</div>
          </div>
        </div>

        <div className="space-y-1.5 text-xs">
          <div className="flex items-center gap-1.5">
            <MapPin className="size-3.5 text-muted-foreground" />
            <span>{loc.label}{loc.country_code ? `, ${loc.country_code}` : ''}</span>
            {loc.basis && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info className="size-3.5 cursor-help text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">{loc.basis}</TooltipContent>
              </Tooltip>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-muted-foreground">Reported country (ImportYeti):</span>
            {company.reportedCountries.map((c) => <Badge key={c} variant="outline">{c}</Badge>)}
          </div>
          {mismatch && (
            <p className="rounded-md bg-muted px-2 py-1.5 text-muted-foreground">
              The reported country differs from the address. The map plots the address; the risk engine uses the reported value.
            </p>
          )}
          {company.suppliers.length > 1 && (
            <div className="text-muted-foreground">{company.suppliers.length} supplier nodes: {company.suppliers.map((s) => s.name).join(' · ')}</div>
          )}
        </div>

        <BarList title="Products" items={company.products} />
        <BarList title="Exit ports" items={company.exitPorts} />
        <BarList title="US entry ports" items={company.entryPorts} />
        <BarList title="Carriers" items={company.carriers} />
      </div>
      <div className="border-t p-3">
        <Button asChild className="w-full" size="sm">
          <Link to={explorerHref}>Open in Graph Explorer <ArrowRight className="size-4" /></Link>
        </Button>
      </div>
    </div>
  )
}

export function CompanyList({ companies, onSelect }: { companies: MapCompany[]; onSelect: (key: string) => void }) {
  const peak = companies[0]?.shipments || 1
  const seen = new Map<string, number>()
  companies.forEach((c) => seen.set(c.company, (seen.get(c.company) ?? 0) + 1))
  const dupes = new Set([...seen].filter(([, n]) => n > 1).map(([name]) => name))
  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-4">
        <div className="font-semibold">Supplier companies</div>
        <div className="text-xs text-muted-foreground">Click a company here or on the map. Companies with two sites appear twice.</div>
      </div>
      <ul className="flex-1 space-y-0.5 overflow-y-auto p-2">
        {companies.map((c) => (
          <li key={c.key}>
            <button
              onClick={() => onSelect(c.key)}
              className="relative w-full overflow-hidden rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent"
            >
              <div className="absolute inset-y-1 left-0 rounded-r bg-primary/10" style={{ width: `${(c.shipments / peak) * 100}%` }} />
              <div className="relative flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate">
                  {c.company}
                  {dupes.has(c.company) && <span className="ml-1.5 text-xs text-muted-foreground">{c.location.label}</span>}
                </span>
                <span className="text-xs text-muted-foreground">{c.location.country_code}</span>
                <span className="tabular w-8 text-right text-xs font-medium">{c.shipments}</span>
              </div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
