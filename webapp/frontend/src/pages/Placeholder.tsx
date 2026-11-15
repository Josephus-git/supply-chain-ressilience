import type { LucideIcon } from 'lucide-react'
import { PageContainer } from '@/components/layout/AppShell'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function Placeholder({
  title, phase, icon: Icon, points,
}: { title: string; phase: number; icon: LucideIcon; points: string[] }) {
  return (
    <PageContainer className="max-w-3xl">
      <Card>
        <CardHeader>
          <div className="mb-2 grid size-10 place-items-center rounded-lg bg-muted">
            <Icon className="size-5 text-muted-foreground" />
          </div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>Arrives in phase {phase} of the web app plan.</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground">
            {points.map((p) => <li key={p}>{p}</li>)}
          </ul>
        </CardContent>
      </Card>
    </PageContainer>
  )
}
