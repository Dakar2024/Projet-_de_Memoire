import { describe, expect, it } from 'vitest'
import { groupByRecency } from './recency'

const at = (iso: string) => ({ id: iso, title: iso, updatedAt: new Date(iso).toISOString() })

describe('groupByRecency', () => {
  const now = new Date(2026, 9, 22, 15, 0)

  it('splits from local midnight and drops empty groups', () => {
    const groups = groupByRecency(
      [at('2026-10-22T08:00:00'), at('2026-10-21T23:59:00'), at('2026-10-16T00:00:00'), at('2026-10-15T23:00:00')],
      now,
    )
    expect(groups.map((g) => [g.group, g.items.length])).toEqual([
      ['today', 1],
      ['week', 2],
      ['older', 1],
    ])
  })

  it('returns nothing for an empty history', () => {
    expect(groupByRecency([], now)).toEqual([])
  })
})
