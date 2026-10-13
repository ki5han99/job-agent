from pydantic import BaseModel

from app.jobs.form_verifier import FieldVerification
from app.jobs.form_parser import FormField


class ApplicationReadiness(BaseModel):
    verified_count: int
    review_count: int
    failed_count: int
    status: str
    blocking_items: list[str]


def build_readiness_report(
    verifications: list[FieldVerification],
    review_items: list[str],
    fields: list[FormField],
) -> ApplicationReadiness:
    review_items = list(review_items)
    missing_required = []
    for index, field in enumerate(fields):
        if not field.required:
            continue
        matches = [item for item in verifications if field.field_id and item.field_id == field.field_id]
        unique_id = field.field_id and sum(other.field_id == field.field_id for other in fields) == 1
        if unique_id and len(matches) == 1 and matches[0].status == "VERIFIED":
            continue
        label = field.label or field.field_id or field.name or f"Unlabeled required field #{index + 1}"
        missing_required.append(label)
        if label not in review_items and not matches:
            review_items.append(label)

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
        *review_items,
        *[label for label in missing_required if label not in failed_items and label not in review_items],
    ]

    if failed_items or missing_required or not fields:
        status = "NOT_READY"
        if not fields:
            blocking_items.append("No application fields were observed.")

    elif review_items:
        status = "READY_FOR_HUMAN_REVIEW"

    else:
        status = "READY"

    return ApplicationReadiness(
        verified_count=verified_count,
        review_count=len(review_items),
        failed_count=len(failed_items),
        status=status,
        blocking_items=blocking_items,
    )
