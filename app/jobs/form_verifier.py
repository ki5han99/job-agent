from pathlib import Path

from pydantic import BaseModel

from app.browser.client import BrowserClient
from app.jobs.form_parser import FormField


class FieldVerification(BaseModel):
    field_id: str | None
    label: str
    expected_value: str | None
    actual_value: str | None
    status: str


def verify_field(
    browser: BrowserClient,
    field: FormField,
    expected_value: str,
) -> FieldVerification:
    if browser.page is None:
        raise RuntimeError("Browser has not been started.")

    if field.field_id is None:
        return FieldVerification(
            field_id=None,
            label=field.label,
            expected_value=expected_value,
            actual_value=None,
            status="UNVERIFIED",
        )

    element = browser.page.locator(
        f'[id="{field.field_id}"]'
    )

    # -------------------------------------------------
    # Greenhouse phone-country widget
    # -------------------------------------------------
    if (
        field.field_id == "country"
        and field.role == "combobox"
    ):
        if element.count() == 0:
            return FieldVerification(
                field_id=field.field_id,
                label=field.label,
                expected_value=expected_value,
                actual_value=None,
                status="NOT_FOUND",
            )

        try:
            value_container = element.locator(
                "xpath=../.."
            )

            single_value = value_container.locator(
                ".select__single-value"
            )

            if single_value.count() == 0:
                return FieldVerification(
                    field_id=field.field_id,
                    label=field.label,
                    expected_value=expected_value,
                    actual_value=None,
                    status="FAILED",
                )

            visible_text = (
                single_value
                .inner_text()
                .strip()
            )

            flag = single_value.locator(
                ".iti__flag"
            )

            flag_class = ""

            if flag.count() > 0:
                flag_class = (
                    flag
                    .first
                    .get_attribute("class")
                    or ""
                )

            if expected_value.lower() in {
                "united states",
                "united states of america",
                "usa",
                "us",
            }:
                if "iti__us" in flag_class:
                    return FieldVerification(
                        field_id=field.field_id,
                        label=field.label,
                        expected_value=expected_value,
                        actual_value=(
                            f"United States {visible_text}"
                        ),
                        status="VERIFIED",
                    )

            combined_value = (
                f"{flag_class} {visible_text}"
            ).strip()

            status = (
                "VERIFIED"
                if expected_value.lower()
                in combined_value.lower()
                else "FAILED"
            )

            return FieldVerification(
                field_id=field.field_id,
                label=field.label,
                expected_value=expected_value,
                actual_value=combined_value,
                status=status,
            )

        except Exception:
            return FieldVerification(
                field_id=field.field_id,
                label=field.label,
                expected_value=expected_value,
                actual_value=None,
                status="UNVERIFIED",
            )

    # -------------------------------------------------
    # File upload
    # -------------------------------------------------
    if field.field_type == "file":
        expected_filename = Path(
            expected_value
        ).name

        # First try the original input if it still exists
        if element.count() > 0:
            try:
                files = element.evaluate(
                    """
                    el => Array.from(
                        el.files || []
                    ).map(file => file.name)
                    """
                )

                if files:
                    actual_value = files[0]

                    return FieldVerification(
                        field_id=field.field_id,
                        label=field.label,
                        expected_value=expected_filename,
                        actual_value=actual_value,
                        status=(
                            "VERIFIED"
                            if actual_value
                            == expected_filename
                            else "FAILED"
                        ),
                    )

            except Exception:
                pass

        # Greenhouse may replace/hide the file input
        # after upload. Look for the uploaded filename
        # anywhere in the visible page.
        filename_match = browser.page.get_by_text(
            expected_filename,
            exact=False,
        )

        if filename_match.count() > 0:
            return FieldVerification(
                field_id=field.field_id,
                label=field.label,
                expected_value=expected_filename,
                actual_value=expected_filename,
                status="VERIFIED",
            )

        # Fallback: inspect all file inputs still present
        file_inputs = browser.page.locator(
            'input[type="file"]'
        )

        for i in range(file_inputs.count()):
            current = file_inputs.nth(i)

            try:
                files = current.evaluate(
                    """
                    el => Array.from(
                        el.files || []
                    ).map(file => file.name)
                    """
                )

                if expected_filename in files:
                    return FieldVerification(
                        field_id=field.field_id,
                        label=field.label,
                        expected_value=expected_filename,
                        actual_value=expected_filename,
                        status="VERIFIED",
                    )

            except Exception:
                continue

        return FieldVerification(
            field_id=field.field_id,
            label=field.label,
            expected_value=expected_filename,
            actual_value=None,
            status="FAILED",
        )

    # -------------------------------------------------
    # Normal element lookup
    # -------------------------------------------------
    if element.count() == 0:
        return FieldVerification(
            field_id=field.field_id,
            label=field.label,
            expected_value=expected_value,
            actual_value=None,
            status="NOT_FOUND",
        )

    # -------------------------------------------------
    # Checkbox
    # -------------------------------------------------
    if field.field_type == "checkbox":
        checked = element.is_checked()

        actual_value = (
            "true"
            if checked
            else "false"
        )

        expected_checked = (
            expected_value.lower()
            in {
                "true",
                "yes",
                "1",
            }
        )

        status = (
            "VERIFIED"
            if checked == expected_checked
            else "FAILED"
        )

        return FieldVerification(
            field_id=field.field_id,
            label=field.label,
            expected_value=expected_value,
            actual_value=actual_value,
            status=status,
        )

    if field.field_type == "select":
        try:
            actual_value = (
                element
                .locator("option:checked")
                .inner_text()
                .strip()
            )

        except Exception:
            return FieldVerification(
                field_id=field.field_id,
                label=field.label,
                expected_value=expected_value,
                actual_value=None,
                status="UNVERIFIED",
            )

    elif field.role == "combobox":
        try:
            tag_name = element.evaluate(
                "(el) => el.tagName.toLowerCase()"
            )

            # React Select keeps only filter text in the <input>; the committed choice is shown separately.
            selected_value = element.locator(
                "xpath=../.."
            ).locator(
                ".select__single-value"
            )
            if tag_name == "input" and selected_value.count() == 0:
                actual_value = (
                    element
                    .input_value()
                    .strip()
                )
            else:

                if selected_value.count() > 0:
                    actual_value = (
                        selected_value
                        .inner_text()
                        .strip()
                    )
                else:
                    actual_value = (
                        element
                        .inner_text()
                        .strip()
                    )

        except Exception:
            return FieldVerification(
                field_id=field.field_id,
                label=field.label,
                expected_value=expected_value,
                actual_value=None,
                status="UNVERIFIED",
            )

    else:
        # -------------------------------------------------
        # Standard input / textarea
        # -------------------------------------------------
        try:
            actual_value = (
                element
                .input_value()
                .strip()
            )

        except Exception:
            return FieldVerification(
                field_id=field.field_id,
                label=field.label,
                expected_value=expected_value,
                actual_value=None,
                status="UNVERIFIED",
            )

    status = (
        "VERIFIED"
        if actual_value.lower()
        == expected_value.strip().lower()
        else "FAILED"
    )

    return FieldVerification(
        field_id=field.field_id,
        label=field.label,
        expected_value=expected_value,
        actual_value=actual_value,
        status=status,
    )