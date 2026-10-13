from pydantic import BaseModel
import re

from app.config.models import Preferences, Profile
from app.jobs.form_parser import FormField


class ResolvedField(BaseModel):
    field_id: str | None
    label: str
    value: str | None
    status: str


def normalized_question(label: str) -> str:
    return " ".join(label.lower().strip().rstrip("*? .").split())


def approved_sensitive_intent(label: str) -> str | None:
    question = normalized_question(label)
    if re.fullmatch(r"are you legally authorized to work in (?:the )?(?:united states(?: of america)?|u\.s\.|us|usa)", question):
        return "US_AUTHORIZATION"
    # Only discard this explicitly approved explanatory example, not arbitrary clauses.
    question = question.replace(" (e.g., h-1b visa status)", "")
    if re.fullmatch(r"will you now or in the future require sponsorship(?: for employment (?:visa )?status)?", question):
        return "SPONSORSHIP_NOW_OR_FUTURE"
    return None


def is_sensitive_question(label: str) -> bool:
    return any(term in label.lower() for term in (
        "authoriz", "sponsor", "employment visa", "legally", "unrestricted",
        "salary", "compensation", "relocat", "nyc", "onsite", "office", "3 days",
    ))


def resolve_review_field(
    field: FormField,
    profile: Profile,
    preferences: Preferences,
) -> ResolvedField:
    label = field.label.lower()
    field_id = (field.field_id or "").lower()

    intent = approved_sensitive_intent(field.label)
    if intent or is_sensitive_question(field.label):
        value = None
        if intent == "US_AUTHORIZATION":
            value = profile.work_authorization.authorized_to_work_us
        elif intent == "SPONSORSHIP_NOW_OR_FUTURE":
            value = profile.work_authorization.requires_sponsorship_now_or_in_future
        return ResolvedField(field_id=field.field_id, label=field.label,
                             value=("Yes" if value else "No") if value is not None else None,
                             status="READY" if value is not None else "REVIEW")

    question = normalized_question(field.label)
    if question == "location (city)":
        location = profile.location
        value = f"{location.city}, {location.state}, {location.country}" if all(
            part.strip() for part in (location.city, location.state, location.country)
        ) else None
        return ResolvedField(field_id=field.field_id, label=field.label, value=value,
                             status="READY" if value else "REVIEW")
    if question == "which state do you currently reside in":
        value = profile.location.state.strip() or None
        return ResolvedField(field_id=field.field_id, label=field.label, value=value,
                             status="READY" if value else "REVIEW")

    # Country
    if field_id == "country":
        return ResolvedField(
            field_id=field.field_id,
            label=field.label,
            value=profile.location.country,
            status="READY",
        )

    return ResolvedField(
        field_id=field.field_id,
        label=field.label,
        value=None,
        status="REVIEW",
    )
