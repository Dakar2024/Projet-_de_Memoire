import { describe, expect, it } from 'vitest'
import { isProfessionalEmail } from './email'

describe('isProfessionalEmail', () => {
  it.each(['a.diop@chu-exemple.fr', 'x@inserm.fr', 'lab@univ-dakar.sn', 'A.Diop@CHU-Exemple.FR'])('accepts %s', (email) => {
    expect(isProfessionalEmail(email)).toBe(true)
  })

  it.each(['someone@gmail.com', 'x@GMAIL.COM', 'y@outlook.fr', 'z@orange.fr', 'w@proton.me', '@chu.fr', 'no-at-sign'])(
    'refuses %s',
    (email) => {
      expect(isProfessionalEmail(email)).toBe(false)
    },
  )
})
