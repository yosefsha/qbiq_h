/**
 * The shape of a log line.
 *
 * One JSON object per line carrying `timestamp`, `level`, `name`, `message`
 * and `request_id` — the same fields `backend/app/logging_config.py` emits, so
 * a log query written for one service works against the other.
 */

import { JsonLogger } from '../src/common/logging/json-logger'
import { NO_REQUEST_ID, runWithRequestId } from '../src/common/request-context'

/** Captures whatever the logger writes, so nothing reaches the test report. */
function capture(emit: () => void): Record<string, unknown>[] {
  const lines: string[] = []
  const original = process.stdout.write.bind(process.stdout)
  process.stdout.write = ((chunk: string) => {
    lines.push(chunk)
    return true
  }) as typeof process.stdout.write
  try {
    emit()
  } finally {
    process.stdout.write = original
  }
  return lines.map((line) => JSON.parse(line) as Record<string, unknown>)
}

describe('JsonLogger', () => {
  const logger = new JsonLogger('app.test', 'DEBUG')

  it('emits exactly one JSON object per line', () => {
    const records = capture(() => logger.log('hello'))

    expect(records).toHaveLength(1)
    expect(records[0]).toMatchObject({ level: 'INFO', name: 'app.test', message: 'hello' })
    expect(typeof records[0].timestamp).toBe('string')
  })

  it('tags the line with the current request id', () => {
    const records = capture(() => {
      runWithRequestId('req-42', () => logger.log('inside a request'))
    })

    expect(records[0].request_id).toBe('req-42')
  })

  it('reports a placeholder outside a request', () => {
    const records = capture(() => logger.log('at startup'))

    expect(records[0].request_id).toBe(NO_REQUEST_ID)
  })

  it('promotes extra fields to top-level keys', () => {
    const records = capture(() => logger.log('request completed', { status_code: 200 }))

    expect(records[0].status_code).toBe(200)
  })

  it('carries the stack on an exception', () => {
    const records = capture(() => logger.exception('request failed', new Error('boom')))

    expect(records[0].level).toBe('ERROR')
    expect(String(records[0].exc_info)).toContain('boom')
    expect(String(records[0].exc_info)).toContain('logging.spec.ts')
  })

  it('honours the configured level', () => {
    const quiet = new JsonLogger('app.test', 'ERROR')
    const records = capture(() => {
      quiet.log('suppressed')
      quiet.warn('also suppressed')
      quiet.error('kept')
    })

    expect(records).toHaveLength(1)
    expect(records[0].message).toBe('kept')
  })

  it('uses the same level names as the Python service', () => {
    const records = capture(() => {
      logger.debug('d')
      logger.log('i')
      logger.warn('w')
      logger.error('e')
    })

    expect(records.map((record) => record.level)).toEqual([
      'DEBUG',
      'INFO',
      'WARNING',
      'ERROR',
    ])
  })
})
