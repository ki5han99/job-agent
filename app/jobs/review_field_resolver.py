from pydantic import BaseModel

from app.config.models import Preferences, Profile
from app.jobs.form_parser import FormField


class ResolvedField(BaseModel):
    field_id: str | None
    label: str
    value: str | None
    status: str


def resolve_review_field(
    field: FormField,
    profile: Profile,
    preferences: Preferences,
) -> ResolvedField:
    label = field.label.lower()
    field_id = (field.field_id or "").lower()

    # Country
    if field_id == "country":
        return ResolvedField(
            field_id=field.field_id,
            label=field.label,
            value=profile.location.country,
            status="READY",
        )

    # Onsite / office availability
    if (
        "open to being in the office" in label
        or "onsite" in label
        or "in office" in label
    ):
        if preferences.work_arrangements.onsite:
            return ResolvedField(
                field_id=field.field_id,
                label=field.label,
                value="Yes",
                status="READY",
            )

    # Sponsorship
    if (
        "require sponsorship" in label
        or "sponsorship" in label
        or "employment visa" in label
    ):
        sponsorship = profile.work_authorization.requires_sponsorship

        if sponsorship is True:
            return ResolvedField(
                field_id=field.field_id,
                label=field.label,
                value="Yes",
                status="READY",
            )

        if sponsorship is False:
            return ResolvedField(
                field_id=field.field_id,
                label=field.label,
                value="No",
                status="READY",
            )

    return ResolvedField(
        field_id=field.field_id,
        label=field.label,
        value=None,
        status="REVIEW",
    )