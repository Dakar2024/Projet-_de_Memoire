import { Trans, useLingui } from '@lingui/react/macro'
import { ArrowUp } from 'lucide-react'
import { useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import type { PanelId } from '@/shared/api/contracts'
import { PANEL_LABELS } from '@/features/landing/panels'
import { cn } from '@/lib/utils'
import { QUESTION_MAX } from '../schemas'

/**
 * The panel filter needs the RAG `panels` parameter (MODELISATION_BACKEND.md § 4.2). Until the retriever
 * honours it, the selector stays hidden: showing it would promise a restriction that does not exist.
 */
const PANEL_FILTER = import.meta.env.VITE_ASSISTANT_PANEL_FILTER === 'true'
const MAX_HEIGHT = 240

type ComposerProps = {
  onSubmit: (question: string, panel: PanelId | undefined) => void
  disabled?: boolean
  autoFocus?: boolean
  /** Text put back in the field after a failed send, so the question is never lost. */
  initialValue?: string
}

export function Composer({ onSubmit, disabled = false, autoFocus = false, initialValue = '' }: ComposerProps) {
  const { t, i18n } = useLingui()
  const [value, setValue] = useState(initialValue)
  const [panel, setPanel] = useState<PanelId | undefined>(undefined)
  const textarea = useRef<HTMLTextAreaElement>(null)

  // Grows with the text up to MAX_HEIGHT, then scrolls.
  useLayoutEffect(() => {
    const el = textarea.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
    el.style.overflowY = el.scrollHeight > MAX_HEIGHT ? 'auto' : 'hidden'
  }, [value])

  const question = value.trim()
  const tooLong = value.length > QUESTION_MAX
  const canSend = !disabled && question.length > 0 && !tooLong

  function submit(event?: FormEvent) {
    event?.preventDefault()
    if (!canSend) return
    onSubmit(question, panel)
    setValue('')
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter breaks the line; never send while an IME is composing.
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-2 rounded-[22px] border border-border bg-card p-2.5 shadow-elevated transition-colors focus-within:border-primary/60"
    >
      <label htmlFor="question" className="sr-only">
        <Trans>Votre question</Trans>
      </label>
      <textarea
        id="question"
        ref={textarea}
        rows={1}
        value={value}
        autoFocus={autoFocus}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={t`Posez votre question sur un variant`}
        aria-describedby="question-hint"
        aria-invalid={tooLong || undefined}
        className="min-h-11 w-full resize-none overflow-hidden bg-transparent px-2.5 py-2 text-[15px] leading-relaxed outline-none placeholder:text-faint"
      />
      <div className="flex items-center gap-2 pl-1">
        {PANEL_FILTER && (
          <div role="radiogroup" aria-label={t`Panel interrogé`} className="flex flex-wrap gap-1">
            {([undefined, 'brca', 'sickle'] as const).map((id) => (
              <button
                key={id ?? 'all'}
                type="button"
                role="radio"
                aria-checked={panel === id}
                onClick={() => setPanel(id)}
                className={cn(
                  'min-h-8 rounded-full border px-3 text-xs transition-colors',
                  panel === id
                    ? 'border-primary bg-primary/10 text-foreground'
                    : 'border-border text-muted-foreground hover:bg-muted',
                )}
              >
                {id ? i18n._(PANEL_LABELS[id]) : t`Tous les panels`}
              </button>
            ))}
          </div>
        )}
        <p id="question-hint" className={cn('ml-auto text-xs', tooLong ? 'text-destructive' : 'text-faint')}>
          {value.length > QUESTION_MAX * 0.8 ? (
            `${value.length} / ${QUESTION_MAX}`
          ) : (
            <span className="max-sm:sr-only">
              <Trans>Identifiant rs, notation HGVS ou phrase libre · Maj + Entrée pour aller à la ligne</Trans>
            </span>
          )}
        </p>
        <button
          type="submit"
          disabled={!canSend}
          className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-opacity disabled:opacity-35"
          aria-label={t`Envoyer la question`}
        >
          <ArrowUp className="size-5" aria-hidden="true" />
        </button>
      </div>
    </form>
  )
}
