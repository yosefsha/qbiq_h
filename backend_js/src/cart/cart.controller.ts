/**
 * Cart routes: server-authoritative Cart operations.
 *
 * Implements exactly the four operations ADR-001 assigns to the server: read
 * the Cart, add a line, change a line's quantity, and remove a line. Every
 * route is behind `SessionGuard` for the Shopper's identity and never reads
 * the `session_id` cookie itself, and never accepts a session id from a query
 * parameter or header — ADR-001 rejects that outright, since it would let any
 * caller read or mutate another Shopper's Cart by guessing or copying an id.
 *
 * Every mutation returns 200 with the whole Cart. There is deliberately no 201
 * and no 204: the SPA re-renders from the response body, so a body-less
 * success would force it into a second request to find out what it had just
 * done.
 */

import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  HttpStatus,
  Inject,
  NotFoundException,
  Param,
  Patch,
  Post,
  UnprocessableEntityException,
  UseGuards,
  ValidationPipe,
} from '@nestjs/common'

import { Cart } from '../domain/cart'
import { UnknownProductError } from '../domain/errors'
import { CART_REPOSITORY, CartRepository } from '../domain/repositories'
import { CurrentSession } from '../common/session/current-session.decorator'
import { SessionGuard } from '../common/session/session.guard'
import { SessionId } from '../common/session/session-id'
import { AddCartItemRequest, SetCartItemQuantityRequest } from './dto/cart.request'
import { CartView, toCartView } from './dto/cart.response'

/**
 * Rejects a body carrying any field the request shape does not declare, and
 * reports a failure as 422 rather than Nest's default 400 — the status the
 * Python service returns and the SPA is written against.
 */
const bodyPipe = new ValidationPipe({
  transform: true,
  whitelist: true,
  forbidNonWhitelisted: true,
  errorHttpStatusCode: HttpStatus.UNPROCESSABLE_ENTITY,
})

/**
 * Runs a `CartRepository` write, translating domain errors into HTTP ones.
 *
 * Centralised here rather than duplicated as a try/catch in every route below.
 * A `RangeError` covers a repository-enforced rule the request shape cannot
 * express at the boundary — `addItem`'s *cumulative* per-line ceiling
 * (existing quantity + this request's quantity), which no single request's own
 * `quantity` field can be validated against in isolation.
 */
async function translateDomainErrors(operation: () => Promise<Cart>): Promise<Cart> {
  try {
    return await operation()
  } catch (cause) {
    if (cause instanceof UnknownProductError) {
      throw new NotFoundException(cause.message)
    }
    if (cause instanceof RangeError) {
      throw new UnprocessableEntityException(cause.message)
    }
    throw cause
  }
}

@Controller('api/cart')
@UseGuards(SessionGuard)
export class CartController {
  constructor(
    @Inject(CART_REPOSITORY) private readonly carts: CartRepository,
  ) {}

  /** Returns the current Shopper's Cart, creating an empty one if unseen. */
  @Get()
  async getCart(@CurrentSession() session: SessionId): Promise<CartView> {
    return toCartView(await this.carts.getCart(session.value))
  }

  /**
   * Adds `quantity` of a product, incrementing rather than duplicating a line
   * that is already in the Cart.
   */
  @Post('items')
  @HttpCode(HttpStatus.OK)
  async addItem(
    @CurrentSession() session: SessionId,
    @Body(bodyPipe) body: AddCartItemRequest,
  ): Promise<CartView> {
    const cart = await translateDomainErrors(() =>
      this.carts.addItem(session.value, body.productId, body.quantity),
    )
    return toCartView(cart)
  }

  /** Sets a line's quantity to exactly `body.quantity` (always >= 1). */
  @Patch('items/:productId')
  @HttpCode(HttpStatus.OK)
  async setItemQuantity(
    @CurrentSession() session: SessionId,
    @Param('productId') productId: string,
    @Body(bodyPipe) body: SetCartItemQuantityRequest,
  ): Promise<CartView> {
    const cart = await translateDomainErrors(() =>
      this.carts.setQuantity(session.value, productId, body.quantity),
    )
    return toCartView(cart)
  }

  /** Removes a line from the Cart. A no-op, not a 404, if it was absent. */
  @Delete('items/:productId')
  @HttpCode(HttpStatus.OK)
  async removeItem(
    @CurrentSession() session: SessionId,
    @Param('productId') productId: string,
  ): Promise<CartView> {
    return toCartView(await this.carts.removeItem(session.value, productId))
  }
}
