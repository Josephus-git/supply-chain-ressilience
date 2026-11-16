import { Gauge } from 'lucide-react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import Ask from '@/pages/Ask'
import Evidence from '@/pages/Evidence'
import Explorer from '@/pages/Explorer'
import Home from '@/pages/Home'
import { Placeholder } from '@/pages/Placeholder'

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Home />} />
        <Route path="explorer" element={<Explorer />} />
        <Route path="ask" element={<Ask />} />
        <Route path="evidence/:id?" element={<Evidence />} />
        <Route
          path="assess"
          element={
            <Placeholder
              title="Risk Assessment"
              phase={5}
              icon={Gauge}
              points={[
                'Pick one BOM line and a simulated as-of date inside the study window (2025-01-01 to 2026-09-30).',
                'A live step timeline: vector search, each Cypher query and its rows, supplier exposure profiles, evidence records.',
                'The gpt-5.2 report streams in, with citation chips linking to evidence and graph elements.',
                'A History tab reopens any past run with its full trace. These runs feed the evaluation.',
              ]}
            />
          }
        />
        {/* Run History is now a tab inside Risk Assessment. */}
        <Route path="runs" element={<Navigate to="/assess" replace />} />
        <Route path="*" element={<Placeholder title="Not found" icon={Gauge} points={['No page at this address.']} />} />
      </Route>
    </Routes>
  )
}
