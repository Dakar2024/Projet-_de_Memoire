import { describe, expect, it } from 'vitest'
import { safeRedirect } from './redirect'

const FALLBACK = '/fr/assistant'

describe('safeRedirect', () => {
  it.each([
    ['/fr/assistant/abc?x=1#top', '/fr/assistant/abc?x=1#top'],
    ['/en/explorer?panel=brca', '/en/explorer?panel=brca'],
  ])('keeps the in-app path %s', (target, expected) => {
    expect(safeRedirect(target, FALLBACK)).toBe(expected)
  })

  it.each([
    [undefined],
    [42],
    [''],
    ['https://evil.example/fr/assistant'],
    ['//evil.example/fr'],
    ['/\\evil.example'],
    ['/fr/assistant\u0000'],
    ['javascript:alert(1)'],
    ['fr/assistant'],
    ['/fr/sign-in'],
    ['/en/pending?reason=pending_email'],
    ['/fr/onboarding'],
    ['/fr/verify-email?token=abc'],
    ['/fr/reset-password?token=abc'],
  ])('falls back for %j', (target) => {
    expect(safeRedirect(target, FALLBACK)).toBe(FALLBACK)
  })
})
