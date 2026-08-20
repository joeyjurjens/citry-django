"""
Content for the demo site and for the end-to-end tests.

Real content matters here: `{% image %}` needs an actual Image with a real file
to generate a rendition from, and `{% pageurl %}` needs pages that are really in
the tree.
"""

from __future__ import annotations

import io

ARTICLES = [
    ("Deploying on Friday", True),
    ("A quieter changelog", False),
    ("Tag interop", True),
]


def _png(width: int = 800, height: int = 400) -> io.BytesIO:
    """A minimal valid PNG, built without needing an asset on disk."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (40, 90, 160)).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def seed() -> dict:
    """Build the site and return the objects a test needs to assert against."""
    from django.core.files.images import ImageFile
    from wagtail.images.models import Image
    from wagtail.models import Page, Site

    from testproject.home.models import ArticlePage, HomePage

    root = Page.objects.get(depth=1)
    HomePage.objects.all().delete()
    Page.objects.filter(slug="home", depth=2).delete()

    image = Image.objects.filter(title="Hero").first()
    if image is None:
        image = Image(title="Hero")
        image.file.save("hero.png", ImageFile(_png(), name="hero.png"), save=False)
        image.save()

    home = HomePage(
        title="Citry + Wagtail",
        slug="home",
        intro="<p>An <b>existing</b> Wagtail site, migrating one region at a time.</p>",
        hero_image=image,
    )
    root.add_child(instance=home)
    home.save_revision().publish()

    site = Site.objects.first()
    if site is None:
        Site.objects.create(hostname="localhost", port=80, root_page=home, is_default_site=True)
    else:
        site.root_page = home
        site.hostname = "localhost"
        site.port = 80
        site.is_default_site = True
        site.save()

    articles = []
    for index, (title, featured) in enumerate(ARTICLES):
        article = ArticlePage(
            title=title,
            slug=f"article-{index}",
            summary=f"Summary for {title.lower()}.",
            # The `linktype="page"` anchor is stored as an internal reference.
            # Only Wagtail's `richtext` filter expands it into a real URL, so
            # its presence in the output proves the filter actually ran.
            body=(
                f"<p>Body of <i>{title}</i>.</p>"
                f'<p><a linktype="page" id="{home.pk}">Back home</a></p>'
            ),
            featured=featured,
            body_stream=[
                ("heading", f"Heading for {title}"),
                ("paragraph", "<p>A <b>streamed</b> paragraph.</p>"),
                ("image", image),
            ],
        )
        home.add_child(instance=article)
        article.save_revision().publish()
        articles.append(article)

    return {"home": home, "image": image, "articles": articles}


if __name__ == "__main__":
    import django

    django.setup()
    result = seed()
    print(f"Seeded: home={result['home'].url!r}, articles={len(result['articles'])}")
