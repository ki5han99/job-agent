from app.browser.client import BrowserClient
from app.config.models import Preferences, Profile
from app.jobs.field_mapper import map_field_to_value
from app.jobs.form_parser import FormField
from app.jobs.review_field_resolver import resolve_review_field


def fill_ready_fields(
    browser: BrowserClient,
    fields: list[FormField],
    profile: Profile,
    preferences: Preferences,
) -> None:
    if browser.page is None:
        raise RuntimeError("Browser has not been started.")

    for field in fields:
        mapping = map_field_to_value(
            field,
            profile,
        )

        # If the normal mapper cannot answer it,
        # try the review-field resolver.
        if mapping.status != "READY":
            resolved = resolve_review_field(
                field=field,
                profile=profile,
                preferences=preferences,
            )

            if resolved.status != "READY":
                continue

            value = resolved.value

        else:
            value = mapping.value

        if value is None:
            continue

        if field.field_id is None:
            continue

        element = browser.page.locator(
            f'[id="{field.field_id}"]'
        )

        if element.count() == 0:
            continue

        # Checkbox
        if field.field_type == "checkbox":
            element.check()
            continue

        # File upload
        if field.field_type == "file":
            element.set_input_files(value)
            continue

        # Native select
        if field.field_type == "select":
            element.select_option(
                label=value
            )
            continue

        # Custom Greenhouse combobox
        if field.role == "combobox":
            element.click()
            element.fill(value)

            option = browser.page.get_by_role(
                "option",
                name=value,
                exact=True,
            )

            if option.count() > 0:
                option.first.click()

            continue

        # Normal text fields
        if field.field_type in {
            "text",
            "tel",
            "email",
            "textarea",
        }:
            element.fill(value)