import { msg } from '@lingui/core/macro'
import type { MessageDescriptor } from '@lingui/core'
import type { Profession } from '@/shared/api/contracts'

export const PROFESSION_LABELS: Record<Profession, MessageDescriptor> = {
  medical_biologist: msg`Biologiste médical`,
  clinical_geneticist: msg`Généticien clinicien`,
  bioinformatician: msg`Bioinformaticien`,
  genetic_counselor: msg`Conseiller en génétique`,
  researcher: msg`Chercheur`,
  other: msg`Autre`,
}
