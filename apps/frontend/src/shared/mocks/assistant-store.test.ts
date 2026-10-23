import { describe, expect, it } from 'vitest'
import {
  cannedAnswer,
  conversationTitle,
  mockAsk,
  mockDeleteConversation,
  mockGetConversation,
  mockListConversations,
} from './assistant-store'

describe('cannedAnswer', () => {
  it('answers rs334 with both HBB alleles, in citation order', () => {
    const answer = cannedAnswer('Le variant rs334 de HBB est-il pathogène ?')
    expect(answer.status).toBe('answered')
    expect(answer.sources.map((s) => s.clinvarVariationId)).toEqual(['15333', '15175'])
    expect(answer.sources[0].stars).toBe(2)
  })

  it('routes counting questions out of scope before any variant rule', () => {
    const answer = cannedAnswer('Combien de variants pathogènes sur BRCA1 c.68_69del ?')
    expect(answer).toMatchObject({ status: 'out_of_scope', scopeReason: 'counting', sources: [] })
  })

  it('flags genes outside the 18-gene panel', () => {
    expect(cannedAnswer('CFTR F508del est-il pathogène ?').scopeReason).toBe('gene_out_of_panel')
  })

  it('falls back to the RAG "no document" answer', () => {
    expect(cannedAnswer('Bonjour')).toMatchObject({ status: 'not_in_sources', sources: [] })
  })
})

describe('conversationTitle', () => {
  it('keeps short questions and cuts long ones at 60 characters', () => {
    expect(conversationTitle('  rs334   HBB ? ')).toBe('rs334 HBB ?')
    const title = conversationTitle('a'.repeat(80))
    expect(title).toHaveLength(60)
    expect(title.endsWith('…')).toBe(true)
  })
})

describe('mock conversations', () => {
  it('creates, continues, isolates and deletes a conversation', () => {
    const first = mockAsk('owner', { question: 'rs334 ?' })
    if (!first.ok) throw new Error(first.code)
    const id = first.value.conversationId

    const next = mockAsk('owner', { conversationId: id, question: 'BRCA1 c.68_69del ?' })
    expect(next.ok && next.value.conversationId).toBe(id)

    const thread = mockGetConversation('owner', id)
    expect(thread.ok && thread.value.messages.map((m) => m.role)).toEqual(['user', 'assistant', 'user', 'assistant'])

    expect(mockGetConversation('intruder', id)).toEqual({ ok: false, code: 'not_found' })
    expect(mockAsk('intruder', { conversationId: id, question: 'x' })).toEqual({ ok: false, code: 'not_found' })

    expect(mockDeleteConversation('owner', id).ok).toBe(true)
    expect(mockListConversations('owner').map((c) => c.id)).not.toContain(id)
  })
})
