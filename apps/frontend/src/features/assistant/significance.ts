/**
 * Maps a ClinVar significance label to one of the clinical color tones (`--sig-*`).
 * Composite labels keep their first, strongest term ("Pathogenic/Likely pathogenic" → p);
 * anything ClinVar marks as conflicting wins over the rest, since it must never look settled.
 */
export type SignificanceTone = 'p' | 'lp' | 'vus' | 'lb' | 'b' | 'conf' | 'other'

const PREFIXES: [string, SignificanceTone][] = [
  ['likely pathogenic', 'lp'],
  ['pathogenic', 'p'],
  ['uncertain significance', 'vus'],
  ['likely benign', 'lb'],
  ['benign', 'b'],
]

export function significanceTone(label: string | null): SignificanceTone {
  if (!label) return 'other'
  const value = label.trim().toLowerCase()
  if (value.includes('conflicting')) return 'conf'
  return PREFIXES.find(([prefix]) => value.startsWith(prefix))?.[1] ?? 'other'
}
