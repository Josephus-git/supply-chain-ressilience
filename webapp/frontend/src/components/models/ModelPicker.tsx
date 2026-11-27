/**
 * Model picker and arm badge. The picker lists the three evaluation arms; an arm
 * whose API key is missing in .env is shown but cannot be chosen.
 */
import { Cpu } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ARM_FALLBACK_LABEL, ARM_TONE, useModels, type ArmId } from '@/lib/models'
import { cn } from '@/lib/utils'

export function ArmBadge({ arm, model, className }: { arm: ArmId | null | undefined; model?: string | null; className?: string }) {
  if (!arm) return model ? <span className={cn('rounded border px-1.5 font-mono text-[10px] text-muted-foreground', className)}>{model}</span> : null
  return (
    <span className={cn('inline-flex items-center gap-1 rounded border px-1.5 text-[10px] font-medium', ARM_TONE[arm], className)} title={model ?? ARM_FALLBACK_LABEL[arm]}>
      {arm} <span className="font-normal">{ARM_FALLBACK_LABEL[arm]}</span>
    </span>
  )
}

export function ModelPicker({ value, onChange, disabled, compact }: {
  value: ArmId; onChange: (a: ArmId) => void; disabled?: boolean; compact?: boolean
}) {
  const models = useModels()
  const arms = models.data?.arms
  const current = arms?.find((a) => a.name === value)
  return (
    <div className="space-y-1">
      {!compact && <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><Cpu className="size-3.5" /> Model</div>}
      <Select value={value} onValueChange={(v) => onChange(v as ArmId)} disabled={disabled}>
        <SelectTrigger size="sm" className="min-w-52" aria-label="Model">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(arms ?? (['M1', 'M2', 'M3'] as ArmId[]).map((name) => ({ name, label: ARM_FALLBACK_LABEL[name], note: '', available: true, model: '' }))).map((a) => (
            <SelectItem key={a.name} value={a.name} disabled={!a.available}>
              <span className={cn('rounded border px-1 text-[10px] font-semibold', ARM_TONE[a.name])}>{a.name}</span>
              <span>{a.label}</span>
              {!a.available && <span className="text-[10px] text-muted-foreground">no API key</span>}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {!compact && current?.note && <p className="max-w-56 text-[10.5px] leading-snug text-muted-foreground">{current.note}</p>}
      {current && !current.available && <p className="text-[10.5px] text-red-600 dark:text-red-400">This model has no API key in .env.</p>}
    </div>
  )
}
