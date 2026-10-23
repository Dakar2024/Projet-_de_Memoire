import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  completeOnboardingFn,
  forgotPasswordFn,
  getSessionFn,
  resendVerificationFn,
  resetPasswordFn,
  signInFn,
  signOutFn,
  signUpFn,
  verifyEmailFn,
} from './server'
import type { OnboardingInput, SignInInput, SignUpInput } from '@/shared/api/contracts'

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

export function useResendVerification() {
  return useMutation({ mutationFn: (email: string) => resendVerificationFn({ data: { email } }) })
}

export function useVerifyEmail() {
  return useMutation({ mutationFn: (token: string) => verifyEmailFn({ data: { token } }) })
}

export function useResetPassword() {
  return useMutation({
    mutationFn: (data: { token: string; password: string }) => resetPasswordFn({ data }),
  })
}

/** On success the session is refreshed: still signed in when activated at once, signed out otherwise. */
export function useCompleteOnboarding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: OnboardingInput) => completeOnboardingFn({ data }),
    onSuccess: (result) => {
      if (!result.ok) return
      queryClient.setQueryData(sessionQuery.queryKey, result.user.status === 'active' ? result.user : null)
    },
  })
}
