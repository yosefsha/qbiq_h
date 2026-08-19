/**
 * Cart request bodies.
 *
 * `forbidNonWhitelisted` is applied to these in the controller: this API never
 * accepts a price from the client — every total is computed server-side from
 * the catalogue — so an extra `unitPriceMinor` or `price` field in a request
 * body is a 422 validation error, not a value silently accepted and ignored.
 */

import { IsInt, IsString, Min } from 'class-validator'

/** Body of `POST /api/cart/items`. */
export class AddCartItemRequest {
  @IsString()
  productId!: string

  @IsInt()
  @Min(1)
  quantity!: number
}

/**
 * Body of `PATCH /api/cart/items/:productId`.
 *
 * `quantity` has a floor of 1, not 0 like `CartRepository.setQuantity`, which
 * permits 0 to remove a line item. This route deliberately enforces the
 * stricter floor: removal is `DELETE /api/cart/items/:productId`, so a PATCH
 * to 0 is a 422 rather than a second spelling of delete a client could come to
 * rely on.
 */
export class SetCartItemQuantityRequest {
  @IsInt()
  @Min(1)
  quantity!: number
}
