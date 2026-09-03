from pydantic import BaseModel

from app.config.models import Preferences, Profile
from app.jobs.field_mapper import map_field_to_value
from app.jobs.form_parser import FormField
from app.jobs.review_field_resolver import resolve_review_field


class EffectiveFieldMapping(BaseModel):
    field_id: str | None
    label: str
    value: str | None
    status: str
    source: str


def get_effective_mapping(
    field: FormField,
    profile: Profile,
    preferences: Preferences,
) -> EffectiveFieldMapping:
    base = map_field_to_value(
        field,
        profile,
    )

    if base.status == "READY":
        return EffectiveFieldMapping(
            field_id=field.field_id,
            label=field.label,
            value=base.value,
            status="READY",
            source="BASE",
        )

    resolved = resolve_review_field(
        field=field,
        profile=profile,
        preferences=preferences,
    )

    if resolved.status == "READY":
        return EffectiveFieldMapping(
            field_id=field.field_id,
            label=field.label,
            value=resolved.value,
            status="READY",
            source="RESOLVED",
        )

    return EffectiveFieldMapping(
        field_id=field.field_id,
        label=field.label,
        value=None,
        status="REVIEW",
        source="UNRESOLVED",
    )