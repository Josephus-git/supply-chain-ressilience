import { Gauge } from 'lucide-react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import Ask from '@/pages/Ask'
import Assess from '@/pages/Assess'
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
        <Route path="assess" element={<Assess />} />
        {/* Run History is now a tab inside Risk Assessment. */}
        <Route path="runs" element={<Navigate to="/assess" replace />} />
        <Route path="*" element={<Placeholder title="Not found" icon={Gauge} points={['No page at this address.']} />} />
      </Route>
    </Routes>
  )
}
