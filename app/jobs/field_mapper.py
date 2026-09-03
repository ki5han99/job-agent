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

    # Last name
    elif field_id == "last_name":
        value = profile.candidate.last_name

    # Email
    elif field_id == "email":
        value = profile.contact.email

    # Phone
    elif field_id == "phone":
        value = profile.contact.phone

    # Country:
    # Greenhouse uses a more complicated control here,
    # so leave it for review for now.
    elif field_id == "country":
        return FieldMapping(
            field_id=field.field_id,
            label=field.label,
            value=None,
            status="REVIEW",
        )

    # Resume
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

    # LinkedIn
    elif "linkedin" in label:
        value = profile.links.linkedin

    # Website / portfolio
    elif "website" in label:
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

    # Anything we don't recognize
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