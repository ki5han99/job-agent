from pydantic import BaseModel

from app.browser.client import BrowserClient


class FormField(BaseModel):
    label: str
    field_type: str
    name: str | None
    field_id: str | None
    role: str | None
    required: bool


def parse_form_fields(
    browser: BrowserClient,
) -> list[FormField]:
    if browser.page is None:
        raise RuntimeError("Browser has not been started.")

    fields: list[FormField] = []

    elements = browser.page.locator(
        "input, textarea, select"
    )

    for i in range(elements.count()):
        element = elements.nth(i)

        # Skip hidden/internal elements
        if not element.is_visible():
            continue

        name = element.get_attribute("name")
        field_id = element.get_attribute("id")
        role = element.get_attribute("role")

        # Ignore CAPTCHA infrastructure
        if name == "g-recaptcha-response":
            continue

        field_type = (
            element.get_attribute("type")
            or element.evaluate(
                "(el) => el.tagName.toLowerCase()"
            )
        )

        # Ignore search boxes used inside dropdown widgets
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

        # React Select's required validation proxy is visually measurable, but
        # is not a second question. Only omit it if its real widget was parsed.
        if (
            not field_id and not label.strip() and not role
            and element.get_attribute("aria-hidden") == "true"
            and element.get_attribute("tabindex") == "-1"
        ):
            companion_id = element.evaluate("""el => {
                const shell = el.closest('.select-shell');
                const combos = shell ? shell.querySelectorAll('[role="combobox"][id]') : [];
                return combos.length === 1 ? combos[0].id : null;
            }""")
            if companion_id and any(
                field.field_id == companion_id and field.role == "combobox" and field.label
                for field in fields
            ):
                continue

        fields.append(
            FormField(
                label=label.strip(),
                field_type=field_type,
                name=name,
                field_id=field_id,
                role=role,
                required=required,
            )
        )

    return fields
