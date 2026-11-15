const nf = new Intl.NumberFormat('en-GB')
export const fmt = (n: number | null | undefined) => (n == null ? '—' : nf.format(n))

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
/** "2025-03" -> "Mar 2025" */
export function monthLabel(ym: string, short = false): string {
  const [y, m] = ym.split('-')
  const name = MONTHS[Number(m) - 1] ?? m
  return short ? `${name} ${y.slice(2)}` : `${name} ${y}`
}

/** "2025-03-14" -> "14 Mar 2025" */
export function dateLabel(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${Number(d)} ${MONTHS[Number(m) - 1]} ${y}`
}

export function plural(n: number, one: string, many = `${one}s`) {
  return `${fmt(n)} ${n === 1 ? one : many}`
}
