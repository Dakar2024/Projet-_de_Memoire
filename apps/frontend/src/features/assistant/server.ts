import { createServerFn } from '@tanstack/react-start'
import { getCookie } from '@tanstack/react-start/server'
import type { ApiErrorCode, AskQuestionResponse, Conversation, ConversationSummary } from '@/shared/api/contracts'
import { USE_MOCKS, backendFetch, errorCode } from '@/shared/api/backend'
import { mockUserForToken } from '@/shared/mocks/auth-store'
import {
  mockAsk,
  mockDeleteConversation,
  mockGetConversation,
  mockListConversations,
} from '@/shared/mocks/assistant-store'
import { MOCK_COOKIE } from '@/features/auth/server'
import { askQuestionSchema, conversationIdSchema } from './schemas'

/**
 * The browser talks to the Genomica backend only; the backend holds the RAG API key and the history.
 * Server functions keep the session cookie server-side, as for auth, and let route loaders run during SSR.
 */

export type AskResult = { ok: true; value: AskQuestionResponse } | { ok: false; code: ApiErrorCode }

/** Mock mode only: the signed-in user's id, or null once the session is gone. */
function mockUserId(): string | null {
  return mockUserForToken(getCookie(MOCK_COOKIE))?.id ?? null
}

export const askQuestionFn = createServerFn({ method: 'POST' })
  .inputValidator(askQuestionSchema)
  .handler(async ({ data }): Promise<AskResult> => {
    if (USE_MOCKS) {
      const userId = mockUserId()
      if (!userId) return { ok: false, code: 'unauthorized' }
      // Rough RAG latency, so the waiting state is visible during development.
      await new Promise((resolve) => setTimeout(resolve, 1400))
      return mockAsk(userId, data)
    }
    const response = await backendFetch('/api/assistant/questions', { method: 'POST', json: data })
    if (!response.ok) return { ok: false, code: await errorCode(response) }
    return { ok: true, value: (await response.json()) as AskQuestionResponse }
  })

export const listConversationsFn = createServerFn({ method: 'GET' }).handler(
  async (): Promise<ConversationSummary[]> => {
    if (USE_MOCKS) {
      const userId = mockUserId()
      return userId ? mockListConversations(userId) : []
    }
    const response = await backendFetch('/api/assistant/conversations', { method: 'GET' })
    if (!response.ok) throw new Error(`conversations: ${response.status}`)
    return ((await response.json()) as { items: ConversationSummary[] }).items
  },
)

/** Null when the conversation is missing or belongs to someone else (the backend answers 404 for both). */
export const getConversationFn = createServerFn({ method: 'GET' })
  .inputValidator(conversationIdSchema)
  .handler(async ({ data }): Promise<Conversation | null> => {
    if (USE_MOCKS) {
      const userId = mockUserId()
      const result = userId ? mockGetConversation(userId, data.id) : null
      return result?.ok ? result.value : null
    }
    const response = await backendFetch(`/api/assistant/conversations/${encodeURIComponent(data.id)}`, {
      method: 'GET',
    })
    if (response.status === 404) return null
    if (!response.ok) throw new Error(`conversation: ${response.status}`)
    return (await response.json()) as Conversation
  })

export const deleteConversationFn = createServerFn({ method: 'POST' })
  .inputValidator(conversationIdSchema)
  .handler(async ({ data }): Promise<void> => {
    if (USE_MOCKS) {
      const userId = mockUserId()
      if (userId) mockDeleteConversation(userId, data.id)
      return
    }
    const response = await backendFetch(`/api/assistant/conversations/${encodeURIComponent(data.id)}`, {
      method: 'DELETE',
    })
    if (!response.ok && response.status !== 404) throw new Error(`delete conversation: ${response.status}`)
  })
