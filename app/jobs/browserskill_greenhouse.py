"""BrowserSkill Greenhouse workflow; unsupported or unapproved fields remain for review."""
import time
from pathlib import Path

from app.browser.interface import Browser, BrowserError, ChoiceRequest, SelectionReview
from app.config.loader import load_preferences, load_profile
from app.jobs.effective_field_mapper import get_effective_mapping
from app.jobs.extractor import extract_job
from app.jobs.filters import passes_hard_filters
from app.jobs.form_parser import FormField
from app.jobs.form_verifier import FieldVerification
from app.jobs.greenhouse import validate_greenhouse_job_page
from app.jobs.readiness import build_readiness_report
from app.jobs.scorer import classify_score, score_job
from app.jobs.review_field_resolver import approved_sensitive_intent, approved_yes_no, normalized_question


def approved_choice(field: FormField, profile) -> ChoiceRequest | None:
    if field.role != "combobox":
        return None
    intent = approved_sensitive_intent(field.label)
    if intent and intent != "DESIRED_SALARY":
        fact = approved_yes_no(intent, field.label, profile)
        if fact is None:
            return None
        value = "Yes" if fact else "No"
        return ChoiceRequest(search=value, labels=[value])
    question = normalized_question(field.label)
    location = profile.location
    if question == "country" and field.field_id == "country" and location.country == "United States":
        return ChoiceRequest(search=location.country, labels=[location.country], country_code="us")
    # CA -> California is a spelling normalization, not a candidate fact inference.
    state_names = {"CA": "California"}
    if question == "which state do you currently reside in" and location.state.strip():
        state = location.state.strip()
        return ChoiceRequest(search=state_names.get(state, state), labels=[state, state_names.get(state, state)])
    if question == "location (city)" and all(part.strip() for part in (
        location.city, location.state, location.country,
    )):
        city, state, country = location.city.strip(), location.state.strip(), location.country.strip()
        return ChoiceRequest(search=city, labels=[f"{city}, {state}, {country}",
                                                  f"{city}, {state_names.get(state, state)}, {country}"])
    return None


def permitted_text(field: FormField) -> bool:
    if field.role == "combobox" or field.field_type not in {"text", "email", "tel"}:
        return False
    label = field.label.strip().rstrip("*").strip().lower()
    # Require both semantic label and ID for standard fields. No sensitive facts
    # or arbitrary questions mentioning a profile URL enter this first slice.
    labels = {
        "first_name": {"first name"}, "last_name": {"last name"},
        "preferred_name": {"preferred first name", "preferred name"},
        "email": {"email", "email address"}, "phone": {"phone", "phone number"},
    }
    return (label in labels.get(field.field_id, set()) or label == "linkedin profile"
            or approved_sensitive_intent(field.label) == "DESIRED_SALARY")


RESUME_PATH = Path(__file__).resolve().parents[2] / "data" / "resume.pdf"


def is_resume_field(field: FormField) -> bool:
    label = field.label.strip().rstrip("*").strip().lower()
    return (field.field_type == "file" and field.field_id == "resume"
            and label in {"resume", "resume/cv", "cv"})


def upload_resume(browser: Browser, observation, field: FormField, resume: Path = RESUME_PATH):
    """Upload then verify independently; returns a FieldVerification or None for REVIEW."""
    if not resume.is_file():
        print(field.label, "→ REVIEW: resume file not found at", resume)
        return None
    try:
        browser.upload_file(observation, str(resume))
    except BrowserError as error:
        print(field.label, "→ REVIEW: upload failed:", error)
        return None
    # The page re-renders asynchronously after upload; reads are idempotent, so poll.
    for attempt in range(10):
        actual = browser.read_file(observation, resume.name)
        attached = actual.found and (resume.name in actual.filenames or actual.shown_in_ui)
        if attached:
            break
        time.sleep(0.5)
    return FieldVerification(
        field_id=field.field_id, label=field.label, expected_value=resume.name,
        actual_value=resume.name if attached else (", ".join(actual.filenames) or None),
        status="VERIFIED" if attached else ("FAILED" if actual.found else "NOT_FOUND"),
    )


