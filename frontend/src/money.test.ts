import { describe, expect, it } from 'vitest'

import { formatMoney } from './money'

describe('formatMoney', () => {
  it('formats integer minor units as a currency string', () => {
    expect(formatMoney(14900, 'USD')).toBe('$149.00')
  })

  it('formats zero minor units', () => {
    expect(formatMoney(0, 'USD')).toBe('$0.00')
  })

  it('respects the currency code rather than hardcoding USD', () => {
    expect(formatMoney(14900, 'EUR')).toBe('€149.00')
  })

  it('rounds to the currency-appropriate number of decimal places', () => {
    expect(formatMoney(1, 'USD')).toBe('$0.01')
  })
})
