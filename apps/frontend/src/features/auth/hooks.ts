import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { getSessionFn, signInFn, signOutFn, signUpFn, forgotPasswordFn } from './server'
import type { SignInInput, SignUpInput } from '@/shared/api/contracts'

export const sessionQuery = queryOptions({
  queryKey: ['auth', 'session'],
  queryFn: () => getSessionFn(),
  staleTime: 60_000,
})

export function useSignIn() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: SignInInput) => signInFn({ data }),
    onSuccess: (result) => {
      if (result.ok) queryClient.invalidateQueries({ queryKey: sessionQuery.queryKey })
    },
  })
}

export function useSignUp() {
  return useMutation({ mutationFn: (data: SignUpInput) => signUpFn({ data }) })
}

export function useForgotPassword() {
  return useMutation({ mutationFn: (email: string) => forgotPasswordFn({ data: { email } }) })
}

export function useSignOut() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => signOutFn(),
    onSuccess: () => queryClient.setQueryData(sessionQuery.queryKey, null),
  })
}
