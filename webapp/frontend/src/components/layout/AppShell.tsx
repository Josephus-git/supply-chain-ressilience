import {
  BookOpenText, Gauge, Home, Menu, MessagesSquare, Monitor, Moon, Network, Sun,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useHealth } from '@/lib/api'
import { useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'
import { ErrorBoundary } from './ErrorBoundary'

export const NAV = [
  { to: '/', label: 'Home', icon: Home, end: true },
  { to: '/explorer', label: 'Graph Explorer', icon: Network },
  { to: '/ask', label: 'Ask the Graph', icon: MessagesSquare },
  { to: '/evidence', label: 'Evidence Library', icon: BookOpenText, phase: 4 },
  { to: '/assess', label: 'Risk Assessment', icon: Gauge, phase: 5 },
]

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-0.5">
      {NAV.map(({ to, label, icon: Icon, end, phase }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'group flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors',
              isActive
                ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
                : 'text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground',
            )
          }
        >
          <Icon className="size-4 shrink-0" />
          <span className="flex-1 truncate">{label}</span>
          {phase && (
            <span className="rounded border border-sidebar-border px-1 text-[10px] text-muted-foreground">
              soon
            </span>
          )}
        </NavLink>
      ))}
    </nav>
  )
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-2.5">
      <div className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
        <Network className="size-4" />
      </div>
      <div className="leading-tight">
        <div className="text-sm font-semibold">Supply-chain risk</div>
        <div className="text-xs text-muted-foreground">Dyson case study</div>
      </div>
    </div>
  )
}

function HealthDot() {
  const { data, isError, isPending } = useHealth()
  const state = isPending ? 'checking' : isError ? 'down' : 'ok'
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex items-center gap-2 rounded-md px-2 py-1 text-xs text-muted-foreground">
          <span
            className={cn(
              'size-2 rounded-full',
              state === 'ok' && 'bg-emerald-500',
              state === 'down' && 'bg-red-500',
              state === 'checking' && 'animate-pulse bg-amber-400',
            )}
          />
          <span className="hidden sm:inline">
            {state === 'ok' ? 'Neo4j connected' : state === 'down' ? 'Backend unreachable' : 'Connecting…'}
          </span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs">
        {data ? (
          <div className="space-y-0.5">
            <div>Neo4j: {data.neo4j} (read-only)</div>
            <div>Evidence: {data.evidence_records} records · engine {data.engine_version}</div>
            <div className="font-mono text-[10px] opacity-80">{data.evidence_snapshot_id}</div>
          </div>
        ) : isError ? (
          'Start the backend: .venv/bin/uvicorn webapp.backend.main:app --port 8000'
        ) : (
          'Checking /api/health'
        )}
      </TooltipContent>
    </Tooltip>
  )
}

function ThemeMenu() {
  const { mode, preference, setPreference } = useTheme()
  const Icon = mode === 'dark' ? Moon : Sun
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Theme">
          <Icon className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup value={preference} onValueChange={(v) => setPreference(v as typeof preference)}>
          <DropdownMenuRadioItem value="light"><Sun className="size-4" /> Light</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark"><Moon className="size-4" /> Dark</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system"><Monitor className="size-4" /> System</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function AppShell() {
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  const current = NAV.find((n) => (n.end ? pathname === n.to : pathname.startsWith(n.to)))

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <aside className="hidden w-60 shrink-0 flex-col gap-6 border-r bg-sidebar py-4 md:flex">
        <Brand />
        <div className="px-2">
          <NavItems />
        </div>
        <div className="mt-auto px-4 text-[11px] leading-relaxed text-muted-foreground">
          KG + LLM decision support for supplier risk explanation.
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="md:hidden" aria-label="Menu">
                <Menu className="size-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-64 bg-sidebar p-4">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <div className="flex flex-col gap-6 pt-2">
                <Brand />
                <NavItems onNavigate={() => setOpen(false)} />
              </div>
            </SheetContent>
          </Sheet>
          <h1 className="truncate text-sm font-medium">{current?.label}</h1>
          <div className="ml-auto flex items-center gap-1">
            <HealthDot />
            <ThemeMenu />
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">
          <ErrorBoundary key={pathname} label="This page">
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  )
}

export function PageContainer({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('mx-auto w-full max-w-[1400px] px-4 py-6 md:px-6', className)}>{children}</div>
}
