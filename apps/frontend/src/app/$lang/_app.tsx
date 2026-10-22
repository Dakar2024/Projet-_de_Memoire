import { Outlet, createFileRoute, redirect } from '@tanstack/react-router'
import { sessionQuery } from '@/features/auth/hooks'

/**
 * Signed-in area. The guard runs in beforeLoad, on the server during SSR and in the browser on
 * client navigation; only active accounts get a session from the backend, others are sent to sign in.
 * The requested page travels in `?redirect=` so the user lands back on it after signing in.
 */
export const Route = createFileRoute('/$lang/_app')({
  beforeLoad: async ({ context, params, location }) => {
    const user = await context.queryClient.ensureQueryData(sessionQuery)
    if (!user) throw redirect({ to: '/$lang/sign-in', params, search: { redirect: location.href } })
    return { user }
  },
  component: Outlet,
})
