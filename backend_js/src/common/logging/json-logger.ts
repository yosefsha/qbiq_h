/**
 * Structured JSON logging.
 *
 * One JSON object per line carrying `timestamp`, `level`, `name`, `message`
 * and `request_id`, matching what `backend/app/logging_config.py` emits so a
 * log pipeline (and `docs/runbook.md`) does not have to care which
 * implementation produced a line. `request_id` is read from the
 * `AsyncLocalStorage` in `request-context.ts` rather than passed in, which is
 * what lets any code log a correlated line without taking a logger argument.
 *
 * Written by hand rather than pulled from pino: the field names, the level
 * names and the `-` placeholder outside a request are a contract with the
 * Python service, and a library's defaults would have to be bent back into
 * shape anyway.
 */

import { LoggerService } from '@nestjs/common'

import { getRequestId } from '../request-context'
import { settings } from '../../config/settings'

/** Severity names, ordered least to most severe, as Python's logging uses. */
const LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const

export type Level = (typeof LEVELS)[number]

/** Extra fields promoted to top-level keys on the emitted JSON object. */
export type LogFields = Record<string, unknown>

function severity(level: Level): number {
  return LEVELS.indexOf(level)
}

function isEnabled(level: Level, threshold: string): boolean {
  const configured = LEVELS.includes(threshold as Level) ? (threshold as Level) : 'INFO'
  return severity(level) >= severity(configured)
}

/**
 * Emits one JSON object per line on stdout.
 *
 * `name` identifies the emitting component, matching the Python loggers
 * (`app.request`, `app.session`, `app.health`) so the two implementations'
 * logs are filterable by the same values.
 */
export class JsonLogger implements LoggerService {
  /**
   * `threshold` defaults to `LOG_LEVEL`, read per emit so the configured level
   * is honoured however late the logger was constructed. It is only ever
   * passed explicitly by the test that asserts the emitted record's shape,
   * which has to be able to log below the level the suite otherwise runs at.
   */
  constructor(
    private readonly name: string,
    private readonly threshold?: Level,
  ) {}

  log(message: string, fields: LogFields = {}): void {
    this.emit('INFO', message, fields)
  }

  warn(message: string, fields: LogFields = {}): void {
    this.emit('WARNING', message, fields)
  }

  error(message: string, fields: LogFields = {}): void {
    this.emit('ERROR', message, fields)
  }

  debug(message: string, fields: LogFields = {}): void {
    this.emit('DEBUG', message, fields)
  }

  verbose(message: string, fields: LogFields = {}): void {
    this.emit('DEBUG', message, fields)
  }

  /**
   * Logs an error together with its stack, under the `exc_info` key.
   *
   * The stack is a plain string field rather than a nested object so a log
   * search for a frame matches the same way it does for a Python traceback.
   */
  exception(message: string, cause: unknown, fields: LogFields = {}): void {
    const stack = cause instanceof Error ? (cause.stack ?? cause.message) : String(cause)
    this.emit('ERROR', message, { ...fields, exc_info: stack })
  }

  private emit(level: Level, message: string, fields: LogFields): void {
    if (!isEnabled(level, this.threshold ?? settings.logLevel)) {
      return
    }
    const record = {
      timestamp: new Date().toISOString(),
      level,
      name: this.name,
      message,
      request_id: getRequestId(),
      ...fields,
    }
    process.stdout.write(`${JSON.stringify(record)}\n`)
  }
}
