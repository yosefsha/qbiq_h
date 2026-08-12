"""Tests for `app.seed` — the catalogue seed's idempotency.

These are integration tests against a real Postgres instance reached via
`DATABASE_URL` (ADR-003 rejects SQLite for dev/prod parity, and that parity
argument applies just as much to the seed as to application code). Each test
runs inside a SAVEPOINT nested in an outer transaction that is always rolled
back, so the seed's own `session.commit()` calls only release the savepoint
and never touch data outside the test.

Requires the `postgres` Docker Compose service to be running and reachable
at `DATABASE_URL`; see the project README / docker-compose.yml.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.models import Category, Product, Review
from app.db.session import engine
from app.seed import CATEGORY_SEEDS, PRODUCT_SEEDS, seed_catalogue


@pytest.fixture(name="session")
def session_fixture() -> Iterator[Session]:
    """A session bound to a savepoint inside a transaction that always rolls
    back, with pre-existing catalogue rows cleared for the duration of the
    test so counts reflect only what the seed itself inserts."""
    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"Postgres is not reachable at DATABASE_URL: {exc}")

    outer_transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    session.query(Review).delete()
    session.query(Product).delete()
    session.query(Category).delete()
    session.commit()

    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


def test_seed_loads_expected_products_categories_and_reviews(
    session: Session,
) -> None:
    """`Done when`: at least 12 products across at least 3 categories, each
    with reviews."""
    seed_catalogue(session)

    category_count = session.execute(text("select count(*) from category")).scalar_one()
    product_count = session.execute(text("select count(*) from product")).scalar_one()
    review_count = session.execute(text("select count(*) from review")).scalar_one()

    assert category_count >= 3
    assert product_count >= 12
    assert review_count > 0

    products_without_reviews = session.execute(
        text(
            "select count(*) from product p "
            "where not exists (select 1 from review r where r.product_id = p.id)"
        )
    ).scalar_one()
    assert products_without_reviews == 0


def test_seed_is_idempotent_on_row_counts(session: Session) -> None:
    """Rerunning the seed must not create duplicate rows."""
    seed_catalogue(session)

    category_count_first = session.execute(text("select count(*) from category")).scalar_one()
    product_count_first = session.execute(text("select count(*) from product")).scalar_one()
    review_count_first = session.execute(text("select count(*) from review")).scalar_one()

    seed_catalogue(session)

    category_count_second = session.execute(text("select count(*) from category")).scalar_one()
    product_count_second = session.execute(text("select count(*) from product")).scalar_one()
    review_count_second = session.execute(text("select count(*) from review")).scalar_one()

    assert category_count_second == category_count_first
    assert product_count_second == product_count_first
    assert review_count_second == review_count_first


def test_seed_is_idempotent_after_three_runs(session: Session) -> None:
    """Belt-and-braces: three runs settle at the same counts as one run."""
    for _ in range(3):
        seed_catalogue(session)

    assert session.query(Category).count() == len(CATEGORY_SEEDS)
    assert session.query(Product).count() == len(PRODUCT_SEEDS)

    for seed in PRODUCT_SEEDS:
        product = session.query(Product).filter_by(name=seed.name).one()
        assert len(product.reviews) == len(seed.reviews)


def test_seed_does_not_duplicate_categories_already_present(session: Session) -> None:
    """A category inserted out-of-band before the seed runs must not be
    duplicated by slug."""
    session.add(Category(slug="e-books", label="E-Books (pre-existing)"))
    session.commit()

    seed_catalogue(session)

    matching_categories = session.query(Category).filter_by(slug="e-books").all()
    assert len(matching_categories) == 1
    # The pre-existing row wins; the seed does not overwrite its label.
    assert matching_categories[0].label == "E-Books (pre-existing)"