def run_greenhouse(browser: Browser, job_url: str, session_id=None, tab_id=None):
    try:
        if session_id is not None:
            browser.attach(session_id, tab_id, job_url)
        else:
            browser.start()
            browser.open(job_url)
        observed = browser.observe_page()
        validate_greenhouse_job_page(job_url, observed.url, observed.heading)
        lines = [line.strip() for line in observed.text.splitlines() if line.strip()]
        index = lines.index(observed.heading) if observed.heading in lines else -1
        location = lines[index + 1] if index >= 0 and index + 1 < len(lines) else "Unknown"
        company = observed.title.split(" at ")[-1].replace("Job Application for ", "").strip()
        job = extract_job(observed.heading, company, location, observed.text, "Greenhouse", job_url)
        profile, preferences = load_profile(), load_preferences()
        filters = passes_hard_filters(job, preferences)
        print("Job:", job.title, "at", job.company)
        print("Hard filters:", filters.passed, filters.reasons)
        if not filters.passed:
            print("Decision: SKIP. Form was not touched.")
            return None
        score = score_job(job, profile)
        decision = classify_score(score.overall_score, preferences.scoring.auto_apply_minimum,
                                  preferences.scoring.review_minimum)
        print("Score:", score.overall_score, "Decision:", decision)
        print("Explanation:", score.explanation)
        if decision == "SKIP":
            print("Form was not touched.")
            return None

        # Re-observe after LLM calls: never act on a stale page or field list.
        observed = browser.observe_page()
        fields = [FormField.model_validate(item.model_dump()) for item in observed.fields]
        verifications, reviews = [], []
        for observation, field in zip(observed.fields, fields):
            mapping = get_effective_mapping(field, profile, preferences)
            unique_id = field.field_id and sum(f.field_id == field.field_id for f in fields) == 1
            if is_resume_field(field) and unique_id:
                result = upload_resume(browser, observation, field)
                if result is None:
                    reviews.append(field)
                else:
                    verifications.append(result)
                    print(field.label, "→", result.status, "(attached file)")
                continue
            choice = approved_choice(field, profile)
            if unique_id and choice is not None:
                try:
                    actual = browser.select_choice(observation, choice)
                except SelectionReview as error:
                    reviews.append(field)
                    print(field.label, "→ REVIEW:", str(error))
                    continue
                verifications.append(FieldVerification(
                    field_id=field.field_id, label=field.label, expected_value=" / ".join(choice.labels),
                    actual_value=actual.value, status=("VERIFIED" if actual.found and (
                        actual.country_code == choice.country_code if choice.country_code else
                        " ".join((actual.value or "").casefold().split()) in {
                            " ".join(label.casefold().split()) for label in choice.labels
                        }
                    ) else "FAILED"),
                ))
                print(field.label, "→", verifications[-1].status, "(selected value)")
                continue
            if (not unique_id or not permitted_text(field) or mapping.status != "READY"
                    or not mapping.value or not mapping.value.strip()):
                reviews.append(field)
                print(field.label or field.field_id or "Unnamed field", "→ REVIEW")
                continue
            browser.fill_text(observation, mapping.value)
            actual = browser.read_field(observation)
            status = "NOT_FOUND" if not actual.found else (
                "VERIFIED" if actual.value == mapping.value else "FAILED")
            verifications.append(FieldVerification(
                field_id=field.field_id, label=field.label, expected_value=mapping.value,
                actual_value=actual.value, status=status,
            ))
            print(field.label, "→", status)
        # Include newly appeared required fields; never drop original observations.
        final = browser.observe_page()
        for item in final.fields:
            field = FormField.model_validate(item.model_dump())
            if field not in fields:
                fields.append(field)
                reviews.append(field)
        report = build_readiness_report(verifications, reviews, fields)
        # A resume must be independently verified as attached, even if the page
        # did not mark the control required or did not expose it at all.
        if not any(v.field_id == "resume" and v.status == "VERIFIED" for v in verifications):
            report.status = "NOT_READY"
            report.blocking_items.append("Resume attachment was not verified.")
        print("Readiness:", report.status)
        print("Verified:", report.verified_count, "Required unresolved:", report.review_count)
        print("Blocking items:", report.blocking_items)
        print("Optional review:", report.optional_review_items)
        return report
    finally:
        # Handoff deliberately does not call stop/close or replay browser actions.
        print(browser.handoff())
