import { createFileRoute, notFound } from '@tanstack/react-router'
import { useSuspenseQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { ApiErrorCode, PanelId } from '@/shared/api/contracts'
import { AssistantFooter } from '@/features/assistant/components/AssistantFooter'
import { Composer } from '@/features/assistant/components/Composer'
import { Thread } from '@/features/assistant/components/Thread'
import { conversationQuery, useAskQuestion } from '@/features/assistant/hooks'

export const Route = createFileRoute('/$lang/_app/assistant/$conversationId')({
  loader: async ({ context, params }) => {
    const conversation = await context.queryClient.ensureQueryData(conversationQuery(params.conversationId))
    // Missing and foreign conversations look the same: the backend answers 404 for both.
    if (!conversation) throw notFound()
    return { title: conversation.title }
  },
  head: ({ loaderData }) => ({ meta: [{ title: `${loaderData?.title ?? 'Assistant'} · Genomica` }] }),
  component: ConversationPage,
})

function ConversationPage() {
  const { conversationId } = Route.useParams()
  const { data: conversation } = useSuspenseQuery(conversationQuery(conversationId))
  const ask = useAskQuestion()
  const [failed, setFailed] = useState<{ question: string; panel?: PanelId; code: ApiErrorCode } | null>(null)

  async function send(question: string, panel: PanelId | undefined) {
    setFailed(null)
    const result = await ask.mutateAsync({ conversationId, question, panel }).catch(() => null)
    if (!result?.ok) setFailed({ question, panel, code: result?.code ?? 'internal' })
  }

  // Deleted from another tab while open: the loader's notFound covers the next visit.
  if (!conversation) return null

  return (
    <>
      <main className="flex-1 overflow-y-auto">
        <Thread
          messages={conversation.messages}
          pending={ask.isPending ? ask.variables?.question : undefined}
          failed={failed ?? undefined}
          onRetry={failed ? () => send(failed.question, failed.panel) : undefined}
        />
      </main>
      <div className="mx-auto w-full max-w-[820px] px-5 pb-4">
        <Composer key={conversationId} onSubmit={send} disabled={ask.isPending} autoFocus />
        <AssistantFooter />
      </div>
    </>
  )
}
