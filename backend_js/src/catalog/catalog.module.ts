import { Module } from '@nestjs/common'

import { ProductCatalogService } from './product-catalog.service'
import { ProductsController } from './products.controller'

/** The catalogue half of the API: products and categories. */
@Module({
  controllers: [ProductsController],
  providers: [ProductCatalogService],
})
export class CatalogModule {}
