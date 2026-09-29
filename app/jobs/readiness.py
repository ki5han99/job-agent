from pydantic import BaseModel

from app.jobs.form_verifier import FieldVerification


class ApplicationReadiness(BaseModel):
    verified_count: int
    review_count: int
    failed_count: int
    status: str
    blocking_items: list[str]


def build_readiness_report(
    verifications: list[FieldVerification],
    review_items: list[str],
) -> ApplicationReadiness:
    verified_count = sum(
        1
        for item in verifications
        if item.status == "VERIFIED"
    )

    failed_items = [
        item.label
        for item in verifications
        if item.status in {
            "FAILED",
            "NOT_FOUND",
            "UNVERIFIED",
        }
    ]

    blocking_items = [
        *failed_items,
        *review_items,
    ]

    if failed_items:
        status = "NOT_READY"

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