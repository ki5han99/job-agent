from pydantic import BaseModel

from app.browser.client import BrowserClient


class FormField(BaseModel):
    label: str
    field_type: str
    name: str | None
    field_id: str | None
    required: bool


def parse_form_fields(browser: BrowserClient) -> list[FormField]:
    if browser.page is None:
        raise RuntimeError("Browser has not been started.")

    fields: list[FormField] = []

    elements = browser.page.locator(
        "input, textarea, select"
    )

    for i in range(elements.count()):
        element = elements.nth(i)

        # Ignore invisible/internal form elements
        if not element.is_visible():
            continue

        name = element.get_attribute("name")
        field_id = element.get_attribute("id")

        # Ignore CAPTCHA fields
        if name == "g-recaptcha-response":
            continue

        field_type = (
            element.get_attribute("type")
            or element.evaluate(
                "(el) => el.tagName.toLowerCase()"
            )
        )

        # Ignore search boxes used inside dropdowns
        if field_type == "search":
            continue

        required = (
            element.get_attribute("required") is not None
            or element.get_attribute("aria-required") == "true"
        )

        label = element.get_attribute("aria-label") or ""

        if not label and field_id:
            label_element = browser.page.locator(
                f'label[for="{field_id}"]'
            )

            if label_element.count() > 0:
                label = label_element.first.inner_text()

        fields.append(
            FormField(
                label=label.strip(),
                field_type=field_type,
                name=name,
                field_id=field_id,
                required=required,
            )
        )

    return fields