import { createServerFn } from '@tanstack/react-start'
import * as z from 'zod'
import type { AccessRequest, ApiErrorCode } from '@/shared/api/contracts'
import { USE_MOCKS, backendFetch, errorCode } from '@/shared/api/backend'
import { mockAccessRequests, mockDecide } from '@/shared/mocks/auth-store'

/** Admin review of access requests (MODELISATION_BACKEND.md § 4.5); the backend checks the role. */

export type DecisionResult = { ok: true } | { ok: false; code: ApiErrorCode }

export const listAccessRequestsFn = createServerFn({ method: 'GET' }).handler(async (): Promise<AccessRequest[]> => {
  if (USE_MOCKS) return mockAccessRequests()
  const response = await backendFetch('/api/admin/requests', { method: 'GET' })
  if (!response.ok) throw new Error(`admin/requests: ${response.status}`)
  return (await response.json()) as AccessRequest[]
})

const decisionSchema = z.object({
  id: z.uuid().or(z.string().min(1).max(64)),
  decision: z.enum(['approve', 'reject']),
  reason: z.string().trim().max(1000).optional(),
})

export const decideAccessRequestFn = createServerFn({ method: 'POST' })
  .inputValidator(decisionSchema)
  .handler(async ({ data }): Promise<DecisionResult> => {
    if (USE_MOCKS) {
      const result = mockDecide(data.id, data.decision)
      return result.ok ? { ok: true } : result
    }
    const path = `/api/admin/requests/${encodeURIComponent(data.id)}/${data.decision}`
    const response = await backendFetch(path, {
      method: 'POST',
      json: data.decision === 'reject' ? { reason: data.reason ?? '' } : undefined,
    })
    return response.ok ? { ok: true } : { ok: false, code: await errorCode(response) }
  })
