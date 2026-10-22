import { Outlet, createFileRoute, notFound } from '@tanstack/react-router'
import { SUPPORTED_LOCALES, type Locale } from '@/lib/i18n-utils'

/** Parent of every page: rejects unknown language prefixes instead of rendering them as French. */
export const Route = createFileRoute('/$lang')({
  beforeLoad: ({ params }) => {
    if (!SUPPORTED_LOCALES.includes(params.lang as Locale)) throw notFound()
  },
  component: Outlet,
})
