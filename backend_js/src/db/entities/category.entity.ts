/**
 * Persistence-layer entities for the catalogue schema.
 *
 * These intentionally do not reference the domain types in `src/domain` —
 * mapping between the two layers belongs to the repository implementation.
 * Column names, lengths, indexes and constraints match
 * `backend/alembic/versions/40ffd1e5ec7d_initial_schema.py` exactly, so both
 * services can be pointed at a database built by either migration.
 *
 * Prices are stored as integer minor units (`price_minor`) plus a `currency`
 * code, never as a float or a numeric-with-scale column, per ADR-003.
 */

import { Column, Entity, OneToMany, PrimaryGeneratedColumn } from 'typeorm'

import { ProductEntity } from './product.entity'

/** The kind of digital good a Product is. Every Product has exactly one. */
@Entity({ name: 'category' })
export class CategoryEntity {
  @PrimaryGeneratedColumn({ type: 'integer' })
  id!: number

  @Column({ type: 'varchar', length: 80, unique: true, nullable: false })
  slug!: string

  /**
   * The human-readable name. Called `label` in the schema and `name` in the
   * domain; `SqlProductRepository` is the single place that crosses that
   * naming boundary.
   */
  @Column({ type: 'varchar', length: 120, nullable: false })
  label!: string

  @OneToMany(() => ProductEntity, (product) => product.category)
  products!: ProductEntity[]
}
