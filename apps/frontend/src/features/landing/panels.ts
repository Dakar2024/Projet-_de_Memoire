import { msg } from '@lingui/core/macro'
import type { MessageDescriptor } from '@lingui/core'
import type { PanelId } from '@/shared/api/contracts'

/** Display names of the gene panels; the panel list itself always comes from the backend. */
export const PANEL_LABELS: Record<PanelId, MessageDescriptor> = {
  brca: msg`Cancer du sein héréditaire`,
  sickle: msg`Drépanocytose et modificateurs`,
}
