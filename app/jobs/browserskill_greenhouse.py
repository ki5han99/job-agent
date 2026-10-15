"""BrowserSkill Greenhouse workflow; unsupported or unapproved fields remain for review."""
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from app.browser.interface import Browser, BrowserError, ChoiceRequest, SelectionReview
from datetime import date

from app.config.loader import load_answers, load_preferences, load_profile
from app.jobs.consent import classify_consent
from app.jobs.cover_letter import generate_cover_letter, write_cover_letter_file
from app.jobs.eeo import DECLINE_LABELS, is_eeo_question
from app.jobs.grounding import UNSUPPORTED_PERSONAL_CLAIMS, ungrounded_claims
from app.jobs.policy import Context, classify_intent, resolve_choice, resolve_text
from app.jobs.answer_engine import generate_application_answer
from app.jobs.effective_field_mapper import get_effective_mapping
from app.jobs.extractor import extract_job
from app.jobs.filters import passes_hard_filters
from app.jobs.form_parser import FormField
from app.jobs.form_verifier import FieldVerification
from app.jobs.greenhouse import validate_greenhouse_job_page
from app.jobs.readiness import build_readiness_report
from app.jobs.scorer import classify_score, score_job
from app.jobs.review_field_resolver import approved_sensitive_intent, approved_yes_no, normalized_question


def approved_choice(field: FormField, profile, ctx: Context | None = None) -> ChoiceRequest | None:
    if field.role != "combobox":
        return None
    if ctx is not None:
        # Approved policy/facts first. Veteran questions have an explicit fact, so they never
        # fall through to the generic "decline" default.
        choice = resolve_choice(field, ctx)
        if choice is not None:
            return choice
        intent = classify_intent(field.label, ctx)
        if intent is not None and intent.name in {"VETERAN", "MILITARY", "EEO", "RACE", "HISPANIC"}:
            return None
    intent = approved_sensitive_intent(field.label)
    if ctx is None and is_eeo_question(field.label):
        # Voluntary self-identification: only an explicitly offered decline option, never a fact.
        return ChoiceRequest(search="decline", labels=DECLINE_LABELS, no_search=True)
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
    state_names = US_STATE_NAMES
    if question == "which state do you currently reside in" and location.state.strip():
        state = location.state.strip()
        return ChoiceRequest(search=state_names.get(state, state), labels=[state, state_names.get(state, state)])
    if question == "location (city)" and all(part.strip() for part in (
        location.city, location.state, location.country,
    )):
        city, state, country = location.city.strip(), location.state.strip(), location.country.strip()
        return ChoiceRequest(search=city, labels=[f"{city}, {state}, {country}",
                                                  f"{city}, {state_names.get(state, state)}, {country}"],
                             identical_duplicates_ok=True)
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


def is_open_ended_field(field: FormField) -> bool:
    return field.field_type == "textarea" and bool(field.label.strip()) and bool(field.field_id)


def grounded_answer(field: FormField, profile, job) -> str | None:
    """Draft via the grounded answer engine; None unless HIGH confidence and claim-free."""
    answer = generate_application_answer(question=field.label, profile=profile, job=job)
    text = answer.answer.strip()
    if answer.confidence != "HIGH" or not text:
        return None
    problems = ungrounded_claims(text, profile, job)
    if problems:
        print(field.label[:60], "→ REVIEW: draft discarded:", "; ".join(problems))
        return None
    return text


# Postal abbreviation -> full name is spelling normalization, not a candidate fact.
US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

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


SUBMISSION_LEDGER = Path(__file__).resolve().parents[2] / "data" / "submissions.json"


def _ledger() -> dict:
    try:
        return json.loads(SUBMISSION_LEDGER.read_text())
    except (OSError, ValueError):
        return {}


def _record(url: str, status: str) -> None:
    ledger = _ledger()
    ledger[url.split('?')[0].rstrip('/')] = status
    SUBMISSION_LEDGER.write_text(json.dumps(ledger, indent=2))


def submit_gate(decision: str, report, generated: list, job_url: str, ignore_score: bool = False) -> list[str]:
    """Reasons NOT to submit; an empty list means every strict condition holds."""
    reasons = []
    if decision != "AUTO_APPLY" and not ignore_score:
        reasons.append(f"score decision is {decision}, not AUTO_APPLY")
    if report.status != "READY":
        reasons.append("readiness is " + report.status)
    if generated:
        reasons.append("LLM-generated answers require human review")
    if job_url.split('?')[0].rstrip('/') in _ledger():
        reasons.append("ledger shows this application was already attempted")
    return reasons


def field_stream(browser: Browser, observed, fields: list, max_rounds: int = 3):
    """Yield (observation, field) for the form, then for fields revealed by earlier answers.

    Answering one question can reveal another (e.g. Hispanic/Latino -> race). After each round the page
    is re-observed; genuinely new fields are appended to `fields` in place and yielded.
    """
    yield from zip(observed.fields, list(fields))
    for _ in range(max_rounds):
        revealed = []
        for item in browser.observe_page().fields:
            field = FormField.model_validate(item.model_dump())
            if field not in fields:
                fields.append(field)
                revealed.append((item, field))
        if not revealed:
            return
        yield from revealed


PLACEHOLDER_COMPANIES = {"", "page_title", "unknown", "none", "null", "undefined"}


