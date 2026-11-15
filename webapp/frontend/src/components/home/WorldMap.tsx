import type { EChartsCoreOption } from 'echarts/core'
import { useMemo, useRef } from 'react'
import { EChart, WORLD_MAP } from '@/components/charts/EChart'
import { fmt } from '@/lib/format'
import { CUT, toMap } from '@/lib/geo'
import type { MapCompany } from '@/lib/network'
import { CATEGORICAL, CHROME, MAP, type Mode } from '@/lib/palette'
import type { Network } from '@/lib/types'

export type MapView = 'links' | 'routes'

/** Map colours: three categorical slots, the all-pairs-safe set for point marks. */
export function mapColors(mode: Mode) {
  const c = CATEGORICAL[mode]
  return { supplier: c[0], dyson: c[1], port: c[2] }
}

const esc = (s: unknown) =>
  String(s ?? '').replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch]!)

function widthScale(max: number, lo = 0.5, hi = 1.8) {
  return (n: number) => lo + (hi - lo) * Math.sqrt(n / Math.max(max, 1))
}

type Pt = [number, number]

/**
 * Project a [lon, lat] path into the Pacific-centred frame, splitting it where it
 * crosses the map seam (CUT) so an Atlantic crossing does not streak across the map.
 */
function projectPath(path: Pt[]): Pt[][] {
  const parts: Pt[][] = [[]]
  path.forEach(([lon, lat], i) => {
    if (i > 0) {
      const [plon, plat] = path[i - 1]
      if (plon >= CUT !== lon >= CUT && Math.abs(plon - lon) < 180) {
        const y = plat + ((lat - plat) * (CUT - plon)) / (lon - plon)
        parts[parts.length - 1].push(plon >= CUT ? [CUT, y] : [CUT + 360, y])
        parts.push([plon >= CUT ? [CUT + 360, y] : [CUT, y]])
      }
    }
    parts[parts.length - 1].push(toMap(lon, lat))
  })
  return parts.filter((p) => p.length > 1)
}

export const DEFAULT_VIEW = { center: [185, 24] as [number, number], zoom: 1.9 }

interface Props {
  network: Network
  companies: MapCompany[]
  companyOfSupplier: Map<string, string>
  view: MapView
  mode: Mode
  selected: string | null
  onSelect: (companyKey: string | null) => void
  /** Bump to recentre the map. */
  resetToken?: number
}

