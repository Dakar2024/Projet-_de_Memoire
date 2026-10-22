import { useNavigate, useParams } from '@tanstack/react-router'
import { useState } from 'react'
import { setLocaleCookie, type Locale } from '@/shared/actions/cookies'

type LanguageCode = 'en' | 'fr'

export default function LanguageSwitcher() {
  const navigate = useNavigate()
  const params = useParams({ strict: false })

  const [language, setLanguage] = useState<LanguageCode>(
    (params.lang as LanguageCode) || 'fr'
  )

  async function changeLocale(newLang: LanguageCode) {
    const currentPath = window.location.pathname
    const currentLocale = params.lang
    if (!currentLocale) return

    // Sauvegarder la langue dans le cookie côté serveur
    await setLocaleCookie({ data: newLang as Locale })

    const newPath = currentPath.replace(
      new RegExp(`^/${currentLocale}(/|$)`),
      `/${newLang}$1`
    )
    navigate({ to: newPath })
  }

  function handleChange(language: LanguageCode) {
    setLanguage(language)
    changeLocale(language)
  }

  return (
    <div className="flex items-center gap-1 rounded-full border border-border bg-muted/60 p-1 text-sm shadow-sm">
      {(['en', 'fr'] as const).map((code) => (
        <button
          key={code}
          type="button"
          onClick={() => handleChange(code)}
          className={`rounded-full px-3 py-1.5 transition ${language === code
              ? 'bg-background text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'
            }`}
          aria-pressed={language === code}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  )
}
