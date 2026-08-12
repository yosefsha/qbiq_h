"""Seeds the catalogue with a realistic set of digital products.

Run with `python -m app.seed`. Idempotent: rerunning it never creates
duplicate categories, products, or reviews — each entity is looked up by its
natural key (category `slug`, product `name`, review `(product, author)`)
before being inserted, and only missing rows are added.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db.models import Category, Product, Review
from app.db.session import SessionLocal


@dataclass(frozen=True)
class ReviewSeed:
    """One review to attach to a seeded product."""

    author: str
    rating: int
    body: str


@dataclass(frozen=True)
class ProductSeed:
    """One product to seed, together with its reviews."""

    name: str
    price_minor: int
    currency: str
    short_description: str
    long_description: str
    thumbnail_url: str
    category_slug: str
    reviews: tuple[ReviewSeed, ...] = field(default_factory=tuple)


CATEGORY_SEEDS: tuple[Category, ...] = (
    Category(slug="e-books", label="E-Books"),
    Category(slug="software-licences", label="Software Licences"),
    Category(slug="online-courses", label="Online Courses"),
)

PRODUCT_SEEDS: tuple[ProductSeed, ...] = (
    # --- E-Books -----------------------------------------------------
    ProductSeed(
        name="Deep Work: Rules for Focused Success",
        price_minor=1499,
        currency="USD",
        short_description=(
            "A practical guide to cultivating deep, distraction-free focus."
        ),
        long_description=(
            "Deep Work lays out a framework for training your ability to "
            "focus without distraction on cognitively demanding tasks. "
            "Delivered as a DRM-free EPUB and PDF, readable on any device, "
            "with lifetime access to future revisions."
        ),
        thumbnail_url="/assets/thumbnails/deep-work.svg",
        category_slug="e-books",
        reviews=(
            ReviewSeed(
                "Priya N.", 5, "Changed how I structure my mornings. Read it twice."
            ),
            ReviewSeed(
                "Marcus T.", 4, "Dense in places but the core argument is worth it."
            ),
        ),
    ),
    ProductSeed(
        name="Clean Architecture: A Craftsman's Guide",
        price_minor=2999,
        currency="USD",
        short_description=(
            "Software structure and design principles for maintainable systems."
        ),
        long_description=(
            "A guide to the architectural principles behind long-lived, "
            "testable software: boundaries, dependency rules, and the "
            "trade-offs between them. Includes downloadable diagrams and "
            "companion code samples in the EPUB package."
        ),
        thumbnail_url="/assets/thumbnails/clean-architecture.svg",
        category_slug="e-books",
        reviews=(
            ReviewSeed(
                "Dana K.", 5, "Reference-quality. I keep coming back to chapter 22."
            ),
            ReviewSeed("Owen R.", 4, "Some examples feel dated but the ideas hold up."),
            ReviewSeed(
                "Yuki S.", 5, "Best explanation of the dependency rule I've read."
            ),
        ),
    ),
    ProductSeed(
        name="The Pragmatic Programmer, 20th Anniversary Edition",
        price_minor=2499,
        currency="USD",
        short_description="Timeless, practical advice for software craftsmanship.",
        long_description=(
            "A fully revised edition covering topics from personal "
            "responsibility to architectural techniques, updated for "
            "modern development practices. Includes the original "
            "tips list as a quick-reference PDF insert."
        ),
        thumbnail_url="/assets/thumbnails/pragmatic-programmer.svg",
        category_slug="e-books",
        reviews=(
            ReviewSeed(
                "Leah B.", 5, "Every developer should read this early in their career."
            ),
        ),
    ),
    ProductSeed(
        name="Atomic Habits",
        price_minor=1299,
        currency="USD",
        short_description=(
            "An easy and proven way to build good habits and break bad ones."
        ),
        long_description=(
            "A practical framework for improving daily habits, built "
            "around the four laws of behaviour change. Delivered as EPUB, "
            "MOBI, and PDF with an accompanying habit-tracking template."
        ),
        thumbnail_url="/assets/thumbnails/atomic-habits.svg",
        category_slug="e-books",
        reviews=(
            ReviewSeed("Grace P.", 5, "Simple, actionable, and it actually stuck."),
            ReviewSeed("Tomas V.", 3, "Good ideas but repetitive by the last third."),
        ),
    ),
    # --- Software Licences --------------------------------------------
    ProductSeed(
        name="PixelForge Studio — 1-Year Licence",
        price_minor=8900,
        currency="USD",
        short_description="Professional raster and vector image editing suite.",
        long_description=(
            "A full-featured image editor for photo retouching, vector "
            "illustration, and layered compositing. This licence covers "
            "one seat for twelve months, including all point releases and "
            "priority email support."
        ),
        thumbnail_url="/assets/thumbnails/pixelforge-studio.svg",
        category_slug="software-licences",
        reviews=(
            ReviewSeed(
                "Ines M.",
                5,
                "Genuinely rivals the big-name editors at a third of the price.",
            ),
            ReviewSeed(
                "Carlos D.", 4, "Great value; the plugin ecosystem is still growing."
            ),
        ),
    ),
    ProductSeed(
        name="TaskFlow Pro — Lifetime Licence",
        price_minor=6900,
        currency="USD",
        short_description="Project and task management for small teams.",
        long_description=(
            "A lifetime licence for TaskFlow Pro, covering unlimited "
            "projects, Gantt views, and up to ten team seats. One-time "
            "payment, no recurring fees, includes all future major "
            "versions."
        ),
        thumbnail_url="/assets/thumbnails/taskflow-pro.svg",
        category_slug="software-licences",
        reviews=(
            ReviewSeed(
                "Wendy A.", 5, "Paid once two years ago, still gets free updates."
            ),
            ReviewSeed(
                "Sam O.", 4, "Solid, though the mobile app lags behind desktop."
            ),
        ),
    ),
    ProductSeed(
        name="SecureVault Password Manager — 2-Year Licence",
        price_minor=3499,
        currency="USD",
        short_description="Encrypted password and secrets manager for individuals.",
        long_description=(
            "End-to-end encrypted vault for passwords, passkeys, and "
            "secure notes, with browser extensions for every major "
            "browser and biometric unlock on mobile. Two-year single-user "
            "licence, key delivered by email immediately after purchase."
        ),
        thumbnail_url="/assets/thumbnails/securevault.svg",
        category_slug="software-licences",
        reviews=(
            ReviewSeed(
                "Hana J.",
                5,
                "Migration from my old manager took ten minutes, flawless since.",
            ),
        ),
    ),
    ProductSeed(
        name="CodeSight Static Analyzer — Team Licence",
        price_minor=14900,
        currency="USD",
        short_description="Static analysis and linting for polyglot codebases.",
        long_description=(
            "A static analysis suite covering Python, TypeScript, and Go, "
            "with CI integration and a shared dashboard. Team licence for "
            "up to fifteen developers, renewed annually with this key."
        ),
        thumbnail_url="/assets/thumbnails/codesight.svg",
        category_slug="software-licences",
        reviews=(
            ReviewSeed(
                "Petra L.",
                4,
                "Caught real bugs in week one. CI plugin setup was fiddly.",
            ),
            ReviewSeed(
                "Amir F.", 5, "Dashboard makes triaging findings across repos painless."
            ),
        ),
    ),
    # --- Online Courses -------------------------------------------------
    ProductSeed(
        name="Backend Engineering with Python & FastAPI",
        price_minor=4999,
        currency="USD",
        short_description="Build and deploy production APIs with FastAPI.",
        long_description=(
            "A project-based course covering FastAPI fundamentals, "
            "SQLAlchemy, Alembic migrations, and deployment to a "
            "containerized cloud environment. Includes lifetime access "
            "and downloadable source code for every module."
        ),
        thumbnail_url="/assets/thumbnails/backend-fastapi-course.svg",
        category_slug="online-courses",
        reviews=(
            ReviewSeed(
                "Noor H.", 5, "The migrations module alone was worth the price."
            ),
            ReviewSeed("Ben C.", 5, "Clear pacing, real projects, no filler."),
        ),
    ),
    ProductSeed(
        name="Vue 3 & TypeScript: From Fundamentals to Production",
        price_minor=5499,
        currency="USD",
        short_description="Composition API, TypeScript, and Vite in a single track.",
        long_description=(
            "Covers the Composition API, typed props and emits, Pinia "
            "state management, and a full production build pipeline with "
            "Vite. Includes quizzes, a capstone project, and a completion "
            "certificate."
        ),
        thumbnail_url="/assets/thumbnails/vue3-typescript-course.svg",
        category_slug="online-courses",
        reviews=(
            ReviewSeed(
                "Elif K.", 4, "Great structure; wish there were more on testing."
            ),
            ReviewSeed(
                "Diego R.", 5, "Finally a course that treats TypeScript as first-class."
            ),
        ),
    ),
    ProductSeed(
        name="AWS for Backend Engineers: CDK in Practice",
        price_minor=6499,
        currency="USD",
        short_description="Infrastructure as code on AWS using the Python CDK.",
        long_description=(
            "Hands-on modules building VPCs, ECS Fargate services, RDS "
            "instances, and CI/CD pipelines with AWS CDK in Python. Ends "
            "with a capstone deploying a full three-tier application."
        ),
        thumbnail_url="/assets/thumbnails/aws-cdk-course.svg",
        category_slug="online-courses",
        reviews=(
            ReviewSeed(
                "Fatima Z.", 5, "Took this straight into a real project the same week."
            ),
        ),
    ),
    ProductSeed(
        name="SQL for Application Developers",
        price_minor=3999,
        currency="USD",
        short_description="Practical, index-aware SQL for building real applications.",
        long_description=(
            "Covers query design, indexing strategy, transactions, and "
            "common pitfalls when an ORM sits between you and the "
            "database. Exercises run against a real Postgres instance "
            "provided in the browser sandbox."
        ),
        thumbnail_url="/assets/thumbnails/sql-for-developers-course.svg",
        category_slug="online-courses",
        reviews=(
            ReviewSeed(
                "Ravi S.", 4, "The indexing chapter changed how I write queries."
            ),
            ReviewSeed(
                "Claire M.", 5, "Best SQL course I've taken, and I've taken a few."
            ),
        ),
    ),
)


class CatalogueSeeder:
    """Idempotently loads `CATEGORY_SEEDS` and `PRODUCT_SEEDS` into Postgres."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def run(self) -> None:
        """Seeds categories, then products, then reviews, committing once."""
        categories_by_slug = self._seed_categories()
        self._seed_products(categories_by_slug)
        self._session.commit()

    def _seed_categories(self) -> dict[str, Category]:
        """Inserts any category from `CATEGORY_SEEDS` missing by `slug`."""
        existing = {
            category.slug: category for category in self._session.query(Category).all()
        }
        for seed in CATEGORY_SEEDS:
            if seed.slug in existing:
                continue
            category = Category(slug=seed.slug, label=seed.label)
            self._session.add(category)
            existing[seed.slug] = category
        self._session.flush()
        return existing

    def _seed_products(self, categories_by_slug: dict[str, Category]) -> None:
        """Inserts any product from `PRODUCT_SEEDS` missing by `name`, along
        with any of its reviews missing by `(product, author)`, and reconciles
        `thumbnail_url` on products that already exist."""
        existing_products = {
            product.name: product for product in self._session.query(Product).all()
        }
        for seed in PRODUCT_SEEDS:
            product = existing_products.get(seed.name)
            if product is None:
                product = Product(
                    name=seed.name,
                    price_minor=seed.price_minor,
                    currency=seed.currency,
                    short_description=seed.short_description,
                    long_description=seed.long_description,
                    thumbnail_url=seed.thumbnail_url,
                    category=categories_by_slug[seed.category_slug],
                )
                self._session.add(product)
                self._session.flush()
                existing_products[seed.name] = product
            elif product.thumbnail_url != seed.thumbnail_url:
                # Insert-only was not enough. Every seeded product pointed at
                # `https://cdn.qbiq.dev/products/<slug>.jpg` — a host that does
                # not exist — so a database seeded before that was fixed holds
                # twelve dead URLs, and a re-seed that only inserts leaves every
                # one of them in place. It looks like it worked on a fresh
                # database while doing nothing to the environment that has the
                # problem.
                #
                # Only `thumbnail_url` is reconciled, deliberately. Prices,
                # descriptions and reviews are things a demo may have edited in
                # place, and a seed run is not a mandate to revert them; the
                # thumbnail is the one field whose seeded value is authoritative
                # because it names a file this repository ships.
                product.thumbnail_url = seed.thumbnail_url

            existing_authors = {review.author for review in product.reviews}
            for review_seed in seed.reviews:
                if review_seed.author in existing_authors:
                    continue
                self._session.add(
                    Review(
                        product=product,
                        author=review_seed.author,
                        rating=review_seed.rating,
                        body=review_seed.body,
                    )
                )


def seed_catalogue(session: Session) -> None:
    """Runs `CatalogueSeeder` against the given session."""
    CatalogueSeeder(session).run()


def main() -> None:
    """Entry point for `python -m app.seed`."""
    with SessionLocal() as session:
        seed_catalogue(session)


if __name__ == "__main__":
    main()