export function WorldMap({ network, companies, companyOfSupplier, view, mode, selected, onSelect, resetToken = 0 }: Props) {
  // Pan and zoom survive data updates: options merge, and the last roam is fed back in.
  const roam = useRef({ ...DEFAULT_VIEW })
  const lastReset = useRef(resetToken)
  if (lastReset.current !== resetToken) {
    lastReset.current = resetToken
    roam.current = { ...DEFAULT_VIEW }
  }

  const option = useMemo<EChartsCoreOption>(() => {
    const ch = CHROME[mode]
    const mp = MAP[mode]
    const col = mapColors(mode)
    const byKey = new Map(companies.map((c) => [c.key, c]))
    const buyers = new Map(network.buyers.map((b) => [b.id, b]))
    const ports = new Map(network.ports.map((p) => [p.id, p]))
    const dim = (companyKey: string | undefined) => selected != null && companyKey !== selected
    const sel = selected ? byKey.get(selected) : undefined
    const selPorts = new Set([...(sel?.exitPorts ?? []), ...(sel?.entryPorts ?? [])].map((p) => p.id))

    const tooltipBox = (title: string, rows: [string, string][], note?: string) =>
      `<div style="min-width:180px"><div style="font-weight:600;margin-bottom:4px">${esc(title)}</div>` +
      rows.map(([k, v]) => `<div style="display:flex;gap:12px;justify-content:space-between"><span style="color:${ch.ink2}">${esc(k)}</span><span>${esc(v)}</span></div>`).join('') +
      (note ? `<div style="margin-top:4px;color:${ch.muted};font-size:11px">${esc(note)}</div>` : '') +
      '</div>'

    // --- point layers
    const maxCompany = Math.max(...companies.map((c) => c.shipments), 1)
    const supplierData = companies.map((c) => ({
      name: c.company,
      value: [...toMap(c.location.lon, c.location.lat), c.shipments],
      key: c.key,
      symbolSize: 9 + 13 * Math.sqrt(c.shipments / maxCompany),
      itemStyle: { opacity: dim(c.key) ? 0.25 : 1 },
      tip: tooltipBox(
        c.company,
        [
          ['Shipments', fmt(c.shipments)],
          ['Location', `${c.location.label ?? ''}${c.location.country_code ? `, ${c.location.country_code}` : ''}`],
          ['Reported country', c.reportedCountries.join(', ') || '—'],
          ['Parent', c.parent ?? '—'],
        ],
        'Click for products, ports and carriers',
      ),
    }))

    const buyerData = network.buyers
      .filter((b) => b.location)
      .map((b) => ({
        name: b.name,
        value: [...toMap(b.location!.lon, b.location!.lat), b.shipments],
        tip: tooltipBox(b.name, [
          ['Shipments received', fmt(b.shipments)],
          ['Site', b.location!.label ?? '—'],
        ], 'Dyson site (consignee)'),
      }))

    const portData = network.ports
      .filter((p) => p.location && p.shipments > 0)
      .map((p) => ({
        name: p.name,
        value: [...toMap(p.location!.lon, p.location!.lat), p.shipments],
        symbol: p.kind === 'exit_port' ? 'triangle' : 'diamond',
        symbolSize: 7,
        itemStyle: { opacity: selected && !selPorts.has(p.id) ? 0.2 : 1 },
        tip: tooltipBox(
          p.name,
          [
            ['Type', p.kind === 'exit_port' ? 'Exit port' : 'Entry port (US)'],
            ['Shipments', fmt(p.shipments)],
            ...(p.code != null ? ([['Code', String(p.code)]] as [string, string][]) : []),
          ],
          p.location!.level === 'country' ? 'Catch-all port: drawn at country level' : undefined,
        ),
      }))

    // --- line layers
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const lines: any[] = []
    const lineSeries = (name: string, data: unknown[], curveness: number, color: string, dashed = false, polyline = false) => ({
      type: 'lines',
      name,
      coordinateSystem: 'geo',
      zlevel: 1,
      polyline,
      data,
      lineStyle: { color, curveness, opacity: 0.55, cap: 'round', type: dashed ? [4, 4] : 'solid' },
      effect: { show: true, period: 5, trailLength: 0.25, symbol: 'circle', symbolSize: 3, color },
      emphasis: { lineStyle: { opacity: 0.95 } },
      tooltip: { show: true },
      silent: false,
    })

    if (view === 'links') {
      const agg = new Map<string, { company: string; buyer: string; shipments: number }>()
      for (const l of network.links) {
        const ck = companyOfSupplier.get(l.supplier)
        if (!ck || !buyers.get(l.buyer)?.location) continue
        const k = `${ck}|${l.buyer}`
        const cur = agg.get(k)
        agg.set(k, { company: ck, buyer: l.buyer, shipments: (cur?.shipments ?? 0) + l.shipments })
      }
      const w = widthScale(Math.max(...[...agg.values()].map((a) => a.shipments), 1))
      const data = [...agg.values()].map((a) => {
        const c = byKey.get(a.company)!
        const b = buyers.get(a.buyer)!
        return {
          coords: [toMap(c.location.lon, c.location.lat), toMap(b.location!.lon, b.location!.lat)],
          key: a.company,
          lineStyle: { width: w(a.shipments), opacity: dim(a.company) ? 0.06 : 0.55 },
          tip: tooltipBox(`${c.company} → ${b.name}`, [['Shipments', fmt(a.shipments)]]),
        }
      })
      lines.push(lineSeries('Supplier → Dyson', data, 0.28, col.supplier))
    } else {
      // Each route is supplier -> exit port -> entry port -> Dyson site, drawn
      // as three legs and aggregated per leg so shared legs read as one thicker line.
      type Leg = { from: Pt; to: Pt; shipments: number; companies: Set<string>; title: string }
      const seaPaths = new Map((network.sea_paths ?? []).map((p) => [`${p.exit_port}|${p.entry_port}`, p]))
      const legs = { land: new Map<string, Leg>(), sea: new Map<string, Leg>(), inland: new Map<string, Leg>() }
      const add = (m: Map<string, Leg>, k: string, from: [number, number], to: [number, number], n: number, ck: string, title: string) => {
        const cur = m.get(k) ?? { from, to, shipments: 0, companies: new Set<string>(), title }
        cur.shipments += n
        cur.companies.add(ck)
        m.set(k, cur)
      }
      for (const r of network.routes) {
        const ck = companyOfSupplier.get(r.supplier)
        const c = ck ? byKey.get(ck) : undefined
        const xp = ports.get(r.exit_port)?.location
        const ep = ports.get(r.entry_port)?.location
        const b = buyers.get(r.buyer)
        if (!c || !xp || !ep || !b?.location) continue
        const S = toMap(c.location.lon, c.location.lat)
        const X = toMap(xp.lon, xp.lat)
        const E = toMap(ep.lon, ep.lat)
        const B = toMap(b.location.lon, b.location.lat)
        const xn = ports.get(r.exit_port)!.name
        const en = ports.get(r.entry_port)!.name
        add(legs.land, `${ck}|${r.exit_port}`, S, X, r.shipments, ck!, `${c.company} → ${xn}`)
        add(legs.sea, `${r.exit_port}|${r.entry_port}|${ck}`, X, E, r.shipments, ck!, `${xn} → ${en}`)
        add(legs.inland, `${r.entry_port}|${r.buyer}`, E, B, r.shipments, ck!, `${en} → ${b.name}`)
      }
      const all = [...legs.land.values(), ...legs.sea.values(), ...legs.inland.values()]
      const w = widthScale(Math.max(...all.map((l) => l.shipments), 1), 0.4, 1.6)
      const legData = (l: Leg, label: string, coords: Pt[], extra: [string, string][] = [], note?: string) => ({
        coords,
        lineStyle: { width: w(l.shipments), opacity: selected != null && !l.companies.has(selected) ? 0.05 : 0.6 },
        tip: tooltipBox(l.title, [
          ['Leg', label],
          ['Shipments', fmt(l.shipments)],
          ...extra,
          ['Suppliers', [...l.companies].map((k) => byKey.get(k)?.company).join(', ')],
        ], note),
      })
      const toData = (m: Map<string, Leg>, label: string) => [...m.values()].map((l) => legData(l, label, [l.from, l.to]))

      // Ocean legs follow the likely sea lane (searoute) when the backend has one;
      // otherwise (e.g. catch-all ports drawn at country level) a straight arc.
      const seaRouted: unknown[] = []
      const seaStraight: unknown[] = []
      for (const [k, l] of legs.sea) {
        const [xp, ep] = k.split('|')
        const sp = seaPaths.get(`${xp}|${ep}`)
        if (!sp) {
          seaStraight.push(legData(l, 'Exit port → US entry port', [l.from, l.to], [], 'Straight line: no sea path for this port'))
          continue
        }
        const extra: [string, string][] = [['Likely route', sp.via], ['Distance', `${fmt(sp.length_km)} km`]]
        const note = 'Likely shortest sea lane, not the recorded vessel track'
        for (const part of projectPath(sp.coords)) seaRouted.push(legData(l, 'Exit port → US entry port', part, extra, note))
      }
      lines.push(lineSeries('Supplier → exit port', toData(legs.land, 'Supplier → exit port'), 0, col.supplier, true))
      lines.push(lineSeries('Ocean leg', seaRouted, 0, col.supplier, false, true))
      if (seaStraight.length) lines.push(lineSeries('Ocean leg (straight)', seaStraight, 0.22, col.supplier))
      lines.push(lineSeries('Entry port → Dyson', toData(legs.inland, 'US entry port → Dyson site'), 0, col.dyson, true))
    }

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        backgroundColor: ch.surface,
        borderColor: ch.ring,
        textStyle: { color: ch.ink, fontSize: 12 },
        extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,.12);border-radius:8px;',
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        formatter: (p: any) => p.data?.tip ?? esc(p.name),
      },
      geo: {
        map: WORLD_MAP,
        roam: true,
        center: roam.current.center,
        zoom: roam.current.zoom,
        scaleLimit: { min: 1, max: 12 },
        silent: false,
        itemStyle: { areaColor: mp.land, borderColor: mp.landBorder, borderWidth: 0.6 },
        emphasis: { disabled: true },
        select: { disabled: true },
        tooltip: { show: false },
      },
      series: [
        ...lines,
        {
          type: 'scatter', name: 'US entry & exit ports', coordinateSystem: 'geo', zlevel: 2,
          data: portData, itemStyle: { color: col.port, borderColor: ch.surface, borderWidth: 1 },
        },
        {
          type: 'scatter', name: 'Dyson sites', coordinateSystem: 'geo', zlevel: 3,
          data: buyerData, symbol: 'pin', symbolSize: 26,
          itemStyle: { color: col.dyson, borderColor: ch.surface, borderWidth: 1.5 },
        },
        {
          type: 'effectScatter', name: 'Suppliers', coordinateSystem: 'geo', zlevel: 3,
          data: supplierData, rippleEffect: { scale: 2.4, brushType: 'stroke', number: 2 },
          showEffectOn: 'render',
          itemStyle: { color: col.supplier, borderColor: ch.surface, borderWidth: 1.5 },
          cursor: 'pointer',
        },
      ],
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [network, companies, companyOfSupplier, view, mode, selected, resetToken])

  return (
    <EChart
      option={option}
      needsWorld
      notMerge={false}
      replaceMerge={['series']}
      events={{
        georoam: (_p: unknown, chart) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const geo = (chart.getOption() as any).geo?.[0]
          if (geo?.center) roam.current = { center: geo.center, zoom: geo.zoom }
        },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        click: (p: any) => {
          if (p.seriesName === 'Suppliers' && p.data?.key) onSelect(p.data.key === selected ? null : p.data.key)
          else if (p.data?.key) onSelect(p.data.key)
          else if (p.componentType === 'geo') onSelect(null)
        },
      }}
    />
  )
}
