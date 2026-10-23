import { Trans } from '@lingui/react/macro'

export function AssistantFooter() {
  return (
    <p className="pt-2 text-center text-xs text-faint">
      <Trans>Genomica restitue ClinVar et peut se tromper : vérifiez chaque fiche citée avant toute décision.</Trans>
    </p>
  )
}
