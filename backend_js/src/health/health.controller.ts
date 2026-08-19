/**
 * The ALB target group's health check.
 *
 * 503 rather than 500 on failure: the task is answering, it just is not able
 * to serve requests yet. See `health.service.ts` for why the dependency probes
 * stop once they have succeeded.
 */

import { Controller, Get, HttpStatus, Res } from '@nestjs/common'
import { Response } from 'express'

import { HealthReport, HealthService, STATUS_OK } from './health.service'

@Controller()
export class HealthController {
  constructor(private readonly health: HealthService) {}

  @Get('health')
  async check(@Res({ passthrough: true }) response: Response): Promise<HealthReport> {
    const report = await this.health.status()
    if (report.status !== STATUS_OK) {
      response.status(HttpStatus.SERVICE_UNAVAILABLE)
    }
    return report
  }
}
