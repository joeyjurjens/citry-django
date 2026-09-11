"""
What a component can read by name, inside a Citry region.

Django draws a line that this follows: a context processor is ambient - every
template Django renders has `user` and `LANGUAGE_CODE`, whatever called it - and
a view's own context is not, it belongs to the template it was rendered for.

So processors and the request reach a component's own template at any depth,
and the host's variables scope to the region they were written in.
"""

import pytest


@pytest.fixture
def request_with_user(rf):
    from django.contrib.auth.models import AnonymousUser

    request = rf.get("/hello/")
    request.user = AnonymousUser()
    return request


class TestInsideAComponentTemplate:
    """A component's own template, which is a scope of its own."""

    def test_the_request_resolves(self, component, render_django, request_with_user):
        component("<i>{{ request.path }}</i>", name="host-req")
        assert "/hello/" in render_django("<c-host-req/>", request=request_with_user)

    def test_a_context_processor_value_resolves(self, component, render_django, request_with_user):
        """`user` comes from `django.contrib.auth`'s processor and nowhere else."""
        component("<i>{{ user }}</i>", name="host-user")
        assert "AnonymousUser" in render_django("<c-host-user/>", request=request_with_user)

    def test_a_nested_component_gets_them_too(self, component, render_django, request_with_user):
        component("<i>{{ request.path }}|{{ user }}</i>", name="host-inner")
        component("<b><c-host-inner/></b>", name="host-outer")
        html = render_django("<c-host-outer/>", request=request_with_user)
        assert "/hello/" in html
        assert "AnonymousUser" in html

    def test_the_view_s_own_context_does_not_leak_in(self, component, render_django):
        """A component takes its inputs; the caller's variables are not among
        them, however convenient that would be."""
        component("<i>{{ thing }}</i>", name="host-leak")
        with pytest.raises(Exception, match="thing"):
            render_django("<c-host-leak/>", thing=42)


class TestInsideTheRegion:
    """The markup in the Django template itself, which is the caller's scope."""

    def test_a_host_variable_resolves(self, render_django):
        assert "42" in render_django("<c-element c-is=\"'i'\">{{ thing }}</c-element>", thing=42)


class TestProcessorsComeFromDjango:
    def test_they_arrive_without_a_request_context(self, component, request_with_user):
        """Asked for by name from the engine, so a host rendered without
        `RequestContext` has them too - a component cannot tell the difference
        and should not have to."""
        from django.template import Context, engines

        component("<i>{{ user }}</i>", name="host-plain")
        template = engines["citry"].from_string("<c-host-plain/>")
        assert "AnonymousUser" in template.template.render(Context({"request": request_with_user}))

    def test_none_of_them_without_a_request(self, component, render_django):
        component("<i>{{ user }}</i>", name="host-no-request")
        with pytest.raises(Exception, match="user"):
            render_django("<c-host-no-request/>")


def example_processor(request):
    """Stand-in for whatever a project adds to its own `context_processors`."""
    return {"site_motto": "everything Django has"}


class TestAnyProcessor:
    """Nothing here names a processor: the list comes from the engine, so a
    project's own arrives on the same footing as Django's."""

    def test_a_project_s_own_processor_reaches_a_component(
        self, component, render_django, request_with_user, settings
    ):
        first, *rest = settings.TEMPLATES
        options = first["OPTIONS"]
        # Assigning the setting itself is what resets Django's engine cache.
        settings.TEMPLATES = [
            {
                **first,
                "OPTIONS": {
                    **options,
                    "context_processors": [
                        *options["context_processors"],
                        "tests.test_host_context.example_processor",
                    ],
                },
            },
            *rest,
        ]
        component("<i>{{ site_motto }}</i>", name="host-custom")
        assert "everything Django has" in render_django(
            "<c-host-custom/>", request=request_with_user
        )


@pytest.fixture
def django_behavior(citry_app):
    """Switch the region to Django's context rule for one test."""
    extension = citry_app.extensions.get_extension("citry_django")
    extension.context_behavior = "django"
    try:
        yield
    finally:
        extension.context_behavior = "isolated"


class TestContextBehavior:
    """`isolated` is Citry's rule, `django` is Django's. Named after the
    django-components setting that does the same job."""

    def test_the_default_is_isolated(self):
        from citry_django import CitryDjangoExtension

        assert CitryDjangoExtension().context_behavior == "isolated"

    def test_an_unknown_value_is_refused(self):
        from citry_django import CitryDjangoExtension

        with pytest.raises(ValueError, match="context_behavior"):
            CitryDjangoExtension(context_behavior="whatever")

    def test_django_lets_a_component_read_the_view_s_context(
        self, django_behavior, component, render_django
    ):
        component("<i>{{ thing }}</i>", name="behave-django")
        assert "42" in render_django("<c-behave-django/>", thing=42)

    def test_a_component_s_own_name_still_wins(self, django_behavior, component, render_django):
        cls = component("<i>{{ thing }}</i>", name="behave-shadow")
        cls.template_data = lambda self, kwargs, slots: {"thing": "mine"}
        assert "mine" in render_django("<c-behave-shadow/>", thing=42)

    def test_a_nested_component_reads_it_too(self, django_behavior, component, render_django):
        component("<i>{{ thing }}</i>", name="behave-inner")
        component("<b><c-behave-inner/></b>", name="behave-outer")
        assert "42" in render_django("<c-behave-outer/>", thing=42)

    def test_isolated_keeps_it_out(self, component, render_django):
        component("<i>{{ thing }}</i>", name="behave-isolated")
        with pytest.raises(Exception, match="thing"):
            render_django("<c-behave-isolated/>", thing=42)

    def test_processors_arrive_in_isolated_too(self, component, render_django, request_with_user):
        """They are ambient in Django whatever the mode, so the setting does
        not reach them."""
        component("<i>{{ user }}</i>", name="behave-isolated-user")
        assert "AnonymousUser" in render_django(
            "<c-behave-isolated-user/>", request=request_with_user
        )
