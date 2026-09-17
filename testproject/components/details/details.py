from citry import Component
from citry.ext.dependencies import Style
from django.templatetags.static import static

from testproject.citry_app import app


class Details(Component):
    """A component whose stylesheet sits beside it, the way one is written."""

    citry = app

    class Dependencies:
        css = [Style(url=static("details/details.scss"), attrs={"type": "text/x-scss"})]

    template = '<details class="theme-details"><summary>x</summary></details>'


app.register(Details, "details")
