import { createFileRoute } from '@tanstack/react-router'
import { useSuspenseQuery } from '@tanstack/react-query'
import { panelsQuery } from '@/features/landing/server'
import { SiteHeader } from '@/features/landing/components/SiteHeader'
import { Hero } from '@/features/landing/components/Hero'
import { StatsBand } from '@/features/landing/components/StatsBand'
import { AnswerPreview } from '@/features/landing/components/AnswerPreview'
import { Features } from '@/features/landing/components/Features'
import { Method } from '@/features/landing/components/Method'
import { Panels } from '@/features/landing/components/Panels'
import { FinalCta, SiteFooter, Trust } from '@/features/landing/components/Trust'

export const Route = createFileRoute('/$lang/')({
  loader: ({ context }) => context.queryClient.ensureQueryData(panelsQuery),
  component: LandingPage,
})

function LandingPage() {
  const { data } = useSuspenseQuery(panelsQuery)

  return (
    <div className="min-h-screen overflow-x-hidden">
      <SiteHeader />
      <main>
        <Hero />
        <StatsBand data={data} />
        <AnswerPreview archive={data.archive} />
        <Features />
        <Method />
        <Panels data={data} />
        <Trust />
        <FinalCta />
      </main>
      <SiteFooter />
    </div>
  )
}
