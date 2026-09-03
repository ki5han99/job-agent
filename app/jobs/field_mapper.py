from pydantic import BaseModel

from app.config.models import Profile
from app.jobs.form_parser import FormField


class FieldMapping(BaseModel):
    field_id: str | None
    label: str
    value: str | None
    status: str


def map_field_to_value(
    field: FormField,
    profile: Profile,
) -> FieldMapping:
    field_id = (field.field_id or "").lower()
    label = field.label.lower()

    # First name
    if field_id == "first_name":
        value = profile.candidate.first_name

    # Preferred first name
    elif field_id == "preferred_name":
        value = profile.candidate.preferred_name

    # Last name
    elif field_id == "last_name":
        value = profile.candidate.last_name

    # Email
    elif field_id == "email":
        value = profile.contact.email

    # Phone
    elif field_id == "phone":
        value = profile.contact.phone

    # Country
    # Greenhouse uses a custom combobox here.
    # Keep this for review until we handle it reliably.
    elif field_id == "country":
        return FieldMapping(
            field_id=field.field_id,
            label=field.label,
            value=None,
            status="REVIEW",
        )

    # Resume upload
    elif field_id == "resume":
        return FieldMapping(
            field_id=field.field_id,
            label=field.label,
            value="data/resume.pdf",
            status="READY",
        )

    # Cover letter
    elif field_id == "cover_letter":
        return FieldMapping(
            field_id=field.field_id,
            label=field.label,
            value=None,
            status="REVIEW",
        )

    # LinkedIn profile
    # Be specific so questions that merely mention LinkedIn
    # do not get mapped to the LinkedIn URL.
    elif (
        "linkedin profile" in label
        or field_id == "linkedin"
    ):
        value = profile.links.linkedin

    # Website / portfolio
    elif (
        label == "website"
        or "portfolio" in label
    ):
        if profile.links.portfolio:
            value = profile.links.portfolio
        else:
            return FieldMapping(
                field_id=field.field_id,
                label=field.label,
                value=None,
                status="REVIEW",
            )

    # Onsite / hybrid acknowledgement
    elif (
        field.field_type == "checkbox"
        and (
            "in office" in label
            or "onsite" in label
            or "hybrid requirement" in label
        )
    ):
        return FieldMapping(
            field_id=field.field_id,
            label=field.label,
            value="true",
            status="READY",
        )

    # Sensitive demographic fields
    elif (
        field_id in {
            "gender",
            "hispanic_ethnicity",
            "veteran_status",
            "disability_status",
        }
        or "gender identity" in label
        or "racial/ethnic" in label
        or "sexual orientation" in label
        or "transgender" in label
        or "disability or chronic condition" in label
        or "veteran or active member" in label
    ):
        return FieldMapping(
            field_id=field.field_id,
            label=field.label,
            value=None,
            status="REVIEW",
        )

    # Work authorization / sponsorship
    # Do not guess until those profile values are explicitly set.
    elif (
        "work authorization" in label
        or "sponsorship" in label
    ):
        return FieldMapping(
            field_id=field.field_id,
            label=field.label,
            value=None,
            status="REVIEW",
        )

    # Company-specific confirmations
    # Example: "I confirm I have never been a patient..."
    # These must not be inferred.
    elif field.field_type == "checkbox":
        return FieldMapping(
            field_id=field.field_id,
            label=field.label,
            value=None,
            status="REVIEW",
        )

    # Open-ended questions
    elif field.field_type == "textarea":
        return FieldMapping(
            field_id=field.field_id,
            label=field.label,
            value=None,
            status="REVIEW",
        )

    # Anything unknown
    else:
        return FieldMapping(
            field_id=field.field_id,
            label=field.label,
            value=None,
            status="REVIEW",
        )

    return FieldMapping(
        field_id=field.field_id,
        label=field.label,
        value=value,
        status="READY",
    )