import { Trans, useLingui } from '@lingui/react/macro'
import { Search } from 'lucide-react'

/** Opening screen of a new conversation, with questions that the current index can answer. */
export function EmptyState({ name, onPick }: { name: string; onPick: (question: string) => void }) {
  const { t } = useLingui()
  const examples = [
    t`Le variant rs334 de HBB est-il pathogène ?`,
    t`Classification de BRCA1 c.68_69del ?`,
    t`TP53 p.Arg175His a-t-il été reclassé ?`,
    t`Combien de variants pathogènes sur BRCA2 ?`,
  ]

  return (
    <div className="flex flex-col items-center gap-7 text-center">
      <div className="flex flex-col gap-2">
        {name && <p className="text-muted-foreground">{t`Bonjour ${name}`}</p>}
        <h1 className="text-[clamp(28px,4vw,40px)] font-semibold leading-tight tracking-[-0.025em]">
          <Trans>Quel variant examinons-nous aujourd'hui ?</Trans>
        </h1>
      </div>
      <ul className="flex max-w-[680px] flex-wrap justify-center gap-2" aria-label={t`Exemples de questions`}>
        {examples.map((question) => (
          <li key={question}>
            <button
              type="button"
              onClick={() => onPick(question)}
              className="inline-flex min-h-10 items-center gap-2 rounded-full border border-border bg-card px-3.5 text-sm transition-colors hover:border-primary hover:bg-primary/5"
            >
              <Search className="size-3.5 text-primary" aria-hidden="true" />
              {question}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