def company_from_page(title: str, url: str) -> str:
    """Company from 'Job Application for <role> at <company>'; falls back to the board slug."""
    company = title.rsplit(" at ", 1)[-1].replace("Job Application for ", "").strip() if " at " in title else ""
    if company.casefold() in PLACEHOLDER_COMPANIES:
        slug = urlparse(url).path.strip("/").split("/")[0]
        return slug.replace("-", " ").replace("_", " ").title() if slug else "Unknown"
    return company


def run_greenhouse(browser: Browser, job_url: str, session_id=None, tab_id=None, submit: bool = False,
                   ignore_score: bool = False, intent_llm=None):
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
        company = company_from_page(observed.title, job_url)
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
        if decision == "SKIP" and not ignore_score:
            print("Form was not touched.")
            return None
        if ignore_score and decision != "AUTO_APPLY":
            print("WARNING: --ignore-score set; proceeding despite decision", decision)

        # Re-observe after LLM calls: never act on a stale page or field list.
        observed = browser.observe_page()
        fields = [FormField.model_validate(item.model_dump()) for item in observed.fields]
        verifications, reviews, generated = [], [], []
        answers = load_answers()
        ctx = Context(profile, preferences, answers, company=getattr(job, "company", "") or "",
                      job_location=getattr(job, "location", "") or "",
                      ledger=_ledger(), today=date.today(), llm_classify=intent_llm)
        approved_consent = set(answers.consent.approved_categories)
        for observation, field in field_stream(browser, observed, fields):
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
            if unique_id and re.match(r"cover letter\b", field.label.strip().lower()):
                if not (answers.cover_letter_generation and field.required):
                    reviews.append(field)          # optional letters are skipped, never invented
                    print(field.label, "→ REVIEW (optional or generation not approved)")
                    continue
                letter = generate_cover_letter(profile, job)
                if letter is None:
                    reviews.append(field)
                    print(field.label, "→ REVIEW (no grounded cover letter could be generated)")
                    continue
                if field.field_type == "file":
                    path = write_cover_letter_file(letter, getattr(job, "company", "") or "company")
                    generated.append((field.label, letter))     # generated content always holds the submit gate
                    result = upload_resume(browser, observation, field, path)
                    if result is None:
                        reviews.append(field)
                    else:
                        verifications.append(result)
                        print(field.label, "→", result.status, "(generated cover letter file)")
                    continue
                if field.field_type == "textarea":
                    generated.append((field.label, letter))
                    browser.fill_text(observation, letter)
                    actual = browser.read_field(observation)
                    verifications.append(FieldVerification(
                        field_id=field.field_id, label=field.label, expected_value=letter, actual_value=actual.value,
                        status="NOT_FOUND" if not actual.found else ("VERIFIED" if actual.value == letter else "FAILED")))
                    print(field.label, "→", verifications[-1].status, "(generated cover letter)")
                    continue
            if field.field_type == "checkbox":
                consent = classify_consent(field.label, approved_consent)
                if not (unique_id and consent.eligible):
                    reviews.append(field)
                    print(field.label[:70] or field.field_id or "Unnamed checkbox", "→ REVIEW (consent:", consent.reason + ")")
                    continue
                try:
                    actual = browser.set_checkbox(observation)
                except (BrowserError, SelectionReview) as error:
                    reviews.append(field)
                    print(field.label[:70], "→ REVIEW:", str(error))
                    continue
                verifications.append(FieldVerification(
                    field_id=field.field_id, label=field.label, expected_value="checked",
                    actual_value=actual.value, status="VERIFIED" if actual.found and actual.value == "checked" else "FAILED"))
                print(field.label[:70], "→", verifications[-1].status, f"({', '.join(consent.categories)})")
                continue
            choice = approved_choice(field, profile, ctx)
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
                print(field.label, "→", verifications[-1].status, f"(selected value = {(actual.value or '')[:80]!r})")
                continue
            policy_value = resolve_text(field, ctx) if unique_id else None
            if policy_value:
                mapping = SimpleNamespace(status="READY", value=policy_value)
            if unique_id and not policy_value and is_open_ended_field(field) and mapping.status != "READY":
                draft = grounded_answer(field, profile, job)
                if draft is not None:
                    generated.append((field.label, draft))
                    mapping = SimpleNamespace(status="READY", value=draft)
                    open_ended = True
                else:
                    reviews.append(field)
                    print(field.label[:60], "→ REVIEW (no safe grounded answer)")
                    continue
            else:
                open_ended = False
            if (not unique_id or not (open_ended or policy_value or permitted_text(field)) or mapping.status != "READY"
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
            print(field.label, "→", status, f"(= {(actual.value or '')[:80]!r})" if policy_value else "")
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
        for label, text in generated:
            print("GENERATED ANSWER (review before submitting):", label[:70], "→", text)
        if submit:
            reasons = submit_gate(decision, report, generated, job_url, ignore_score)
            if reasons:
                report.submission = "SKIPPED"
                print("NOT SUBMITTING:", "; ".join(reasons))
            else:
                _record(job_url, "ATTEMPTING")  # written first: a crash must never allow a resubmit
                try:
                    outcome = browser.submit_application()
                except BrowserError as error:
                    report.submission = "NOT_CLICKED"
                    _record(job_url, "NOT_CLICKED")
                    print("NOT SUBMITTED:", error)
                else:
                    report.submission = outcome.status
                    _record(job_url, outcome.status)
                    print("SUBMISSION", outcome.status + ":", outcome.detail)
        return report
    finally:
        # Handoff deliberately does not call stop/close or replay browser actions.
        print(browser.handoff())
