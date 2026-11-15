# Frontend

React 19 + Vite + TypeScript, Tailwind v4 with shadcn/ui (radix-nova), TanStack
Query, ECharts (Home map and chart) and Cytoscape.js with fcose (Graph Explorer).
See [../README.md](../README.md) for how to run it.

```
src/
  main.tsx, App.tsx          providers and routes
  lib/                       api.ts (typed hooks), types.ts, palette.ts, kinds.ts,
                             geo.ts (offline Pacific-centred world), network.ts, theme.tsx
  components/layout/         AppShell (sidebar, health dot, theme menu), ErrorBoundary
  components/charts/         EChart wrapper (tree-shaken echarts core)
  components/home/           KpiTiles, WorldMap, TopSuppliersChart, SupplierCard
  components/graph/          GraphCanvas (Cytoscape), Inspector, useGraphState, KindBadge
  components/ui/             shadcn components (add more with `npx shadcn@latest add …`)
  pages/                     Home, Explorer, Placeholder (phases 3–5)
```

Colours come from `lib/palette.ts`: the validated categorical palette, stepped
separately for light and dark. ECharts and Cytoscape read it directly. Graph
node kinds use colour and shape together, so identity never rests on colour alone.
