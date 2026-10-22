import { createServerFn } from '@tanstack/react-start'
import { setCookie } from '@tanstack/react-start/server'

export type Locale = 'en' | 'fr'

export const setLocaleCookie = createServerFn({ method: 'POST' })
  .inputValidator((data: Locale) => data)
  .handler(async ({ data }) => {
    setCookie('locale', data, {
      path: '/',
      maxAge: 60 * 60 * 24 * 365, // 1 an
      httpOnly: true,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
    })
    return { success: true, locale: data }
  })
