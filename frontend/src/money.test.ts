import { describe, expect, it } from 'vitest'

import { formatPriceMinor } from './money'

describe('formatPriceMinor', () => {
  it('formats integer minor units as a currency string', () => {
    expect(formatPriceMinor(14900, 'USD')).toBe('$149.00')
  })

  it('pads a whole number of minor units to two decimal places', () => {
    expect(formatPriceMinor(999, 'USD')).toBe('$9.99')
  })

  it('formats zero', () => {
    expect(formatPriceMinor(0, 'USD')).toBe('$0.00')
  })

  it('formats a different currency with its own symbol', () => {
    expect(formatPriceMinor(14900, 'EUR')).toBe('€149.00')
  })
})
