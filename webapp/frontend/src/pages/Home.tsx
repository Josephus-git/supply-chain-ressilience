import { AlertTriangle, LocateFixed, Table2, TrendingUp } from 'lucide-react'
import { useMemo, useState } from 'react'
import { PageContainer } from '@/components/layout/AppShell'
import { ErrorBoundary } from '@/components/layout/ErrorBoundary'
import { KpiTiles } from '@/components/home/KpiTiles'
import { CompanyList, SupplierCard } from '@/components/home/SupplierCard'
import { TopSuppliersChart, TopSuppliersTable } from '@/components/home/TopSuppliersChart'
import { mapColors, WorldMap, type MapView } from '@/components/home/WorldMap'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useHomeStats, useNetwork, useTopSuppliers } from '@/lib/api'
import { dateLabel } from '@/lib/format'
import { companiesOf } from '@/lib/network'
import { useTheme } from '@/lib/theme'

function ErrorNote({ error }: { error: unknown }) {
  return (
    <div className="flex h-full items-center justify-center gap-2 p-6 text-sm text-muted-foreground">
      <AlertTriangle className="size-4 text-destructive" />
      {error instanceof Error ? error.message : 'Request failed'}
    </div>
  )
}

function Item({ children }: { children: React.ReactNode }) {
  return <span className="flex items-center gap-1.5">{children}</span>
}

function MapLegend({ view }: { view: MapView }) {
  const { mode } = useTheme()
  const c = mapColors(mode)
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <Item><span className="size-2.5 rounded-full" style={{ background: c.supplier }} /> Supplier (size = shipments)</Item>
      <Item>
        <svg width="10" height="12" viewBox="0 0 10 12"><path d="M5 12 1 6a4 4 0 1 1 8 0z" fill={c.dyson} /></svg> Dyson site
      </Item>
      {view === 'routes' && (
        <>
          <Item><svg width="10" height="10"><path d="M5 1 9 9H1z" fill={c.port} /></svg> Exit port</Item>
          <Item><svg width="10" height="10"><path d="M5 0 10 5 5 10 0 5z" fill={c.port} /></svg> US entry port</Item>
          <Item><span className="w-4 border-t-2 border-dashed" style={{ borderColor: c.supplier }} /> Land leg</Item>
        </>
      )}
      <Item><span className="h-1 w-4 rounded" style={{ background: c.supplier }} /> {view === 'routes' ? 'Ocean leg' : 'Shipments'} (width = count)</Item>
    </div>
  )
}

export default function Home() {
  const { mode } = useTheme()
  const stats = useHomeStats()
  const network = useNetwork()
  const top = useTopSuppliers(10)
  const [view, setView] = useState<MapView>('links')
  const [selected, setSelected] = useState<string | null>(null)
  const [chartView, setChartView] = useState<'chart' | 'table'>('chart')
  const [reset, setReset] = useState(0)

  const grouped = useMemo(() => (network.data ? companiesOf(network.data) : null), [network.data])
  const selectedCompany = grouped?.companies.find((c) => c.key === selected)

  return (
    <PageContainer className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Dyson supplier network</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Ten supplier companies shipping to Dyson's US sites, from US import records (ImportYeti) loaded into a Neo4j
          knowledge graph.
          {stats.data && <> Study window {dateLabel(stats.data.study_window.start)} – {dateLabel(stats.data.study_window.end)}.</>}
        </p>
      </div>

      <KpiTiles stats={stats.data} />

      <Card className="gap-0 overflow-hidden py-0">
        <CardHeader className="border-b py-4">
          <CardTitle>Where shipments come from</CardTitle>
          <CardDescription><MapLegend view={view} /></CardDescription>
          <CardAction className="col-start-1 row-start-3 mt-2 flex items-center gap-2 justify-self-start sm:col-start-2 sm:row-span-2 sm:row-start-1 sm:mt-0 sm:justify-self-end">
            <Button variant="ghost" size="icon" className="size-8" onClick={() => setReset((n) => n + 1)} aria-label="Recentre map">
              <LocateFixed className="size-4" />
            </Button>
            <ToggleGroup type="single" variant="outline" size="sm" value={view} onValueChange={(v) => v && setView(v as MapView)}>
              <ToggleGroupItem value="links">Supplier → Dyson</ToggleGroupItem>
              <ToggleGroupItem value="routes">Real routes</ToggleGroupItem>
            </ToggleGroup>
          </CardAction>
        </CardHeader>
        <div className="grid lg:grid-cols-[1fr_320px]">
          <div className="relative h-[460px] lg:h-[540px]">
            {network.isPending && <Skeleton className="absolute inset-4" />}
            {network.isError && <ErrorNote error={network.error} />}
            {network.data && grouped && (
              <ErrorBoundary label="The map">
              <WorldMap
                network={network.data}
                companies={grouped.companies}
                companyOfSupplier={grouped.companyOfSupplier}
                view={view}
                mode={mode}
                selected={selected}
                onSelect={setSelected}
                resetToken={reset}
              />
              </ErrorBoundary>
            )}
          </div>
          <div className="h-[460px] border-t lg:h-[540px] lg:border-t-0 lg:border-l">
            {selectedCompany ? (
              <SupplierCard company={selectedCompany} onClose={() => setSelected(null)} />
            ) : grouped ? (
              <CompanyList companies={grouped.companies} onSelect={setSelected} />
            ) : (
              <div className="space-y-2 p-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-7" />)}</div>
            )}
          </div>
        </div>
        {network.data && (
          <div className="border-t px-4 py-2.5 text-[11px] leading-relaxed text-muted-foreground">
            {network.data.notes.join(' ')}
            {network.data.missing_locations.length > 0 && <> Not plotted (no coordinates): {network.data.missing_locations.join(', ')}.</>}
          </div>
        )}
      </Card>

      <Card className="gap-0 py-0">
        <CardHeader className="border-b py-4">
          <CardTitle>Top 10 suppliers by monthly shipments</CardTitle>
          <CardDescription>
            Grouped by company (Supplier.supplier_basename). Hover a month for the breakdown; click a legend entry to hide it.
          </CardDescription>
          <CardAction>
            <ToggleGroup type="single" variant="outline" size="sm" value={chartView} onValueChange={(v) => v && setChartView(v as 'chart' | 'table')}>
              <ToggleGroupItem value="chart" aria-label="Chart"><TrendingUp className="size-4" /></ToggleGroupItem>
              <ToggleGroupItem value="table" aria-label="Table"><Table2 className="size-4" /></ToggleGroupItem>
            </ToggleGroup>
          </CardAction>
        </CardHeader>
        <div className="h-[400px] p-4">
          {top.isPending && <Skeleton className="h-full" />}
          {top.isError && <ErrorNote error={top.error} />}
          {top.data && (
            <ErrorBoundary label="The chart">
              {chartView === 'chart' ? <TopSuppliersChart data={top.data} mode={mode} /> : <TopSuppliersTable data={top.data} mode={mode} />}
            </ErrorBoundary>
          )}
        </div>
      </Card>
    </PageContainer>
  )
}
