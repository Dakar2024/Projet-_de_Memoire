
import {  useParams } from '@tanstack/react-router'

// Langues supportées
export const SUPPORTED_LOCALES = ['fr', 'en'] as const
export const DEFAULT_LOCALE = 'fr'

export type Locale = typeof SUPPORTED_LOCALES[number]

/**
 * Vérifie si un chemin commence par une langue valide
 */
export function getLocaleFromPath(pathname: string): Locale | null {
  const segments = pathname.split('/').filter(Boolean)
  const firstSegment = segments[0]

  if (SUPPORTED_LOCALES.includes(firstSegment as Locale)) {
    return firstSegment as Locale
  }

  return null
}

/**
 * Détecte la langue préférée depuis les headers ou cookies
 * Côté serveur : utilise request.headers
 */
export function detectPreferredLocale(request: Request): Locale {
  // 1. Vérifier le cookie de langue
  const cookies = request.headers.get('cookie') || ''
  const localeCookie = cookies
    .split(';')
    .find((c) => c.trim().startsWith('locale='))
    ?.split('=')[1]

  if (localeCookie && SUPPORTED_LOCALES.includes(localeCookie as Locale)) {
    return localeCookie as Locale
  }

  return DEFAULT_LOCALE
}

/**
 * Hook pour obtenir la langue actuelle
 */
export function useLocale(): Locale {
  const params = useParams({ strict: false })
  return (params.lang as Locale) || 'fr'
}

/**
 * Composant sélecteur de langue
 */

// export function LanguageSwitcher() {
//   const currentLocale = useLocale()
//   const changeLocale = useChangeLocale()
  
//   const localeNames: Record<Locale, string> = {
//     fr: '🇫🇷 Français',
//     en: '🇬🇧 English',
//     es: '🇪🇸 Español',
//     de: '🇩🇪 Deutsch',
//   }
  
//   return (
//     <div className="language-switcher">
//       <select 
//         value={currentLocale}
//         onChange={(e) => changeLocale(e.target.value as Locale)}
//         className="px-3 py-2 border rounded"
//       >
//         {SUPPORTED_LOCALES.map((locale) => (
//           <option key={locale} value={locale}>
//             {localeNames[locale]}
//           </option>
//         ))}
//       </select>
//     </div>
//   )
// }

/**
 * Helper pour générer des liens avec la bonne langue
 */
export function localizedPath(path: string, locale?: Locale): string {
  const currentLocale = locale || 'fr'
  
  // Si le path commence déjà par une langue, le retourner tel quel
  if (SUPPORTED_LOCALES.some(l => path.startsWith(`/${l}/`))) {
    return path
  }
  
  // Sinon, ajouter le préfixe de langue
  return `/${currentLocale}${path.startsWith('/') ? path : `/${path}`}`
}
