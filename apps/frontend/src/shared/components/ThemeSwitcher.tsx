import { useTheme } from 'next-themes'
import { Sun, Moon, Laptop } from 'lucide-react'
import { useEffect, useState } from 'react'

export default function ThemeSwitcher() {
    const { theme, setTheme } = useTheme()
    const [mounted, setMounted] = useState(false)

    // Avoid hydration mismatch
    useEffect(() => {
        setMounted(true)
    }, [])

    if (!mounted) {
        return (
            <div className="h-9 w-9 rounded-lg border border-border bg-background/50" />
        )
    }

    const themes = [
        { name: 'light', icon: Sun },
        { name: 'dark', icon: Moon },
        { name: 'system', icon: Laptop },
    ]

    return (
        <div className="flex items-center gap-1 rounded-xl border border-border bg-background/50 p-1 shadow-sm backdrop-blur">
            {themes.map((t) => {
                const Icon = t.icon
                const isActive = theme === t.name

                return (
                    <button
                        key={t.name}
                        onClick={() => setTheme(t.name)}
                        className={`flex h-8 w-8 items-center justify-center rounded-lg transition-all duration-200 ${isActive
                                ? 'bg-primary text-primary-foreground shadow-sm'
                                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                            }`}
                        aria-label={`Switch to ${t.name} theme`}
                    >
                        <Icon size={16} strokeWidth={2.5} />
                    </button>
                )
            })}
        </div>
    )
}
