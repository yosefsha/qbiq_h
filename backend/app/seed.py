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
    # --- Enough catalogue to page through --------------------------------
    # The twelve products above fit on a single page: the storefront asks for
    # `DEFAULT_LIMIT = 12` (frontend/src/catalogueQuery.ts), so a twelve-product
    # catalogue never renders a second page and the paging controls cannot be
    # demonstrated or eyeballed at all. Twenty more takes the catalogue to 32 —
    # three pages of 12, 12 and 8 — which exercises a first page, a middle page
    # and a short final page, the three cases paging gets wrong.
    #
    # Titles here are invented rather than borrowed. The originals use real book
    # names, and adding twenty more real ones would multiply a licensing
    # question the generated thumbnails were introduced to avoid.
    # --- E-Books ---------------------------------------------------------
    ProductSeed(
        name="The Refactoring Field Guide",
        price_minor=1299,
        currency="USD",
        short_description=(
            "Small, safe changes that leave code better than you found it."
        ),
        long_description=(
            "A catalogue of refactorings organised by the smell that motivates "
            "them, each with a worked before-and-after and the test that keeps "
            "it honest. DRM-free EPUB and PDF."
        ),
        thumbnail_url="/assets/thumbnails/refactoring-field-guide.svg",
        category_slug="e-books",
        reviews=(
            ReviewSeed(
                "Dana R.", 5, "The smell-first ordering makes it usable at work."
            ),
            ReviewSeed(
                "Tom H.", 4, "Wish the examples covered more than one language."
            ),
        ),
    ),
    ProductSeed(
        name="Distributed Systems for the Impatient",
        price_minor=1899,
        currency="USD",
        short_description=(
            "Consensus, replication and failure, without the maths degree."
        ),
        long_description=(
            "Explains why distributed systems fail the way they do — partial "
            "failure, clock skew, split brain — and what the standard answers "
            "actually cost. Diagrams over proofs throughout."
        ),
        thumbnail_url="/assets/thumbnails/distributed-systems-impatient.svg",
        category_slug="e-books",
        reviews=(
            ReviewSeed(
                "Priya N.", 5, "Finally understand quorums. Worth it for that alone."
            ),
        ),
    ),
    ProductSeed(
        name="Debugging: A Systematic Approach",
        price_minor=1199,
        currency="USD",
        short_description="Replace guessing with a method that converges on the cause.",
        long_description=(
            "A repeatable loop — reproduce, bisect, hypothesise, test — applied "
            "to memory corruption, race conditions, and the bugs that only "
            "appear in production."
        ),
        thumbnail_url="/assets/thumbnails/debugging-systematic.svg",
        category_slug="e-books",
        reviews=(
            ReviewSeed(
                "Marcus L.", 5, "The bisect chapter paid for the book twice over."
            ),
            ReviewSeed("Elena V.", 4, "Solid, if a little dry in the middle third."),
        ),
    ),
    ProductSeed(
        name="Designing Data Contracts",
        price_minor=1699,
        currency="USD",
        short_description="Schemas that survive the second team that depends on them.",
        long_description=(
            "Versioning, compatibility and deprecation for APIs and event "
            "streams, with the migration strategies that let a producer change "
            "without breaking consumers it has never met."
        ),
        thumbnail_url="/assets/thumbnails/designing-data-contracts.svg",
        category_slug="e-books",
        reviews=(
            ReviewSeed("Sofia K.", 4, "The deprecation playbook is the best part."),
        ),
    ),
    ProductSeed(
        name="The Pragmatic Code Reviewer",
        price_minor=999,
        currency="USD",
        short_description="Reviews that find defects without starting fights.",
        long_description=(
            "What to look for, what to leave alone, and how to write a comment "
            "that gets acted on. Includes checklists for security, concurrency "
            "and API changes."
        ),
        thumbnail_url="/assets/thumbnails/pragmatic-code-reviewer.svg",
        category_slug="e-books",
        reviews=(
            ReviewSeed("Ben A.", 5, "Changed the tone of our whole review culture."),
            ReviewSeed("Yuki T.", 4, "Short, which is the point."),
        ),
    ),
    ProductSeed(
        name="Observability from First Principles",
        price_minor=1599,
        currency="USD",
        short_description=(
            "Logs, metrics and traces, and when each one is the wrong tool."
        ),
        long_description=(
            "Builds up from a single request id to distributed tracing, with a "
            "hard look at cardinality, sampling and what an alert should mean "
            "before anyone is paged."
        ),
        thumbnail_url="/assets/thumbnails/observability-first-principles.svg",
        category_slug="e-books",
        reviews=(
            ReviewSeed(
                "Nadia F.", 5, "The chapter on alert fatigue should be mandatory."
            ),
        ),
    ),
    ProductSeed(
        name="Writing for Engineers",
        price_minor=899,
        currency="USD",
        short_description=(
            "Design docs, incident reports and commit messages that land."
        ),
        long_description=(
            "Technical writing aimed squarely at engineers: how to open a design "
            "doc so it gets read, how to write an incident report that teaches, "
            "and why the commit message is documentation."
        ),
        thumbnail_url="/assets/thumbnails/writing-for-engineers.svg",
        category_slug="e-books",
        reviews=(
            ReviewSeed(
                "Chris P.", 5, "My design docs get comments now instead of silence."
            ),
            ReviewSeed("Amara O.", 5, "Read it in a weekend, use it every week."),
        ),
    ),
    # --- Software Licences -----------------------------------------------
    ProductSeed(
        name="QueryLens Profiler",
        price_minor=8900,
        currency="USD",
        short_description="Find the slow query before your users do.",
        long_description=(
            "Attaches to Postgres and MySQL, samples live traffic, and ranks "
            "statements by total time rather than worst case. Single-developer "
            "licence, one year of updates."
        ),
        thumbnail_url="/assets/thumbnails/querylens-profiler.svg",
        category_slug="software-licences",
        reviews=(
            ReviewSeed("Jonas W.", 5, "Found an unindexed join costing us 40% of CPU."),
        ),
    ),
    ProductSeed(
        name="Sentinel Log Viewer",
        price_minor=4900,
        currency="USD",
        short_description="Structured log search that runs on your laptop.",
        long_description=(
            "Reads JSON logs from files, stdin or an S3 prefix, indexes them "
            "locally, and answers filter queries instantly. No agent, no server, "
            "nothing leaves the machine."
        ),
        thumbnail_url="/assets/thumbnails/sentinel-log-viewer.svg",
        category_slug="software-licences",
        reviews=(
            ReviewSeed("Ines G.", 4, "Replaced three shell aliases and a lot of grep."),
            ReviewSeed("Peter M.", 5, "The S3 mode is why I bought it."),
        ),
    ),
    ProductSeed(
        name="Cascade Diagram Studio",
        price_minor=6500,
        currency="USD",
        short_description="Architecture diagrams that stay in version control.",
        long_description=(
            "Text-first diagramming: describe the system, get a rendered "
            "diagram, and diff the source like any other file. Exports SVG and "
            "PNG at any scale."
        ),
        thumbnail_url="/assets/thumbnails/cascade-diagram-studio.svg",
        category_slug="software-licences",
        reviews=(
            ReviewSeed("Laura B.", 5, "Our diagrams are finally reviewable in PRs."),
        ),
    ),
    ProductSeed(
        name="Payload API Client",
        price_minor=3900,
        currency="USD",
        short_description="A REST and GraphQL client that keeps requests in the repo.",
        long_description=(
            "Collections are plain files you commit, so a request that "
            "reproduced a bug is still there next month. Environments, secrets "
            "from your keychain, and scripted assertions."
        ),
        thumbnail_url="/assets/thumbnails/payload-api-client.svg",
        category_slug="software-licences",
        reviews=(
            ReviewSeed("Owen D.", 4, "Committed collections are such an obvious idea."),
            ReviewSeed("Mei L.", 5, "Fast, and it doesn't want an account."),
        ),
    ),
    ProductSeed(
        name="Bastion Secrets Manager",
        price_minor=12900,
        currency="USD",
        short_description="Team secrets with an audit trail, self-hosted.",
        long_description=(
            "Encrypted at rest with per-environment keys, access scoped by "
            "team, and every read recorded. Runs as a single binary against "
            "Postgres. Five-seat licence."
        ),
        thumbnail_url="/assets/thumbnails/bastion-secrets-manager.svg",
        category_slug="software-licences",
        reviews=(
            ReviewSeed(
                "Tariq H.", 5, "Audit log satisfied our auditor on the first pass."
            ),
        ),
    ),
    ProductSeed(
        name="Meridian Load Tester",
        price_minor=7500,
        currency="USD",
        short_description="Load profiles that look like your actual traffic.",
        long_description=(
            "Replays production access patterns rather than hammering one "
            "endpoint, so the bottleneck it finds is the one you would have "
            "hit. Reports p50 through p99.9."
        ),
        thumbnail_url="/assets/thumbnails/meridian-load-tester.svg",
        category_slug="software-licences",
        reviews=(
            ReviewSeed("Greta S.", 4, "Traffic replay is worth the price on its own."),
            ReviewSeed("Hugo C.", 5, "Caught a connection-pool limit before launch."),
        ),
    ),
    ProductSeed(
        name="Atlas Schema Migrator",
        price_minor=5900,
        currency="USD",
        short_description="Reversible migrations with a dry run you can trust.",
        long_description=(
            "Plans every migration against a shadow database first and reports "
            "locks, rewrites and estimated duration before anything touches "
            "production."
        ),
        thumbnail_url="/assets/thumbnails/atlas-schema-migrator.svg",
        category_slug="software-licences",
        reviews=(
            ReviewSeed("Rafael Q.", 5, "The lock report stopped a very bad Friday."),
        ),
    ),
    # --- Online Courses --------------------------------------------------
    ProductSeed(
        name="Docker and Compose in Practice",
        price_minor=5900,
        currency="USD",
        short_description="Images, layers and Compose files that don't fight you.",
        long_description=(
            "Builds a multi-service application from an empty directory, "
            "covering multi-stage builds, layer caching, health checks and the "
            "differences that bite in production."
        ),
        thumbnail_url="/assets/thumbnails/docker-compose-course.svg",
        category_slug="online-courses",
        reviews=(
            ReviewSeed("Nils E.", 5, "Layer caching finally clicked."),
            ReviewSeed("Aisha R.", 4, "Good pace, assumes a little Linux."),
        ),
    ),
    ProductSeed(
        name="Testing Python at Scale",
        price_minor=6900,
        currency="USD",
        short_description="Fast suites, honest fixtures, and tests that stay green.",
        long_description=(
            "Pytest beyond the basics: fixture scope, parametrisation, "
            "test doubles that don't lie, and keeping a four-thousand-test suite "
            "under two minutes."
        ),
        thumbnail_url="/assets/thumbnails/testing-python-course.svg",
        category_slug="online-courses",
        reviews=(
            ReviewSeed("Lena M.", 5, "The section on flaky tests earned its keep."),
        ),
    ),
    ProductSeed(
        name="System Design Interview Workshop",
        price_minor=8900,
        currency="USD",
        short_description="Eight designs, whiteboarded end to end.",
        long_description=(
            "Works through eight systems — a URL shortener to a news feed — "
            "with the estimation, the trade-offs and the follow-up questions "
            "interviewers actually ask."
        ),
        thumbnail_url="/assets/thumbnails/system-design-workshop.svg",
        category_slug="online-courses",
        reviews=(
            ReviewSeed("Victor A.", 5, "Got the offer. The estimation drills did it."),
            ReviewSeed(
                "Hana J.", 4, "Two designs felt rushed, the rest were excellent."
            ),
        ),
    ),
    ProductSeed(
        name="Terraform to Production",
        price_minor=7900,
        currency="USD",
        short_description="State, modules and the blast radius of a plan.",
        long_description=(
            "Remote state and locking, module boundaries that survive a second "
            "environment, and reading a plan for the replacements it is quietly "
            "proposing."
        ),
        thumbnail_url="/assets/thumbnails/terraform-production-course.svg",
        category_slug="online-courses",
        reviews=(
            ReviewSeed("Kofi B.", 5, "'Read the plan' should be tattooed on everyone."),
        ),
    ),
    ProductSeed(
        name="Redis Patterns for Web Apps",
        price_minor=4900,
        currency="USD",
        short_description="Caching, sessions, queues — and their failure modes.",
        long_description=(
            "Each pattern paired with what happens when the node is lost: TTLs "
            "and eviction policies, cache stampedes, and why a queue on Redis "
            "needs more thought than it first appears."
        ),
        thumbnail_url="/assets/thumbnails/redis-patterns-course.svg",
        category_slug="online-courses",
        reviews=(
            ReviewSeed("Silvia D.", 5, "The eviction-policy lesson saved our carts."),
            ReviewSeed("Adam F.", 4, "Would like more on Cluster mode."),
        ),
    ),
    ProductSeed(
        name="Accessible Frontend Engineering",
        price_minor=6500,
        currency="USD",
        short_description="WCAG in practice, from semantics to focus management.",
        long_description=(
            "Keyboard navigation, focus traps, live regions and colour contrast, "
            "tested with real screen readers rather than an automated score."
        ),
        thumbnail_url="/assets/thumbnails/accessible-frontend-course.svg",
        category_slug="online-courses",
        reviews=(
            ReviewSeed(
                "Grace W.", 5, "Testing with an actual screen reader was eye-opening."
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
