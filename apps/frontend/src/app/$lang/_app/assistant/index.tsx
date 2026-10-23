import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import type { ApiErrorCode, PanelId } from '@/shared/api/contracts'
import { Composer } from '@/features/assistant/components/Composer'
import { EmptyState } from '@/features/assistant/components/EmptyState'
import { Thread } from '@/features/assistant/components/Thread'
import { useAskQuestion } from '@/features/assistant/hooks'
import { AssistantFooter } from '@/features/assistant/components/AssistantFooter'

export const Route = createFileRoute('/$lang/_app/assistant/')({
  head: () => ({ meta: [{ title: 'Assistant · Genomica' }] }),
  component: NewConversation,
})

/** New conversation: the first answer creates it, then the URL moves to its own page. */
function NewConversation() {
  const { user } = Route.useRouteContext()
  const { lang } = Route.useParams()
  const navigate = useNavigate()
  const ask = useAskQuestion()
  const [sent, setSent] = useState<{ question: string; panel?: PanelId } | null>(null)
  const [failed, setFailed] = useState<ApiErrorCode | null>(null)

  async function send(question: string, panel: PanelId | undefined) {
    setSent({ question, panel })
    setFailed(null)
    const result = await ask.mutateAsync({ question, panel }).catch(() => null)
    if (!result?.ok) {
      setFailed(result?.code ?? 'internal')
      return
    }
    await navigate({
      to: '/$lang/assistant/$conversationId',
      params: { lang, conversationId: result.value.conversationId },
    })
  }

  if (!sent) {
    return (
      <main className="flex flex-1 flex-col items-center justify-center gap-8 overflow-y-auto px-5 py-10">
        <EmptyState name={user.fullName} onPick={(question) => send(question, undefined)} />
        <div className="w-full max-w-[760px]">
          <Composer onSubmit={send} autoFocus />
        </div>
        <AssistantFooter />
      </main>
    )
  }

  return (
    <>
      <main className="flex-1 overflow-y-auto">
        <Thread
          messages={[]}
          pending={failed ? undefined : sent.question}
          failed={failed ? { question: sent.question, code: failed } : undefined}
          onRetry={() => send(sent.question, sent.panel)}
        />
      </main>
      <div className="mx-auto w-full max-w-[820px] px-5 pb-4">
        <Composer onSubmit={send} disabled={ask.isPending} />
        <AssistantFooter />
      </div>
    </>
  )
}
