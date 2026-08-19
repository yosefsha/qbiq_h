/**
 * Query parameters for `GET /api/products`.
 *
 * The bounds live here so an out-of-range page is a 422 before any handler
 * runs, matching the Python service where FastAPI's `Query(ge=..., le=...)`
 * does the same job. Note `limit` is rejected above `MAX_PAGE_SIZE` rather
 * than clamped: a client paging with a too-large limit should learn it is
 * doing so instead of quietly getting short pages.
 */

import { Type } from 'class-transformer'
import { IsEnum, IsInt, IsOptional, IsString, Max, Min } from 'class-validator'

import { MAX_PAGE_SIZE, SortDirection, SortKey } from '../../domain/catalog'

export class ListProductsQuery {
  /** Case-insensitive substring match on product name. */
  @IsOptional()
  @IsString()
  name?: string

  /** Category slug to filter by. An unknown slug is a 422, not an empty page. */
  @IsOptional()
  @IsString()
  category?: string

  @IsOptional()
  @IsEnum(SortKey)
  sort?: SortKey

  @IsOptional()
  @IsEnum(SortDirection)
  direction?: SortDirection

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(0)
  @Max(MAX_PAGE_SIZE)
  limit?: number

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(0)
  offset?: number
}
