/**
 * Thin wrapper over echarts-for-react's core build. Only the chart types the
 * app uses are registered, which keeps the bundle small.
 */
import { EffectScatterChart, LineChart, LinesChart, MapChart, ScatterChart } from 'echarts/charts'
import {
  DataZoomComponent, GeoComponent, GridComponent, LegendComponent, TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import type { EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import ReactEChartsCoreModule from 'echarts-for-react/lib/core'
import type { ComponentType, CSSProperties } from 'react'
import { pacificWorld } from '@/lib/geo'

// echarts-for-react ships CommonJS; depending on the bundler path the default
// export arrives either as the component or wrapped as { default: component }.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ReactEChartsCore: ComponentType<any> = (ReactEChartsCoreModule as any).default ?? ReactEChartsCoreModule

echarts.use([
  LineChart, LinesChart, MapChart, ScatterChart, EffectScatterChart,
  GeoComponent, GridComponent, LegendComponent, TooltipComponent, DataZoomComponent,
  CanvasRenderer,
])

export const WORLD_MAP = 'pacific-world'
let registered = false
function ensureWorld() {
  if (!registered) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    echarts.registerMap(WORLD_MAP, pacificWorld() as any)
    registered = true
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type EChartEvents = Record<string, (params: any, chart: echarts.ECharts) => void>

export function EChart({
  option, events, style, className, needsWorld = false, notMerge = true, replaceMerge,
}: {
  option: EChartsCoreOption
  events?: EChartEvents
  style?: CSSProperties
  className?: string
  needsWorld?: boolean
  notMerge?: boolean
  replaceMerge?: string[]
}) {
  if (needsWorld) ensureWorld()
  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      notMerge={notMerge}
      replaceMerge={replaceMerge}
      lazyUpdate
      onEvents={events}
      style={{ height: '100%', width: '100%', ...style }}
      className={className}
      opts={{ renderer: 'canvas' }}
    />
  )
}
