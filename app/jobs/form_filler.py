from app.browser.client import BrowserClient
from app.config.models import Profile
from app.jobs.field_mapper import map_field_to_value
from app.jobs.form_parser import FormField


def fill_ready_fields(
    browser: BrowserClient,
    fields: list[FormField],
    profile: Profile,
) -> None:
    if browser.page is None:
        raise RuntimeError("Browser has not been started.")

    for field in fields:
        mapping = map_field_to_value(
            field,
            profile,
        )

        # Skip anything that still needs human review
        if mapping.status != "READY":
            continue

        # READY fields should have a value
        if mapping.value is None:
            continue

        # We currently locate fields by their HTML id
        if field.field_id is None:
            continue

        # Use an attribute selector instead of "#id".
        # This safely handles IDs containing characters like [ ].
        element = browser.page.locator(
            f'[id="{field.field_id}"]'
        )

        if element.count() == 0:
            continue

        # Checkbox / toggle
        if field.field_type == "checkbox":
            element.check()
            continue

        # File uploads, such as resume
        if field.field_type == "file":
            element.set_input_files(
                mapping.value
            )
            continue

        # Custom dropdown / combobox
        role = element.get_attribute("role")

        if role == "combobox":
            element.click()

            element.fill(
                mapping.value
            )

            option = browser.page.get_by_role(
                "option",
                name=mapping.value,
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
            element.fill(
                mapping.value
            )