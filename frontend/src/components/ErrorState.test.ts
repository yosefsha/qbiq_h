import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { ApiError } from '../types'
import ErrorState from './ErrorState.vue'

describe('ErrorState', () => {
  it('presents a 404 as "not found" without offering a retry', () => {
    const error: ApiError = { kind: 'http', status: 404, message: 'Product not found' }
    const wrapper = mount(ErrorState, { props: { error } })

    expect(wrapper.attributes('data-error-kind')).toBe('http')
    expect(wrapper.text()).toContain('Not found')
    expect(wrapper.text()).toContain('Product not found')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('presents a 500 as a server failure and offers a retry', () => {
    const error: ApiError = { kind: 'http', status: 500, message: 'Internal Server Error' }
    const wrapper = mount(ErrorState, { props: { error } })

    expect(wrapper.text()).toContain('Request failed (500)')
    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('presents a network failure distinctly from an HTTP failure and offers a retry', () => {
    const error: ApiError = { kind: 'network', message: 'Failed to fetch' }
    const wrapper = mount(ErrorState, { props: { error } })

    expect(wrapper.attributes('data-error-kind')).toBe('network')
    expect(wrapper.text()).toContain("Can't reach the server")
    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('renders distinct titles for the three failure kinds', () => {
    const kinds: ApiError[] = [
      { kind: 'http', status: 404, message: 'x' },
      { kind: 'http', status: 500, message: 'x' },
      { kind: 'network', message: 'x' },
    ]

    const titles = kinds.map((error) => mount(ErrorState, { props: { error } }).find('h2').text())

    expect(new Set(titles).size).toBe(titles.length)
  })

  it('emits retry when the retry button is clicked', async () => {
    const error: ApiError = { kind: 'network', message: 'Failed to fetch' }
    const wrapper = mount(ErrorState, { props: { error } })

    await wrapper.find('button').trigger('click')

    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('does not offer a retry for a 4xx, which retrying cannot fix', () => {
    const error: ApiError = { kind: 'http', status: 400, message: 'Bad request' }
    const wrapper = mount(ErrorState, { props: { error } })

    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('offers a retry for a parse failure', () => {
    // This case had no coverage: the test above was titled "parse failure" but
    // passed a `kind: 'http'` error and asserted the opposite of what a real
    // parse failure does.
    const error: ApiError = { kind: 'parse', message: 'Malformed body' }
    const wrapper = mount(ErrorState, { props: { error } })

    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('announces itself to assistive tech via role="alert", for every error kind', () => {
    const errors: ApiError[] = [
      { kind: 'http', status: 404, message: 'x' },
      { kind: 'http', status: 500, message: 'x' },
      { kind: 'network', message: 'x' },
      { kind: 'parse', message: 'x' },
    ]

    for (const error of errors) {
      const wrapper = mount(ErrorState, { props: { error } })
      expect(wrapper.attributes('role')).toBe('alert')
    }
  })

  it('gives the retry button an accessible name from its own visible text, not just an icon', () => {
    const error: ApiError = { kind: 'network', message: 'Failed to fetch' }
    const wrapper = mount(ErrorState, { props: { error } })

    const button = wrapper.get('button')
    expect(button.element.tagName).toBe('BUTTON')
    expect(button.text()).toBe('Retry')
  })
})
