import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { decideAccessRequestFn, listAccessRequestsFn } from './server'

export const accessRequestsQuery = queryOptions({
  queryKey: ['admin', 'access-requests'],
  queryFn: () => listAccessRequestsFn(),
  staleTime: 0,
})

export function useDecideAccessRequest() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: { id: string; decision: 'approve' | 'reject'; reason?: string }) =>
      decideAccessRequestFn({ data }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: accessRequestsQuery.queryKey }),
  })
}
