/**
 * initial schema
 *
 * Builds the catalogue schema — `category`, `product`, `review` — on an empty
 * database, reproducing `backend/alembic/versions/40ffd1e5ec7d_initial_schema.py`
 * column for column, index for index, constraint for constraint. The two
 * services keep separate migration ledgers (Alembic's `alembic_version` and
 * TypeORM's `typeorm_migrations`) over what is deliberately the same shape.
 *
 * Written by hand rather than generated: a generated migration reflects
 * whatever TypeORM's inference made of the entity decorators, which is a
 * moving target across versions, and the point of this file is that it agrees
 * with the Alembic revision.
 *
 * Primary keys, unique constraints and foreign keys are deliberately left
 * unnamed, so Postgres assigns its defaults — `product_pkey`,
 * `category_slug_key`, `product_category_id_fkey` — which is exactly what
 * Alembic produces for the same statements. Only the two check constraints are
 * named, because Alembic names those explicitly too. TypeORM would rather call
 * a foreign key `FK_<hash>`; matching Alembic is worth more than matching
 * TypeORM's convention, and `migration.spec.ts` pins both halves of that.
 *
 * See ADR-003: prices are integer minor units, never a float or
 * numeric-with-scale column, and Category is a real table so the filter UI can
 * be populated from data rather than a hardcoded list.
 */

import { MigrationInterface, QueryRunner } from 'typeorm'

export class InitialSchema1755600000000 implements MigrationInterface {
  name = 'InitialSchema1755600000000'

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`
      CREATE TABLE "category" (
        "id" SERIAL NOT NULL,
        "slug" character varying(80) NOT NULL,
        "label" character varying(120) NOT NULL,
        PRIMARY KEY ("id"),
        UNIQUE ("slug")
      )
    `)

    await queryRunner.query(`
      CREATE TABLE "product" (
        "id" SERIAL NOT NULL,
        "name" character varying(200) NOT NULL,
        "price_minor" integer NOT NULL,
        "currency" character varying(3) NOT NULL,
        "short_description" character varying(300) NOT NULL,
        "long_description" text NOT NULL,
        "thumbnail_url" character varying(500) NOT NULL,
        "category_id" integer NOT NULL,
        PRIMARY KEY ("id"),
        CONSTRAINT "ck_product_price_minor_non_negative" CHECK ("price_minor" >= 0),
        FOREIGN KEY ("category_id") REFERENCES "category" ("id") ON DELETE RESTRICT
      )
    `)
    await queryRunner.query(`CREATE INDEX "ix_product_category_id" ON "product" ("category_id")`)
    await queryRunner.query(`CREATE INDEX "ix_product_name" ON "product" ("name")`)

    await queryRunner.query(`
      CREATE TABLE "review" (
        "id" SERIAL NOT NULL,
        "product_id" integer NOT NULL,
        "author" character varying(120) NOT NULL,
        "rating" integer NOT NULL,
        "body" text NOT NULL,
        "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        PRIMARY KEY ("id"),
        CONSTRAINT "ck_review_rating_range" CHECK ("rating" BETWEEN 1 AND 5),
        FOREIGN KEY ("product_id") REFERENCES "product" ("id") ON DELETE CASCADE
      )
    `)
    await queryRunner.query(`CREATE INDEX "ix_review_product_id" ON "review" ("product_id")`)
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`DROP INDEX "ix_review_product_id"`)
    await queryRunner.query(`DROP TABLE "review"`)
    await queryRunner.query(`DROP INDEX "ix_product_name"`)
    await queryRunner.query(`DROP INDEX "ix_product_category_id"`)
    await queryRunner.query(`DROP TABLE "product"`)
    await queryRunner.query(`DROP TABLE "category"`)
  }
}
