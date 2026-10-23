import * as z from 'zod'

/** Same bounds as the RAG `QuestionIn` (1 to 1,000 characters), checked before any call. */
export const QUESTION_MAX = 1000

export const askQuestionSchema = z.object({
  conversationId: z.string().min(1).max(64).optional(),
  question: z.string().trim().min(1).max(QUESTION_MAX),
  panel: z.enum(['brca', 'sickle']).optional(),
})

export const conversationIdSchema = z.object({ id: z.string().min(1).max(64) })
