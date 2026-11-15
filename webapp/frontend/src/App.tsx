import { BookOpenText, Gauge, History, MessagesSquare } from 'lucide-react'
import { Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import Explorer from '@/pages/Explorer'
import Home from '@/pages/Home'
import { Placeholder } from '@/pages/Placeholder'

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Home />} />
        <Route path="explorer" element={<Explorer />} />
        <Route
          path="assess"
          element={
            <Placeholder
              title="Risk Assessment"
              phase={3}
              icon={Gauge}
              points={[
                'Pick a BOM line and a simulated as-of date inside the study window (2025-01-01 to 2026-09-30).',
                'A live step timeline: vector search, each Cypher query and its rows, supplier exposure profiles, evidence records.',
                'The gpt-5.2 report streams in, with citation chips linking to evidence and graph elements.',
              ]}
            />
          }
        />
        <Route
          path="evidence"
          element={
            <Placeholder
              title="Evidence Library"
              phase={4}
              icon={BookOpenText}
              points={['Browse and filter the 109 evidence records by risk type, country and date.']}
            />
          }
        />
        <Route
          path="runs"
          element={
            <Placeholder
              title="Run History"
              phase={4}
              icon={History}
              points={['Reopen any past assessment with its full trace. These runs feed the evaluation.']}
            />
          }
        />
        <Route
          path="ask"
          element={
            <Placeholder
              title="Ask the Graph"
              phase={5}
              icon={MessagesSquare}
              points={['Natural-language Q&A over the KG, showing the generated Cypher and its rows before the answer. Read-only.']}
            />
          }
        />
        <Route path="*" element={<Placeholder title="Not found" phase={0} icon={Gauge} points={['No page at this address.']} />} />
      </Route>
    </Routes>
  )
}
