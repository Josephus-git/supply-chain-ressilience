/**
 * Model arms (EVALUATION_PLAN §2.11): M1 OpenAI gpt-5.2, M2 DeepSeek V4.1 Flash,
 * M3 Claude Sonnet 5.5. The picker's choice is remembered per browser and sent
 * with each Risk Assessment and Ask the Graph request; every run records it.
 */
import { useQuery } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { getJson } from './api'

export type ArmId = 'M1' | 'M2' | 'M3'

export interface ArmInfo {
  name: ArmId
  provider: string
  model: string
  label: string
  note: string
  available: boolean
}

export const useModels = () =>
  useQuery({
    queryKey: ['models'],
    queryFn: ({ signal }) => getJson<{ default: ArmId; arms: ArmInfo[] }>('/models', {}, signal),
    staleTime: 5 * 60_000,
  })

const KEY = 'model-arm'
const isArm = (v: unknown): v is ArmId => v === 'M1' || v === 'M2' || v === 'M3'

/** The chosen arm, remembered in this browser (falls back to M1 when storage is unavailable). */
export function useArm(): [ArmId, (a: ArmId) => void] {
  const [arm, setArmState] = useState<ArmId>(() => {
    try {
      const v = localStorage.getItem(KEY)
      return isArm(v) ? v : 'M1'
    } catch {
      return 'M1'
    }
  })
  const setArm = useCallback((a: ArmId) => {
    setArmState(a)
    try {
      localStorage.setItem(KEY, a)
    } catch {
      /* storage blocked: the choice lasts for this page only */
    }
  }, [])
  return [arm, setArm]
}

/** Arm colours, shared by the picker, badges and the history page. */
export const ARM_TONE: Record<ArmId, string> = {
  M1: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300',
  M2: 'border-sky-500/40 bg-sky-500/10 text-sky-800 dark:text-sky-300',
  M3: 'border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-300',
}

export const ARM_FALLBACK_LABEL: Record<ArmId, string> = {
  M1: 'OpenAI gpt-5.2',
  M2: 'DeepSeek V4.1 Flash',
  M3: 'Claude Sonnet 5.5',
}
