/**
 * Chart and graph colours. Values come from the validated dataviz reference
 * palette (categorical slots in fixed order, light and dark stepped separately).
 * ECharts and Cytoscape need concrete colours, so they read these, not CSS vars.
 */
export type Mode = 'light' | 'dark'

export const CATEGORICAL: Record<Mode, string[]> = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#0ca30c', '#9085e9', '#e66767'],
}

/** Neutral for series past slot 8; always paired with a dashed line (secondary encoding). */
export const OVERFLOW: Record<Mode, string> = { light: '#898781', dark: '#898781' }

export const CHROME: Record<
  Mode,
  { surface: string; ink: string; ink2: string; muted: string; grid: string; axis: string; ring: string }
> = {
  light: {
    surface: '#fcfcfb', ink: '#0b0b0b', ink2: '#52514e', muted: '#898781',
    grid: '#e1e0d9', axis: '#c3c2b7', ring: 'rgba(11,11,11,0.10)',
  },
  dark: {
    surface: '#1a1a19', ink: '#f0efec', ink2: '#c3c2b7', muted: '#898781',
    grid: '#2c2c2a', axis: '#383835', ring: 'rgba(255,255,255,0.10)',
  },
}

/** Map land and sea, recessive so the data marks carry the eye. */
export const MAP: Record<Mode, { land: string; landBorder: string; landHover: string }> = {
  light: { land: '#eeede8', landBorder: '#d6d5cd', landHover: '#e4e3dc' },
  dark: { land: '#262624', landBorder: '#383835', landHover: '#2e2e2c' },
}

/** Colour for categorical slot i (0-based); past the palette, the neutral overflow. */
export function seriesColor(mode: Mode, i: number): string {
  return CATEGORICAL[mode][i] ?? OVERFLOW[mode]
}
