import type { ConversationSummary } from '@/shared/api/contracts'

export type RecencyGroup = 'today' | 'week' | 'older'

const DAY_MS = 24 * 60 * 60 * 1000

/**
 * Splits conversations (already sorted, most recent first) into sidebar sections.
 * Days are counted from local midnight, so "today" matches what the user sees on their clock.
 */
export function groupByRecency(
  conversations: ConversationSummary[],
  now: Date,
): { group: RecencyGroup; items: ConversationSummary[] }[] {
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const groups: Record<RecencyGroup, ConversationSummary[]> = { today: [], week: [], older: [] }
  for (const conversation of conversations) {
    const at = new Date(conversation.updatedAt).getTime()
    const group: RecencyGroup = at >= midnight ? 'today' : at >= midnight - 6 * DAY_MS ? 'week' : 'older'
    groups[group].push(conversation)
  }
  return (['today', 'week', 'older'] as const)
    .map((group) => ({ group, items: groups[group] }))
    .filter((g) => g.items.length > 0)
}
