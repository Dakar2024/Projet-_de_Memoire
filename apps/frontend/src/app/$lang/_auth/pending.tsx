import { createFileRoute } from '@tanstack/react-router'
import * as z from 'zod'
import { PendingStatus } from '@/features/auth/components/PendingStatus'

const searchSchema = z.object({
  reason: z.enum(['pending_email', 'pending_review']).catch('pending_email'),
})

export const Route = createFileRoute('/$lang/_auth/pending')({
  validateSearch: searchSchema,
  head: () => ({ meta: [{ title: 'Demande en cours · Genomica' }] }),
  component: PendingPage,
})

function PendingPage() {
  const { reason } = Route.useSearch()
  return <PendingStatus reason={reason} />
}
