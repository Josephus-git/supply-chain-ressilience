import type { EChartsCoreOption } from 'echarts/core'
import { useMemo } from 'react'
import { EChart } from '@/components/charts/EChart'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmt, monthLabel } from '@/lib/format'
import { CATEGORICAL, CHROME, OVERFLOW, type Mode } from '@/lib/palette'
import type { TopSuppliers } from '@/lib/types'

/**
 * Colour follows the company, fixed by its overall rank in the response, so a
 * legend toggle never repaints the others. Ranks 9 and 10 fall past the
 * 8-slot palette: they share the neutral and are told apart by dash pattern.
 */
export function companyStyle(mode: Mode, rank: number) {
  if (rank < CATEGORICAL[mode].length) return { color: CATEGORICAL[mode][rank], dash: 'solid' as const }
  return { color: OVERFLOW[mode], dash: rank % 2 === 0 ? ([6, 4] as number[]) : ([2, 3] as number[]) }
}

export function TopSuppliersChart({ data, mode }: { data: TopSuppliers; mode: Mode }) {
  const option = useMemo<EChartsCoreOption>(() => {
    const ch = CHROME[mode]
    return {
      backgroundColor: 'transparent',
      grid: { left: 8, right: 16, top: 56, bottom: 8, outerBoundsMode: 'same', outerBounds: { left: 0, right: 0, top: 0, bottom: 0 } },
      legend: {
        type: 'scroll',
        top: 0,
        left: 0,
        right: 0,
        icon: 'roundRect',
        itemWidth: 14,
        itemHeight: 4,
        itemGap: 14,
        textStyle: { color: ch.ink2, fontSize: 12 },
        pageIconColor: ch.ink2,
        pageTextStyle: { color: ch.muted },
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'line', lineStyle: { color: ch.axis } },
        backgroundColor: ch.surface,
        borderColor: ch.ring,
        textStyle: { color: ch.ink, fontSize: 12 },
        extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,.12);border-radius:8px;',
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        formatter: (ps: any[]) => {
          const rows = ps
            .filter((p) => p.value > 0)
            .sort((a, b) => b.value - a.value)
            .map(
              (p) =>
                `<div style="display:flex;align-items:center;gap:8px"><span style="display:inline-block;width:10px;height:3px;border-radius:2px;background:${p.color}"></span><span style="flex:1;color:${ch.ink2}">${p.seriesName}</span><span style="font-variant-numeric:tabular-nums">${p.value}</span></div>`,
            )
          const total = ps.reduce((n, p) => n + (p.value || 0), 0)
          return `<div style="min-width:220px"><div style="font-weight:600;margin-bottom:4px">${monthLabel(data.months[ps[0].dataIndex])} · ${total} shipments</div>${rows.join('') || `<div style="color:${ch.muted}">No shipments</div>`}</div>`
        },
      },
      xAxis: {
        type: 'category',
        data: data.months,
        boundaryGap: false,
        axisLine: { lineStyle: { color: ch.axis } },
        axisTick: { show: false },
        axisLabel: { color: ch.muted, fontSize: 11, formatter: (m: string) => monthLabel(m, true), hideOverlap: true },
      },
      yAxis: {
        type: 'value',
        name: 'Shipments / month',
        nameTextStyle: { color: ch.muted, fontSize: 11, align: 'left' },
        minInterval: 1,
        splitLine: { lineStyle: { color: ch.grid } },
        axisLabel: { color: ch.muted, fontSize: 11 },
      },
      series: data.series.map((s, rank) => {
        const st = companyStyle(mode, rank)
        return {
          name: s.company,
          type: 'line',
          data: s.monthly,
          symbol: 'circle',
          symbolSize: 6,
          showSymbol: false,
          lineStyle: { width: 2, color: st.color, type: st.dash },
          itemStyle: { color: st.color, borderColor: ch.surface, borderWidth: 2 },
          emphasis: { focus: 'series', lineStyle: { width: 3 } },
          blur: { lineStyle: { opacity: 0.15 } },
        }
      }),
    }
  }, [data, mode])

  return <EChart option={option} />
}

export function TopSuppliersTable({ data, mode }: { data: TopSuppliers; mode: Mode }) {
  return (
    <div className="h-full overflow-auto">
      <Table className="tabular text-xs">
        <TableHeader>
          <TableRow>
            <TableHead className="sticky left-0 bg-card">Company</TableHead>
            <TableHead className="text-right">Total</TableHead>
            {data.months.map((m) => <TableHead key={m} className="text-right">{monthLabel(m, true)}</TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.series.map((s, rank) => (
            <TableRow key={s.company}>
              <TableCell className="sticky left-0 bg-card font-medium">
                <span className="mr-2 inline-block h-1 w-3 rounded-sm align-middle" style={{ background: companyStyle(mode, rank).color }} />
                {s.company}
              </TableCell>
              <TableCell className="text-right font-medium">{fmt(s.total)}</TableCell>
              {s.monthly.map((n, i) => (
                <TableCell key={i} className={n ? 'text-right' : 'text-right text-muted-foreground/50'}>{n || '·'}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
