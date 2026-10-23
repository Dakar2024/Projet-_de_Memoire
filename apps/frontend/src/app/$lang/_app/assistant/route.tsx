import { Outlet, createFileRoute, useLocation } from '@tanstack/react-router'
import { useLingui } from '@lingui/react/macro'
import { Menu } from 'lucide-react'
import { useEffect, useState } from 'react'
import { AppSidebar } from '@/features/assistant/components/AppSidebar'
import { conversationsQuery } from '@/features/assistant/hooks'
import { Logo } from '@/shared/components/brand/Logo'

/** Assistant shell: conversation history on the left, the current thread on the right. */
export const Route = createFileRoute('/$lang/_app/assistant')({
  loader: ({ context }) => context.queryClient.ensureQueryData(conversationsQuery),
  component: AssistantLayout,
})

function AssistantLayout() {
  const { t } = useLingui()
  const { user } = Route.useRouteContext()
  const [menuOpen, setMenuOpen] = useState(false)
  const pathname = useLocation({ select: (location) => location.pathname })

  // The drawer closes on every navigation (new conversation, history item).
  useEffect(() => setMenuOpen(false), [pathname])

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <AppSidebar user={user} open={menuOpen} onClose={() => setMenuOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-border px-3 py-2 lg:hidden">
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            className="inline-flex size-11 items-center justify-center rounded-lg hover:bg-muted"
            aria-label={t`Ouvrir l'historique`}
            aria-expanded={menuOpen}
          >
            <Menu className="size-5" aria-hidden="true" />
          </button>
          <Logo size={24} />
        </header>
        <Outlet />
      </div>
    </div>
  )
}
