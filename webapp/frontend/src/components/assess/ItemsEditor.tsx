/**
 * The numbered parts list (up to 20 items). Items can be typed (or pasted
 * from a spreadsheet, one per line) or picked from the catalogue; each keeps
 * its `source` for the evaluation.
 */
import { Plus, X } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Command, CommandGroup, CommandItem, CommandList } from '@/components/ui/command'
import { MAX_ITEMS, type Item } from '@/lib/assess'
import { plural } from '@/lib/format'
import { SourceBadge, useProductMatches } from './Catalogue'

export function ItemsEditor({
  items, setItems, asOf, disabled,
}: {
  items: Item[]
  setItems: (f: (items: Item[]) => Item[]) => void
  asOf: string | null
  disabled?: boolean
}) {
  const [text, setText] = useState('')
  const matches = useProductMatches(asOf, text)
  const full = items.length >= MAX_ITEMS

  const addTyped = (lines: string[]) => {
    const clean = lines.map((l) => l.replace(/^\s*\d+[.)]\s*/, '').split('\t')[0].trim()).filter(Boolean)
    if (!clean.length) return
    setItems((xs) => [...xs, ...clean.map((t) => ({ text: t.slice(0, 200), source: 'typed' as const, product_id: null }))].slice(0, MAX_ITEMS))
    setText('')
  }

  return (
    <div className="space-y-2">
      <ol className="space-y-1">
        {items.map((it, i) => (
          <li key={i} className="group flex items-center gap-2 rounded-md border bg-background px-2 py-1">
            <span className="w-5 text-right text-xs text-muted-foreground tabular">{i + 1}.</span>
            <input
              value={it.text}
              disabled={disabled}
              maxLength={200}
              onChange={(e) => {
                const v = e.target.value
                // Editing a catalogue name makes it a typed item.
                setItems((xs) => xs.map((x, j) => (j === i ? { text: v, source: 'typed', product_id: null } : x)))
              }}
              className="min-w-0 flex-1 bg-transparent py-0.5 text-sm outline-none"
              aria-label={`Item ${i + 1}`}
            />
            {it.product_id && <span className="font-mono text-[10px] text-muted-foreground">{it.product_id}</span>}
            <SourceBadge source={it.source} />
            <Button
              type="button" variant="ghost" size="icon" className="size-6 opacity-50 group-hover:opacity-100"
              disabled={disabled} aria-label={`Remove item ${i + 1}`}
              onClick={() => setItems((xs) => xs.filter((_, j) => j !== i))}
            >
              <X className="size-3.5" />
            </Button>
          </li>
        ))}
      </ol>

      {!full && (
        <Command shouldFilter={false} className="h-auto! overflow-visible rounded-md! border bg-background p-0">
          <div className="flex items-center gap-2 px-2">
            <span className="w-5 text-right text-xs text-muted-foreground tabular">{items.length + 1}.</span>
            <input
              value={text}
              disabled={disabled}
              onChange={(e) => setText(e.target.value)}
              onPaste={(e) => {
                const pasted = e.clipboardData.getData('text')
                if (pasted.includes('\n')) {
                  e.preventDefault()
                  addTyped(pasted.split(/\r?\n/))
                }
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && text.trim() && matches.length === 0) {
                  e.preventDefault()
                  addTyped([text])
                }
              }}
              placeholder={items.length ? 'Add another item…' : 'Type an item, e.g. "hair dryer motor", or paste a list'}
              className="h-9 min-w-0 flex-1 bg-transparent text-sm outline-none"
              aria-label="Add an item"
            />
            {text.trim() && matches.length === 0 && (
              <Button type="button" size="sm" variant="ghost" className="h-7 text-xs" onClick={() => addTyped([text])}>
                <Plus className="size-3" /> Add
              </Button>
            )}
          </div>
          {matches.length > 0 && (
            <CommandList className="border-t">
              <CommandGroup>
                <CommandItem value="__typed__" onSelect={() => addTyped([text])}>
                  <Plus className="size-3.5" /> Add “{text.trim()}” as typed
                </CommandItem>
                {matches.map((p) => (
                  <CommandItem
                    key={p.id} value={p.id}
                    disabled={items.some((x) => x.product_id === p.id)}
                    onSelect={() => {
                      setItems((xs) => [...xs, { text: p.name, source: 'catalogue' as const, product_id: p.id }].slice(0, MAX_ITEMS))
                      setText('')
                    }}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-sm">{p.name} <span className="text-[10px] text-sky-700 dark:text-sky-300">catalogue</span></div>
                      <div className="line-clamp-1 text-[11px] text-muted-foreground">{p.description}</div>
                    </div>
                    <span className="text-right text-[10.5px] text-muted-foreground tabular">
                      <span className="block font-mono">HS {String(p.hs_code ?? '').padStart(6, '0')}</span>
                      {plural(p.shipments, 'shipment')}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          )}
        </Command>
      )}
      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span>Enter adds the item. Paste several lines to add them all.</span>
        <span className={full ? 'font-medium text-amber-700 dark:text-amber-300' : ''}>{items.length} / {MAX_ITEMS}</span>
      </div>
    </div>
  )
}
