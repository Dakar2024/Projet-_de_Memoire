import { useLingui } from '@lingui/react/macro'
import type { CSSProperties } from 'react'

/** Coding strand of HBB, c.1 to c.24: c.20 is the A of codon 7, mutated to T in haemoglobin S. */
const HBB_CODING = 'ATGGTGCATCTGACTCCTGAGGAG'
const PAIR: Record<string, string> = { A: 'T', T: 'A', G: 'C', C: 'G' }
const HBS_INDEX = 19

/**
 * Animated double helix built from real sequence. Hovering pauses it and reveals the base pairs;
 * each rung shows its position and hydrogen-bond count. Pure CSS animation (see styles.css),
 * stopped by `prefers-reduced-motion`.
 */
export function DnaHelix() {
  const { t } = useLingui()

  return (
    <div
      className="dna-helix relative flex flex-col items-center gap-2 py-3"
      role="img"
      aria-label={t`Double hélice d'ADN animée : séquence codante du gène HBB, positions c.1 à c.24. Survolez-la pour lire les paires de bases.`}
    >
      {HBB_CODING.split('').map((base, i) => {
        const pair = PAIR[base]
        const bonds = base === 'G' || base === 'C' ? 3 : 2
        const hot = i === HBS_INDEX
        return (
          <div
            key={i}
            className="dna-rung"
            data-hot={hot}
            style={{ '--i': i } as CSSProperties}
            aria-hidden="true"
          >
            <span className="dna-bar" />
            <span className="dna-a">{base}</span>
            <span className="dna-b">{pair}</span>
            <span className="dna-tip">
              {hot ? 'c.20 A>T · HbS (p.Glu7Val)' : t`c.${i + 1} · ${base}–${pair} · ${bonds} liaisons H`}
            </span>
          </div>
        )
      })}
    </div>
  )
}

const DNA_GLYPH_PATHS = [
  'M2 15c6.667-6 13.333 0 20-6',
  'M9 22c1.798-1.998 2.518-3.995 2.807-5.993',
  'M15 2c-1.798 1.998-2.518 3.995-2.807 5.993',
  'm17 6-2.5-2.5',
  'm7 18 2.5 2.5',
  'm6.5 12.5 1 1',
  'm16.5 10.5 1 1',
]

/** Small decorative DNA glyph that drifts and reacts to hover; placed in margins, never behind text. */
export function FloatingDna({ size, style }: { size: number; style: CSSProperties }) {
  return (
    <svg
      className="dna-float"
      style={style}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      aria-hidden="true"
    >
      {DNA_GLYPH_PATHS.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  )
}
