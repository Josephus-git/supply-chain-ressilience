/**
 * "Browse products": the 43 Product nodes (customs lines, not a parts
 * breakdown) grouped into hand-reviewed categories, with shipment and supplier
 * counts up to the chosen date. Add a product with one click; anything can
 * still be typed freely in the list.
 */
import {
  ArrowLeft, BrushCleaning, Cable, Check, CircleHelp, Fan, Lamp, Plus, Wind, Wrench, type LucideIcon,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useCatalogue, type CatalogueProduct } from '@/lib/assess'
import { dateLabel, fmt, plural } from '@/lib/format'
import { cn } from '@/lib/utils'

export const CATEGORY_ICON: Record<string, LucideIcon> = {
  floorcare: BrushCleaning,
  hair_care: Wind,
  air_treatment: Fan,
  lighting: Lamp,
  spares: Wrench,
  electrical: Cable,
  other: CircleHelp,
}

function ProductRow({ p, added, full, onAdd }: { p: CatalogueProduct; added: boolean; full: boolean; onAdd: () => void }) {
  return (
    <div className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-muted/50">
      <div className="min-w-0 flex-1">
        <div className="text-sm leading-snug">{p.name}</div>
        <div className="line-clamp-1 text-[11px] text-muted-foreground" title={p.description}>{p.description}</div>
        <div className="mt-0.5 flex flex-wrap gap-x-2 text-[10.5px] text-muted-foreground tabular">
          <span className="font-mono">HS {String(p.hs_code ?? '').padStart(6, '0')}</span>
          <span>{plural(p.shipments, 'shipment')}</span>
          <span title={p.companies.join(', ')}>{p.companies.length} supplier{p.companies.length === 1 ? '' : 's'}</span>
        </div>
      </div>
      <Button
        type="button" size="sm" variant={added ? 'secondary' : 'outline'} className="h-7 shrink-0 text-xs"
        disabled={added || full} onClick={onAdd}
      >
        {added ? <><Check className="size-3" /> Added</> : <><Plus className="size-3" /> Add</>}
      </Button>
    </div>
  )
}

export function CataloguePanel({
  asOf, addedIds, full, onAdd,
}: {
  asOf: string | null
  addedIds: Set<string>
  full: boolean
  onAdd: (p: CatalogueProduct) => void
}) {
  const cat = useCatalogue(asOf)
  const [open, setOpen] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const products = useMemo(() => cat.data?.products ?? [], [cat.data])
  const matches = useMemo(() => {
    const t = q.trim().toLowerCase()
    if (t.length < 2) return []
    return products.filter((p) => `${p.name} ${p.description} ${p.hs_code ?? ''} ${p.companies.join(' ')}`.toLowerCase().includes(t))
  }, [q, products])
  const category = cat.data?.categories.find((c) => c.key === open)

  return (
    <div className="flex h-full min-h-0 flex-col rounded-lg border bg-card">
      <div className="space-y-0.5 border-b px-3 py-2.5">
        <div className="flex items-center gap-2 text-sm font-medium">
          Browse products
          {cat.data?.status?.startsWith('DRAFT') && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1 text-[10px] font-normal text-amber-800 dark:text-amber-300">draft categories</span>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">{cat.data.status} {cat.data.basis}</TooltipContent>
            </Tooltip>
          )}
        </div>
        <p className="text-[11px] leading-snug text-muted-foreground">
          {products.length || 43} products from customs lines, not a parts breakdown. Counts up to {asOf ? dateLabel(asOf) : 'the end of the study window'}.
        </p>
      </div>

      <Command shouldFilter={false} className="h-auto! flex-none rounded-none! bg-transparent p-0">
        <div className="border-b p-2">
          <CommandInput value={q} onValueChange={setQ} placeholder="Search all products…" />
        </div>
        {q.trim().length >= 2 && (
          <CommandList className="max-h-80">
            <CommandEmpty>No product matches. You can still type it in the list.</CommandEmpty>
            <CommandGroup>
              {matches.map((p) => (
                <CommandItem
                  key={p.id} value={p.id} disabled={addedIds.has(p.id) || full}
                  onSelect={() => onAdd(p)}
                  className="flex items-start gap-2"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm">{p.name}</div>
                    <div className="line-clamp-1 text-[11px] text-muted-foreground">{p.description}</div>
                  </div>
                  <span className="text-[10.5px] text-muted-foreground tabular">{fmt(p.shipments)}</span>
                  {addedIds.has(p.id) ? <Check className="size-3.5" /> : <Plus className="size-3.5" />}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        )}
      </Command>

      {q.trim().length < 2 && (
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {cat.isPending && <div className="grid grid-cols-2 gap-2">{[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-20" />)}</div>}
          {cat.isError && <p className="p-2 text-xs text-muted-foreground">The catalogue needs Neo4j: {String(cat.error.message)}</p>}
          {cat.data && !category && (
            <div className="grid grid-cols-2 gap-2">
              {cat.data.categories.map((c) => {
                const Icon = CATEGORY_ICON[c.key] ?? CircleHelp
                return (
                  <button
                    key={c.key} type="button" onClick={() => setOpen(c.key)}
                    className="group rounded-md border bg-background p-2.5 text-left transition-colors hover:border-primary/40 hover:bg-muted/40"
                  >
                    <div className="flex items-center gap-2">
                      <span className="grid size-7 place-items-center rounded-md bg-muted text-foreground/80 group-hover:bg-primary/10"><Icon className="size-4" /></span>
                      <span className="text-sm font-medium leading-tight">{c.label}</span>
                    </div>
                    <div className="mt-1.5 text-[11px] text-muted-foreground tabular">
                      {c.products} product{c.products === 1 ? '' : 's'} · {c.companies} supplier{c.companies === 1 ? '' : 's'}
                    </div>
                  </button>
                )
              })}
            </div>
          )}
          {category && (
            <div className="space-y-1">
              <button type="button" onClick={() => setOpen(null)} className="flex items-center gap-1 px-1 text-xs text-muted-foreground hover:text-foreground">
                <ArrowLeft className="size-3.5" /> All categories
              </button>
              <div className="px-2 pt-1 pb-1">
                <div className="text-sm font-medium">{category.label}</div>
                <div className="text-[11px] text-muted-foreground">{category.description}</div>
              </div>
              {products.filter((p) => p.category === category.key).map((p) => (
                <ProductRow key={p.id} p={p} added={addedIds.has(p.id)} full={full} onAdd={() => onAdd(p)} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** Autocomplete for the add-item box: the typed text first, then catalogue matches. */
export function useProductMatches(asOf: string | null, text: string, limit = 6): CatalogueProduct[] {
  const cat = useCatalogue(asOf)
  return useMemo(() => {
    const t = text.trim().toLowerCase()
    if (t.length < 2) return []
    return (cat.data?.products ?? []).filter((p) => `${p.name} ${p.description}`.toLowerCase().includes(t)).slice(0, limit)
  }, [cat.data, text, limit])
}

export function SourceBadge({ source }: { source: 'catalogue' | 'typed' }) {
  return (
    <span
      className={cn(
        'rounded border px-1 text-[10px]',
        source === 'catalogue' ? 'border-sky-500/40 bg-sky-500/10 text-sky-800 dark:text-sky-300' : 'text-muted-foreground',
      )}
    >
      {source}
    </span>
  )
}
