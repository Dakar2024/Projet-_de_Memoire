import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { Trans, useLingui } from '@lingui/react/macro'
import { msg } from '@lingui/core/macro'
import type { MessageDescriptor } from '@lingui/core'
import { LogOut, Monitor, Moon, MoreHorizontal, ShieldCheck, SquarePen, Sun, Trash2, X } from 'lucide-react'
import { useTheme } from 'next-themes'
import type { User } from '@/shared/api/contracts'
import { useSignOut } from '@/features/auth/hooks'
import { Logo } from '@/shared/components/brand/Logo'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { conversationsQuery, useDeleteConversation } from '../hooks'
import { groupByRecency, type RecencyGroup } from '../recency'

const GROUP_LABELS: Record<RecencyGroup, MessageDescriptor> = {
  today: msg`Aujourd'hui`,
  week: msg`7 derniers jours`,
  older: msg`Plus ancien`,
}

type AppSidebarProps = {
  user: User
  /** Drawer state under 1024 px; the sidebar is always visible above. */
  open: boolean
  onClose: () => void
}

export function AppSidebar({ user, open, onClose }: AppSidebarProps) {
  const { t, i18n } = useLingui()
  const { lang } = useParams({ from: '/$lang' })
  const { conversationId } = useParams({ strict: false })
  const navigate = useNavigate()
  const { data: conversations = [] } = useQuery(conversationsQuery)
  const remove = useDeleteConversation()
  const groups = groupByRecency(conversations, new Date())

  return (
    <>
      {open && (
        <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={onClose} aria-hidden="true" />
      )}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex w-[280px] flex-col border-r border-border bg-[var(--sidebar)] transition-transform lg:static lg:translate-x-0',
          open ? 'translate-x-0' : '-translate-x-full',
        )}
        aria-label={t`Conversations`}
      >
        <div className="flex items-center justify-between px-4 pb-2 pt-4">
          <Link to="/$lang/assistant" params={{ lang }} className="inline-flex min-h-11 items-center" aria-label={t`Nouvelle conversation`}>
            <Logo size={26} />
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex size-10 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted lg:hidden"
            aria-label={t`Fermer le menu`}
          >
            <X className="size-5" aria-hidden="true" />
          </button>
        </div>

        <div className="px-3 pb-3">
          <Link
            to="/$lang/assistant"
            params={{ lang }}
            className="flex min-h-11 items-center gap-2.5 rounded-xl border border-border bg-card px-3 text-sm font-medium transition-colors hover:border-primary/50"
          >
            <SquarePen className="size-4 text-primary" aria-hidden="true" />
            <Trans>Nouvelle conversation</Trans>
          </Link>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 pb-4" aria-label={t`Historique`}>
          {groups.length === 0 && (
            <p className="px-3 py-2 text-sm text-faint">
              <Trans>Vos conversations apparaîtront ici.</Trans>
            </p>
          )}
          {groups.map(({ group, items }) => (
            <section key={group} className="mt-3 first:mt-0">
              <h2 className="px-3 pb-1 text-xs font-medium text-faint">{i18n._(GROUP_LABELS[group])}</h2>
              <ul className="flex flex-col gap-0.5">
                {items.map((item) => {
                  const active = item.id === conversationId
                  return (
                    <li key={item.id} className="group relative">
                      <Link
                        to="/$lang/assistant/$conversationId"
                        params={{ lang, conversationId: item.id }}
                        aria-current={active ? 'page' : undefined}
                        className={cn(
                          'flex min-h-10 items-center rounded-lg py-2 pl-3 pr-10 text-sm transition-colors',
                          active ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:bg-muted/70 hover:text-foreground',
                        )}
                      >
                        <span className="truncate">{item.title}</span>
                      </Link>
                      <DropdownMenu>
                        <DropdownMenuTrigger
                          className="absolute right-1 top-1/2 inline-flex size-8 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity hover:bg-background focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100 max-lg:opacity-100"
                          aria-label={t`Actions pour « ${item.title} »`}
                        >
                          <MoreHorizontal className="size-4" aria-hidden="true" />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            variant="destructive"
                            disabled={remove.isPending}
                            onSelect={() =>
                              remove.mutate(item.id, {
                                onSuccess: () => {
                                  if (active) navigate({ to: '/$lang/assistant', params: { lang } })
                                },
                              })
                            }
                          >
                            <Trash2 aria-hidden="true" />
                            <Trans>Supprimer</Trans>
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </li>
                  )
                })}
              </ul>
            </section>
          ))}
        </nav>

        <AccountMenu user={user} lang={lang} />
      </aside>
    </>
  )
}

function initials(user: User): string {
  const source = user.fullName.trim() || user.email
  const parts = source.split(/[\s.@]+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase()
}

function AccountMenu({ user, lang }: { user: User; lang: string }) {
  const { t } = useLingui()
  const navigate = useNavigate()
  const signOut = useSignOut()
  const { theme, setTheme } = useTheme()

  return (
    <div className="border-t border-border p-3">
      <DropdownMenu>
        <DropdownMenuTrigger className="flex min-h-12 w-full items-center gap-3 rounded-xl px-2 text-left transition-colors hover:bg-muted data-[state=open]:bg-muted">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/12 text-xs font-semibold text-primary" aria-hidden="true">
            {initials(user)}
          </span>
          <span className="flex min-w-0 flex-col">
            <span className="truncate text-sm font-medium">{user.fullName || user.email}</span>
            <span className="truncate text-xs text-muted-foreground">{user.organization || user.email}</span>
          </span>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" className="w-[256px]">
          <DropdownMenuLabel className="truncate font-normal text-muted-foreground">{user.email}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuLabel className="text-xs font-medium text-faint">
            <Trans>Thème</Trans>
          </DropdownMenuLabel>
          <DropdownMenuRadioGroup value={theme ?? 'system'} onValueChange={setTheme}>
            <DropdownMenuRadioItem value="system">
              <Monitor aria-hidden="true" />
              <Trans>Système</Trans>
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="light">
              <Sun aria-hidden="true" />
              <Trans>Clair</Trans>
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="dark">
              <Moon aria-hidden="true" />
              <Trans>Sombre</Trans>
            </DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
          <DropdownMenuSeparator />
          {user.role === 'admin' && (
            <DropdownMenuItem onSelect={() => navigate({ to: '/$lang/admin/requests', params: { lang } })}>
              <ShieldCheck aria-hidden="true" />
              {t`Demandes d'accès`}
            </DropdownMenuItem>
          )}
          <DropdownMenuItem
            disabled={signOut.isPending}
            onSelect={() =>
              signOut.mutate(undefined, { onSuccess: () => navigate({ to: '/$lang/sign-in', params: { lang } }) })
            }
          >
            <LogOut aria-hidden="true" />
            {t`Se déconnecter`}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
