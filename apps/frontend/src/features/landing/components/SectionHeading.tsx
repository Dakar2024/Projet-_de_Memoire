import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

type SectionHeadingProps = {
  eyebrow: ReactNode
  title: ReactNode
  lead?: ReactNode
  centered?: boolean
  id?: string
}

export function SectionHeading({ eyebrow, title, lead, centered, id }: SectionHeadingProps) {
  return (
    <div className={cn('flex max-w-[720px] flex-col gap-3.5', centered && 'items-center text-center')}>
      <span className="font-mono text-xs font-medium uppercase tracking-[0.08em] text-primary">{eyebrow}</span>
      <h2 id={id} className="text-[clamp(30px,3.6vw,44px)] font-semibold leading-[1.1] tracking-[-0.03em]">
        {title}
      </h2>
      {lead && <p className="text-[17px] leading-relaxed text-muted-foreground">{lead}</p>}
    </div>
  )
}
