import {
  Check,
  Column,
  CreateDateColumn,
  Entity,
  Index,
  JoinColumn,
  ManyToOne,
  PrimaryGeneratedColumn,
} from 'typeorm'

import { ProductEntity } from './product.entity'

/** A shopper's written verdict on a Product. */
@Entity({ name: 'review' })
@Check('ck_review_rating_range', 'rating BETWEEN 1 AND 5')
export class ReviewEntity {
  @PrimaryGeneratedColumn({ type: 'integer' })
  id!: number

  @Index('ix_review_product_id')
  @Column({ name: 'product_id', type: 'integer', nullable: false })
  productId!: number

  @ManyToOne(() => ProductEntity, (product) => product.reviews, {
    onDelete: 'CASCADE',
    nullable: false,
  })
  @JoinColumn({ name: 'product_id' })
  product!: ProductEntity

  @Column({ type: 'varchar', length: 120, nullable: false })
  author!: string

  @Column({ type: 'integer', nullable: false })
  rating!: number

  @Column({ type: 'text', nullable: false })
  body!: string

  @CreateDateColumn({
    name: 'created_at',
    type: 'timestamptz',
    nullable: false,
    default: () => 'now()',
  })
  createdAt!: Date
}
