import { describe, expect, it } from 'vitest'
import { significanceTone } from './significance'

describe('significanceTone', () => {
  it.each([
    ['Pathogenic', 'p'],
    ['Likely pathogenic', 'lp'],
    ['Pathogenic/Likely pathogenic', 'p'],
    ['Uncertain significance', 'vus'],
    ['Likely benign', 'lb'],
    ['Benign/Likely benign', 'b'],
    ['Conflicting classifications of pathogenicity', 'conf'],
    ['risk factor', 'other'],
    [null, 'other'],
  ] as const)('%s → %s', (label, tone) => {
    expect(significanceTone(label)).toBe(tone)
  })
})
