import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { Mode } from './palette'

type Preference = Mode | 'system'
const KEY = 'scr-theme'

function readPref(): Preference {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

const media = () => window.matchMedia('(prefers-color-scheme: dark)')

const ThemeContext = createContext<{ mode: Mode; preference: Preference; setPreference: (p: Preference) => void }>({
  mode: 'light',
  preference: 'system',
  setPreference: () => {},
})

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPref] = useState<Preference>(readPref)
  const [systemDark, setSystemDark] = useState(() => media().matches)

  useEffect(() => {
    const m = media()
    const on = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [])

  const mode: Mode = preference === 'system' ? (systemDark ? 'dark' : 'light') : preference

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', mode === 'dark')
    root.dataset.theme = mode
    root.style.colorScheme = mode
  }, [mode])

  const setPreference = (p: Preference) => {
    setPref(p)
    try {
      if (p === 'system') localStorage.removeItem(KEY)
      else localStorage.setItem(KEY, p)
    } catch {
      /* storage unavailable; theme still applies for this session */
    }
  }

  return <ThemeContext.Provider value={{ mode, preference, setPreference }}>{children}</ThemeContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export const useTheme = () => useContext(ThemeContext)
