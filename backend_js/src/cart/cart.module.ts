import { Module } from '@nestjs/common'

import { CartController } from './cart.controller'
import { SessionStore } from '../common/session/session.store'

/**
 * The Cart half of the API.
 *
 * `SessionStore` is provided here rather than globally because `SessionGuard`
 * is the only thing that needs it, and these are the only routes the guard is
 * applied to — the catalogue and `/health` mint no session.
 */
@Module({
  controllers: [CartController],
  providers: [SessionStore],
})
export class CartModule {}
