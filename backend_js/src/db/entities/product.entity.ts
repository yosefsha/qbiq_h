import {
  Check,
  Column,
  Entity,
  Index,
  JoinColumn,
  ManyToOne,
  OneToMany,
  PrimaryGeneratedColumn,
} from 'typeorm'

import { CategoryEntity } from './category.entity'
import { ReviewEntity } from './review.entity'

/**
 * A digital good offered for sale — an e-book, a software licence, or an
 * online course.
 */
@Entity({ name: 'product' })
@Check('ck_product_price_minor_non_negative', 'price_minor >= 0')
export class ProductEntity {
  @PrimaryGeneratedColumn({ type: 'integer' })
  id!: number

  @Index('ix_product_name')
  @Column({ type: 'varchar', length: 200, nullable: false })
  name!: string

  /** Integer minor units (e.g. cents). Never a float — see ADR-003. */
  @Column({ name: 'price_minor', type: 'integer', nullable: false })
  priceMinor!: number

  @Column({ type: 'varchar', length: 3, nullable: false })
  currency!: string

  @Column({ name: 'short_description', type: 'varchar', length: 300, nullable: false })
  shortDescription!: string

  @Column({ name: 'long_description', type: 'text', nullable: false })
  longDescription!: string

  @Column({ name: 'thumbnail_url', type: 'varchar', length: 500, nullable: false })
  thumbnailUrl!: string

  @Index('ix_product_category_id')
  @Column({ name: 'category_id', type: 'integer', nullable: false })
  categoryId!: number

  @ManyToOne(() => CategoryEntity, (category) => category.products, {
    onDelete: 'RESTRICT',
    nullable: false,
  })
  @JoinColumn({ name: 'category_id' })
  category!: CategoryEntity

  @OneToMany(() => ReviewEntity, (review) => review.product, { cascade: false })
  reviews!: ReviewEntity[]
}
