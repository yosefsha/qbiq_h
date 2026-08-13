"""Generates the placeholder product thumbnails the storefront renders.

The catalogue sells digital goods under real product names, so real cover art
is not ours to ship. These are deliberately plain: a category-coloured panel,
the product's initials, and the category label. They exist so the storefront
demos with something other than a broken-image icon.

Run with `python scripts/generate_thumbnails.py`. Output is deterministic —
rerunning rewrites byte-identical files, so a regeneration is an empty diff
unless a product actually changed.

**Why `frontend/public/assets/thumbnails/` and not a repo-root directory
uploaded by hand.** Vite copies `public/` into `dist/` verbatim, so these ship
as part of the frontend build and both deploy paths upload them with no extra
step: `scripts/deploy-to-aws.sh` and `.github/workflows/deploy.yml` already run

    aws s3 sync frontend/dist/ "s3://$BUCKET/" --delete

Anything uploaded to the bucket *outside* that build is deleted by the next
deploy's `--delete`. Living inside `dist/` is what makes these permanent
without an exclude rule, a second sync, or a manual step anybody has to
remember.

`assets/` and not the bucket root for two reasons, both in
`infra/stacks/frontend_stack.py`: the `/assets/*` behavior already carries the
year-long immutable cache policy (`frontend_stack.py:183`), while the default
behavior is CACHING_DISABLED (`frontend_stack.py:171`) and would re-fetch every
thumbnail from S3 on every request. Both deploy paths invalidate `/*`
afterwards, so the long TTL never serves a stale thumbnail after a change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "frontend" / "public" / "assets" / "thumbnails"

#: Card art is rendered into a 16:9 box (`aspect-video` in `ProductCard.vue`).
WIDTH = 640
HEIGHT = 360

FONT_STACK = (
    "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)

#: qbiq's own tokens (see frontend/src/style.css for where they came from).
#: Every tile shares these; only ACCENTS varies.
CREAM = "#f7f7f7"
LINE = "#e4e4e4"
INK = "#151619"

#: One accent per category slug, so a tile says which shelf it is on before a
#: word of it is read — but with a single hue changing rather than three
#: unrelated ones. Three saturated gradients (indigo, teal, orange) said
#: "stock placeholder" precisely because no brand uses three unrelated hues at
#: equal weight; qbiq's palette is one blue against a grey ramp, and this
#: borrows that discipline.
ACCENTS: dict[str, str] = {
    "e-books": "#0040ff",  # --blue
    "software-licences": "#7d8ea2",  # --silver-grey
    "online-courses": "#1d1d20",  # --black-ii
}


@dataclass(frozen=True)
class Thumbnail:
    """One generated file: its name, its label, and the initials on it."""

    slug: str
    category_slug: str
    label: str
    initials: str


#: Slugs match the filenames the seed already referenced, so the seed change is
#: to the host and extension only, not to the identity of each file.
THUMBNAILS: tuple[Thumbnail, ...] = (
    Thumbnail("deep-work", "e-books", "E-Book", "DW"),
    Thumbnail("clean-architecture", "e-books", "E-Book", "CA"),
    Thumbnail("pragmatic-programmer", "e-books", "E-Book", "PP"),
    Thumbnail("atomic-habits", "e-books", "E-Book", "AH"),
    Thumbnail("pixelforge-studio", "software-licences", "Licence", "PF"),
    Thumbnail("taskflow-pro", "software-licences", "Licence", "TF"),
    Thumbnail("securevault", "software-licences", "Licence", "SV"),
    Thumbnail("codesight", "software-licences", "Licence", "CS"),
    Thumbnail("backend-fastapi-course", "online-courses", "Course", "PY"),
    Thumbnail("vue3-typescript-course", "online-courses", "Course", "VUE"),
    Thumbnail("aws-cdk-course", "online-courses", "Course", "AWS"),
    Thumbnail("sql-for-developers-course", "online-courses", "Course", "SQL"),
    # The twenty below exist so the catalogue is worth paging through: the
    # storefront asks for 12 per page, so twelve products never render a second
    # page. See the matching comment in backend/app/seed.py.
    Thumbnail("refactoring-field-guide", "e-books", "E-Book", "RF"),
    Thumbnail("distributed-systems-impatient", "e-books", "E-Book", "DS"),
    Thumbnail("debugging-systematic", "e-books", "E-Book", "DB"),
    Thumbnail("designing-data-contracts", "e-books", "E-Book", "DC"),
    Thumbnail("pragmatic-code-reviewer", "e-books", "E-Book", "CR"),
    Thumbnail("observability-first-principles", "e-books", "E-Book", "OB"),
    Thumbnail("writing-for-engineers", "e-books", "E-Book", "WE"),
    Thumbnail("querylens-profiler", "software-licences", "Licence", "QL"),
    Thumbnail("sentinel-log-viewer", "software-licences", "Licence", "SL"),
    Thumbnail("cascade-diagram-studio", "software-licences", "Licence", "CD"),
    Thumbnail("payload-api-client", "software-licences", "Licence", "PA"),
    Thumbnail("bastion-secrets-manager", "software-licences", "Licence", "BS"),
    Thumbnail("meridian-load-tester", "software-licences", "Licence", "ML"),
    Thumbnail("atlas-schema-migrator", "software-licences", "Licence", "AS"),
    Thumbnail("docker-compose-course", "online-courses", "Course", "DKR"),
    Thumbnail("testing-python-course", "online-courses", "Course", "TST"),
    Thumbnail("system-design-workshop", "online-courses", "Course", "SYS"),
    Thumbnail("terraform-production-course", "online-courses", "Course", "TF"),
    Thumbnail("redis-patterns-course", "online-courses", "Course", "RDS"),
    Thumbnail("accessible-frontend-course", "online-courses", "Course", "A11Y"),
)


def render(thumbnail: Thumbnail) -> str:
    """Returns the SVG source for one thumbnail.

    No `<title>` element: the card renders the product name as text directly
    below the image and marks the image decorative (`alt=""` in
    `ProductCard.vue`), so a title here would have a screen reader announce the
    same name twice.
    """
    accent = ACCENTS[thumbnail.category_slug]
    # Initials shrink as they lengthen, so "AWS" does not overrun the panel
    # that "DW" sits comfortably inside.
    initial_size = {1: 150, 2: 132, 3: 104}.get(len(thumbnail.initials), 88)
    # Flat fills and a hairline border rather than a gradient: qbiq's own
    # surfaces are flat, and a gradient is the single strongest tell that
    # artwork came from a placeholder generator.
    #
    # The glyph in the corner is the logo's geometry — rounded square, centred
    # circle — at tile scale, so a grid of these reads as one set rather than
    # as 32 unrelated images.
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}">
  <rect width="{WIDTH}" height="{HEIGHT}" fill="{CREAM}"/>
  <rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" fill="none" stroke="{LINE}"/>
  <g transform="translate(44 44)">
    <rect x="2" y="2" width="48" height="48" rx="11" fill="none" stroke="{accent}" stroke-width="4"/>
    <circle cx="26" cy="26" r="12" fill="{accent}"/>
  </g>
  <text x="{WIDTH // 2}" y="200" text-anchor="middle" font-family="{FONT_STACK}" font-size="{initial_size}" font-weight="700" fill="{INK}">{thumbnail.initials}</text>
  <rect x="{WIDTH // 2 - 28}" y="228" width="56" height="3" rx="1.5" fill="{accent}"/>
  <text x="{WIDTH // 2}" y="272" text-anchor="middle" font-family="{FONT_STACK}" font-size="19" font-weight="600" letter-spacing="6" fill="{accent}">{thumbnail.label.upper()}</text>
</svg>
"""


def main() -> None:
    """Writes every thumbnail in `THUMBNAILS` to `OUTPUT_DIR`."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for thumbnail in THUMBNAILS:
        path = OUTPUT_DIR / f"{thumbnail.slug}.svg"
        path.write_text(render(thumbnail), encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
