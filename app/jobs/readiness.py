from pydantic import BaseModel

from app.jobs.form_verifier import FieldVerification
from app.jobs.form_parser import FormField


class ApplicationReadiness(BaseModel):
    verified_count: int
    review_count: int
    failed_count: int
    status: str
    blocking_items: list[str]
    optional_review_count: int
    optional_review_items: list[str]
    submission: str = "NOT_ATTEMPTED"


def build_readiness_report(
    verifications: list[FieldVerification],
    review_items: list[FormField],
    fields: list[FormField],
) -> ApplicationReadiness:
    missing_required = []
    optional_review_items = []
    for index, field in enumerate(fields):
        matches = [item for item in verifications if field.field_id and item.field_id == field.field_id]
        unique_id = field.field_id and sum(other.field_id == field.field_id for other in fields) == 1
        if (
            unique_id and len(matches) == 1 and matches[0].status == "VERIFIED"
            and field not in review_items
        ):
            continue
        kind = "required" if field.required else "optional"
        label = field.label or field.field_id or field.name or f"Unlabeled {kind} field #{index + 1}"
        if field.required:
            missing_required.append(label)
        else:
            optional_review_items.append(label)

    verified_count = sum(
        1
        for item in verifications
        if item.status == "VERIFIED"
    )

    failed_items = [
        item.label
        for item in verifications
        if item.status != "VERIFIED"
    ]

    blocking_items = [
        *failed_items,
        *[label for label in missing_required if label not in failed_items],
    ]

    if failed_items or missing_required or not fields:
        status = "NOT_READY"
        if not fields:
            blocking_items.append("No application fields were observed.")

    else:
        status = "READY"

    return ApplicationReadiness(
        verified_count=verified_count,
        review_count=len(missing_required),
        failed_count=len(failed_items),
        status=status,
        blocking_items=blocking_items,
        optional_review_count=len(optional_review_items),
        optional_review_items=optional_review_items,
    )
