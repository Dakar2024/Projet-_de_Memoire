import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import type { AskQuestionInput, Conversation } from '@/shared/api/contracts'
import { askQuestionFn, deleteConversationFn, getConversationFn, listConversationsFn } from './server'

export const conversationsQuery = queryOptions({
  queryKey: ['assistant', 'conversations'],
  queryFn: () => listConversationsFn(),
  staleTime: 30_000,
})

export const conversationQuery = (id: string) =>
  queryOptions({
    queryKey: ['assistant', 'conversation', id],
    queryFn: () => getConversationFn({ data: { id } }),
    // A thread only changes when this user asks a question, and the mutation refreshes it.
    staleTime: Infinity,
  })

/**
 * Sends a question. On success the thread and the sidebar are refetched before the mutation
 * settles, so the pending bubble is only removed once the stored answer is on screen.
 */
export function useAskQuestion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: AskQuestionInput) => askQuestionFn({ data: input }),
    onSuccess: async (result) => {
      if (!result.ok) return
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: conversationsQuery.queryKey }),
        queryClient.invalidateQueries({ queryKey: conversationQuery(result.value.conversationId).queryKey }),
      ])
    },
  })
}

export function useDeleteConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteConversationFn({ data: { id } }),
    onSuccess: (_, id) => {
      queryClient.setQueryData<Conversation | null>(conversationQuery(id).queryKey, null)
      return queryClient.invalidateQueries({ queryKey: conversationsQuery.queryKey })
    },
  })
}
