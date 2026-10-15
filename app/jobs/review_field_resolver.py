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
    if re.fullmatch(r"are you (?:currently )?(?:legally )?authorized to work in (?:the )?(?:united states(?: of america)?|u\.s\.?|us|usa)", question):
        return "US_AUTHORIZATION"
    # Only discard this explicitly approved explanatory example, not arbitrary clauses.
    question = re.sub(r"\s*\(e\.g\.?,?\s*h-?1-?b(?: visa)?(?: status)?\)", "", question)
    if re.fullmatch(
        r"will you now or (?:at any point )?in the future require (?:visa )?sponsorship"
        r"(?: for employment (?:visa )?status)?"
        r"(?: to work in (?:the )?(?:united states(?: of america)?|u\.s\.?|us|usa))?", question):
        return "SPONSORSHIP_NOW_OR_FUTURE"
    if re.fullmatch(r"(?:what is your )?(?:desired|expected) (?:annual )?salary(?: expectations?)?", question):
        return "DESIRED_SALARY"
    if _nyc_onsite_days(question) is not None:
        return "NYC_ONSITE"
    return None


def _nyc_onsite_days(question: str) -> int | None:
    match = re.fullmatch(
        r"are you currently based in or planning to relocate to the nyc area and willing to "
        r"work in our nyc office (\d) days a week", question)
    return int(match.group(1)) if match else None


def approved_yes_no(intent: str, label: str, profile: Profile) -> bool | None:
    """Deterministic Yes/No for approved boolean intents; None when unknown."""
    if intent == "US_AUTHORIZATION":
        return profile.work_authorization.authorized_to_work_us
    if intent == "SPONSORSHIP_NOW_OR_FUTURE":
        return profile.work_authorization.requires_sponsorship_now_or_in_future
    if intent == "NYC_ONSITE":
        facts = profile.approved_answers
        days = _nyc_onsite_days(normalized_question(label))
        # A Yes needs BOTH facts, and approval must cover at least the days asked.
        if (facts.nyc_based_or_willing_to_relocate is True and facts.onsite_days_per_week_willing is not None
                and days is not None and days <= facts.onsite_days_per_week_willing):
            return True
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
        if intent == "DESIRED_SALARY":
            salary = (profile.approved_answers.desired_salary or "").strip() or None
            return ResolvedField(field_id=field.field_id, label=field.label, value=salary,
                                 status="READY" if salary else "REVIEW")
        value = approved_yes_no(intent, field.label, profile) if intent else None
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
