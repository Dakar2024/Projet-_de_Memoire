import { Outlet, createFileRoute, redirect } from '@tanstack/react-router'
import { sessionQuery } from '@/features/auth/hooks'

/**
 * Signed-in area. The guard runs in beforeLoad, on the server during SSR and in the browser on
 * client navigation. Active and onboarding accounts get a session from the backend; only active ones
 * enter here, the others are sent to sign in or to finish their profile.
 * The requested page travels in `?redirect=` so the user lands back on it after signing in.
 */
export const Route = createFileRoute('/$lang/_app')({
  beforeLoad: async ({ context, params, location }) => {
    const user = await context.queryClient.ensureQueryData(sessionQuery)
    if (!user) throw redirect({ to: '/$lang/sign-in', params, search: { redirect: location.href } })
    // Signed in but profile not completed: the backend refuses every other route (403).
    if (user.status !== 'active') throw redirect({ to: '/$lang/onboarding', params })
    return { user }
  },
  component: Outlet,
})
