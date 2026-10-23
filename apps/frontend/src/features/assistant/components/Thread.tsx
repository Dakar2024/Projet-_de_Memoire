import { Trans, useLingui } from '@lingui/react/macro'
import { RotateCw } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { ApiErrorCode, ChatMessage } from '@/shared/api/contracts'
import { ApiError, errorMessage } from '@/shared/api/errors'
import { LogoMark } from '@/shared/components/brand/LogoMark'
import { AnswerBlock } from './AnswerBlock'

type ThreadProps = {
  messages: ChatMessage[]
  /** Question sent and not answered yet. */
  pending?: string
  /** Failed question and its error code, shown with a retry button. */
  failed?: { question: string; code: ApiErrorCode }
  onRetry?: () => void
}

/** Conversation thread: questions on the right, answers with their sources on the left. */
export function Thread({ messages, pending, failed, onRetry }: ThreadProps) {
  const { i18n } = useLingui()
  const end = useRef<HTMLDivElement>(null)

  // Keep the newest exchange in view whenever the thread grows.
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [messages.length, pending, failed])

  return (
    <div className="mx-auto flex w-full max-w-[820px] flex-col gap-8 px-5 pb-6 pt-8">
      {messages.map((message) =>
        message.role === 'user' ? (
          <Question key={message.id} text={message.content} />
        ) : (
          <div key={message.id} className="flex items-start gap-3.5">
            <LogoMark size={30} className="mt-0.5" />
            <AnswerBlock message={message} />
          </div>
        ),
      )}

      {pending && (
        <>
          <Question text={pending} />
          <Thinking />
        </>
      )}

      {failed && (
        <>
          <Question text={failed.question} />
          <div role="alert" className="ml-11 flex flex-wrap items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/8 px-4 py-3 text-sm text-destructive">
            <span className="min-w-0 flex-1">{i18n._(errorMessage(new ApiError(failed.code, 0)))}</span>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-destructive/30 px-3 font-medium hover:bg-destructive/10"
              >
                <RotateCw className="size-3.5" aria-hidden="true" />
                <Trans>Réessayer</Trans>
              </button>
            )}
          </div>
        </>
      )}
      <div ref={end} />
    </div>
  )
}

function Question({ text }: { text: string }) {
  return (
    <p className="max-w-[85%] self-end whitespace-pre-line break-words rounded-2xl rounded-br-md bg-muted px-4 py-3 text-[15px] leading-relaxed">
      {text}
    </p>
  )
}

/**
 * Waiting state. The RAG answers in one block, so there is no real progress to show: a single
 * honest label rather than fake steps.
 */
function Thinking() {
  return (
    <div className="flex items-center gap-3.5" role="status">
      <LogoMark size={30} className="animate-pulse" />
      <span className="text-sm text-muted-foreground">
        <Trans>Recherche dans les fiches ClinVar…</Trans>
      </span>
    </div>
  )
}
