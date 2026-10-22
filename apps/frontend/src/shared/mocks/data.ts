import type { PanelsResponse } from '@/shared/api/contracts'

/**
 * Figures read from gold/analytique on 2026-10-22 (archive 2026-10), so the mock never shows invented numbers.
 * Replaced by GET /api/panels once the backend exists.
 */
export const PANELS_FIXTURE: PanelsResponse = {
  archive: '2026-10',
  variantCount: 97192,
  diseaseCount: 442,
  phenotypeCount: 968,
  panels: [
    {
      id: 'brca',
      genes: ['BRCA1', 'BRCA2', 'TP53', 'PALB2', 'PTEN', 'CDH1', 'STK11', 'ATM', 'CHEK2', 'BARD1', 'RAD51C', 'RAD51D'],
      variantCount: 93615,
    },
    {
      id: 'sickle',
      genes: ['HBB', 'BCL11A', 'HBS1L', 'MYB', 'KLF1', 'G6PD'],
      variantCount: 3577,
    },
  ],
}
