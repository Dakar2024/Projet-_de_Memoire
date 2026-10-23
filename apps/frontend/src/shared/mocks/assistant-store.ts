import type {
  AnswerSource,
  AskQuestionInput,
  AskQuestionResponse,
  AssistantMessage,
  Conversation,
  ConversationSummary,
  ScopeReason,
} from '@/shared/api/contracts'
import type { MockResult } from './auth-store'

/**
 * In-memory stand-in for the backend `assistant` feature (VITE_USE_MOCKS=true), per user, reset at restart.
 * Records are copied from the RAG index (rag_documents, archive 2026-10) and fixed texts from
 * RAG/src/generation/messages.py, so the mock never shows an invented classification. Only a handful
 * of questions are recognised; anything else gets the RAG's "no document" answer.
 */

const ARCHIVE = '2026-10'
const DISCLAIMER = `Aide à la consultation de ClinVar (archive ${ARCHIVE}) ; ne remplace pas l'interprétation clinique d'un biologiste.`
const DAILY_QUOTA = 50

const STARS: Record<string, number> = {
  'practice guideline': 4,
  'reviewed by expert panel': 3,
  'criteria provided, multiple submitters, no conflicts': 2,
  'criteria provided, single submitter': 1,
  'criteria provided, conflicting classifications': 1,
}

function source(
  rank: number,
  gene: string,
  variant: string,
  protein: string,
  significance: string,
  significanceFr: string,
  reviewStatus: string,
  variationId: string,
): AnswerSource {
  return {
    rank,
    gene,
    variant,
    protein,
    significance,
    significanceFr,
    reviewStatus,
    stars: STARS[reviewStatus] ?? 0,
    clinvarVariationId: variationId,
    clinvarUrl: `https://www.ncbi.nlm.nih.gov/clinvar/variation/${variationId}/`,
    archive: ARCHIVE,
    previousSignificanceFr: null,
    previousUntil: null,
  }
}

type Canned = Pick<AssistantMessage, 'status' | 'scopeReason' | 'content' | 'sources'>

const OUT_OF_SCOPE: Record<ScopeReason, string> = {
  counting:
    "Cet outil retrouve les fiches ClinVar les plus pertinentes pour une question ; il ne compte pas les variants et ne dresse pas de liste exhaustive. Un comptage relève d'une analyse dédiée de ClinVar.",
  acmg: "Cet outil ne classe pas les variants selon les critères ACMG : il restitue la classification déposée dans ClinVar. La classification reste l'acte du biologiste.",
  frequency:
    'Les fréquences en population (gnomAD, cohortes africaines) ne font pas partie des sources de cet outil, qui s’appuie sur ClinVar, MedGen, HPO et NCBI Gene.',
  clinical_advice:
    "Cet outil ne donne pas de conseil de prise en charge ni d'interprétation clinique : il restitue ce que ClinVar documente.",
  other: 'Cette question sort du périmètre de l’outil, limité aux données ClinVar du panel de 18 gènes.',
  gene_out_of_panel:
    "Ce gène ne fait pas partie du panel de l'outil (12 gènes du cancer du sein héréditaire, 6 gènes de la drépanocytose et des modificateurs de l'hémoglobine fœtale) : aucune fiche n'est disponible.",
}

const NO_DOCUMENT = 'Aucune fiche ClinVar du panel ne correspond à cette question.'

const outOfScope = (reason: ScopeReason): Canned => ({
  status: 'out_of_scope',
  scopeReason: reason,
  content: OUT_OF_SCOPE[reason],
  sources: [],
})

