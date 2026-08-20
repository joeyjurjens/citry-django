from django.contrib import admin
from django.urls import include, path
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls
from wagtail.images.views.serve import ServeView

urlpatterns = [
    # Wagtail's image-serve view, which `{% image_url %}` generates URLs for.
    path(
        "images/<str:signature>/<int:image_id>/<str:filter_spec>/",
        ServeView.as_view(),
        name="wagtailimages_serve",
    ),
    path("django-admin/", admin.site.urls),
    path("admin/", include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    path("", include(wagtail_urls)),
]
