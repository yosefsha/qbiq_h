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


@dataclass(frozen=True)
class Palette:
    """The two gradient stops a category's thumbnails are painted with."""

    start: str
    end: str


#: One palette per category slug, so a card's colour says which shelf it is on
#: before a word of it is read.
PALETTES: dict[str, Palette] = {
    "e-books": Palette("#4f46e5", "#312e81"),
    "software-licences": Palette("#0d9488", "#134e4a"),
    "online-courses": Palette("#c2410c", "#7c2d12"),
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
)


def render(thumbnail: Thumbnail) -> str:
    """Returns the SVG source for one thumbnail.

    No `<title>` element: the card renders the product name as text directly
    below the image and marks the image decorative (`alt=""` in
    `ProductCard.vue`), so a title here would have a screen reader announce the
    same name twice.
    """
    palette = PALETTES[thumbnail.category_slug]
    # Initials shrink as they lengthen, so "AWS" does not overrun the panel
    # that "DW" sits comfortably inside.
    initial_size = {1: 150, 2: 132, 3: 104}.get(len(thumbnail.initials), 88)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{palette.start}"/>
      <stop offset="1" stop-color="{palette.end}"/>
    </linearGradient>
  </defs>
  <rect width="{WIDTH}" height="{HEIGHT}" fill="url(#bg)"/>
  <rect x="40" y="40" width="{WIDTH - 80}" height="{HEIGHT - 80}" rx="12" fill="none" stroke="#ffffff" stroke-opacity="0.22" stroke-width="2"/>
  <text x="{WIDTH // 2}" y="196" text-anchor="middle" font-family="{FONT_STACK}" font-size="{initial_size}" font-weight="700" fill="#ffffff" fill-opacity="0.95">{thumbnail.initials}</text>
  <text x="{WIDTH // 2}" y="256" text-anchor="middle" font-family="{FONT_STACK}" font-size="20" font-weight="600" letter-spacing="6" fill="#ffffff" fill-opacity="0.75">{thumbnail.label.upper()}</text>
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
