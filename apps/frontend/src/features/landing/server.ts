import { createServerFn } from '@tanstack/react-start'
import { queryOptions } from '@tanstack/react-query'
import type { PanelsResponse } from '@/shared/api/contracts'
import { USE_PANELS_FIXTURE, backendFetch } from '@/shared/api/backend'
import { PANELS_FIXTURE } from '@/shared/mocks/data'

/** Public panel catalogue with live counts; read during SSR so the landing page ships its figures. */
export const getPanelsFn = createServerFn({ method: 'GET' }).handler(async (): Promise<PanelsResponse> => {
  if (USE_PANELS_FIXTURE) return PANELS_FIXTURE
  const response = await backendFetch('/api/panels', { method: 'GET' })
  if (!response.ok) throw new Error(`panels: ${response.status}`)
  return (await response.json()) as PanelsResponse
})

export const panelsQuery = queryOptions({
  queryKey: ['panels'],
  queryFn: () => getPanelsFn(),
  // The gold layer changes once a month: an hour of cache is plenty.
  staleTime: 60 * 60 * 1000,
})