/** First matching rule wins; patterns run on the lower-cased question. */
const RULES: [RegExp, () => Canned][] = [
  [/\b(combien|nombre|liste[rz]?|tous les)\b/, () => outOfScope('counting')],
  [/\bacmg\b/, () => outOfScope('acmg')],
  [/\b(fréquence|frequence|gnomad|prévalence)\b/, () => outOfScope('frequency')],
  [/\b(traitement|traiter|prise en charge|conseill)/, () => outOfScope('clinical_advice')],
  [/\b(cftr|mlh1|msh2|apc|kras|egfr|brca3)\b/, () => outOfScope('gene_out_of_panel')],
  [
    /rs334\b|hbb c\.20a/,
    () => ({
      status: 'answered',
      scopeReason: null,
      content:
        "L'identifiant rs334 correspond à deux allèles distincts dans ClinVar. Le variant HBB c.20A>T (p.Glu7Val), responsable de l'hémoglobine S, est classé pathogène (critères fournis, plusieurs soumetteurs, sans conflit). L'allèle c.20A>C (p.Glu7Ala) est classé probablement bénin, sur la base d'un seul soumetteur.",
      sources: [
        source(1, 'HBB', 'c.20A>T', 'p.Glu7Val', 'Pathogenic', 'pathogène', 'criteria provided, multiple submitters, no conflicts', '15333'),
        source(2, 'HBB', 'c.20A>C', 'p.Glu7Ala', 'Likely benign', 'probablement bénin', 'criteria provided, single submitter', '15175'),
      ],
    }),
  ],
  [
    /brca1.*c\.68_69del|c\.68_69del|185delag/,
    () => ({
      status: 'answered',
      scopeReason: null,
      content:
        "Le variant BRCA1 c.68_69del (p.Glu23fs) est classé pathogène dans ClinVar. Cette classification a été revue par un panel d'experts, le plus haut niveau de revue après les recommandations de pratique.",
      sources: [
        source(1, 'BRCA1', 'c.68_69del', 'p.Glu23fs', 'Pathogenic', 'pathogène', 'reviewed by expert panel', '17662'),
      ],
    }),
  ],
  [
    /tp53.*(arg175his|r175h|c\.524g>a)/,
    () => ({
      status: 'partial',
      scopeReason: null,
      content:
        "TP53 c.524G>A (p.Arg175His) est classé pathogène, revu par un panel d'experts. La fiche ClinVar de l'archive 2026-10 ne contient pas d'historique de classification : une éventuelle reclassification antérieure ne peut pas être établie à partir des sources.",
      sources: [
        source(1, 'TP53', 'c.524G>A', 'p.Arg175His', 'Pathogenic', 'pathogène', 'reviewed by expert panel', '12374'),
      ],
    }),
  ],
]

export function cannedAnswer(question: string): Canned {
  const q = question.toLowerCase()
  const rule = RULES.find(([pattern]) => pattern.test(q))
  return rule ? rule[1]() : { status: 'not_in_sources', scopeReason: null, content: NO_DOCUMENT, sources: [] }
}

/** Conversation title as the backend builds it: the first ~60 characters of the first question. */
export function conversationTitle(question: string): string {
  const flat = question.replace(/\s+/g, ' ').trim()
  return flat.length <= 60 ? flat : `${flat.slice(0, 59).trimEnd()}…`
}

type Stored = Conversation & { ownerId: string; deleted: boolean }

const conversations = new Map<string, Stored>()
const asked = new Map<string, number>()

function summary({ id, title, updatedAt }: Stored): ConversationSummary {
  return { id, title, updatedAt }
}

export function mockListConversations(userId: string): ConversationSummary[] {
  return [...conversations.values()]
    .filter((c) => c.ownerId === userId && !c.deleted)
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
    .map(summary)
}

export function mockGetConversation(userId: string, id: string): MockResult<Conversation> {
  const stored = conversations.get(id)
  // Someone else's conversation answers exactly like a missing one.
  if (!stored || stored.ownerId !== userId || stored.deleted) return { ok: false, code: 'not_found' }
  const { ownerId: _owner, deleted: _deleted, ...conversation } = stored
  return { ok: true, value: conversation }
}

export function mockDeleteConversation(userId: string, id: string): MockResult<null> {
  const stored = conversations.get(id)
  if (!stored || stored.ownerId !== userId || stored.deleted) return { ok: false, code: 'not_found' }
  stored.deleted = true
  return { ok: true, value: null }
}

export function mockAsk(userId: string, input: AskQuestionInput, now = new Date()): MockResult<AskQuestionResponse> {
  const used = asked.get(userId) ?? 0
  if (used >= DAILY_QUOTA) return { ok: false, code: 'quota_exceeded' }

  let stored: Stored | undefined
  if (input.conversationId) {
    stored = conversations.get(input.conversationId)
    if (!stored || stored.ownerId !== userId || stored.deleted) return { ok: false, code: 'not_found' }
  } else {
    stored = {
      id: crypto.randomUUID(),
      ownerId: userId,
      deleted: false,
      title: conversationTitle(input.question),
      panel: input.panel ?? null,
      updatedAt: now.toISOString(),
      messages: [],
    }
    conversations.set(stored.id, stored)
  }

  const at = now.toISOString()
  const message: AssistantMessage = {
    id: crypto.randomUUID(),
    role: 'assistant',
    createdAt: at,
    history: [],
    disclaimer: DISCLAIMER,
    ...cannedAnswer(input.question),
  }
  stored.messages.push({ id: crypto.randomUUID(), role: 'user', content: input.question, createdAt: at }, message)
  stored.updatedAt = at
  asked.set(userId, used + 1)
  return { ok: true, value: { conversationId: stored.id, message, quotaRemaining: DAILY_QUOTA - used - 1 } }
}
