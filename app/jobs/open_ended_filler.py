from app.browser.client import BrowserClient
from app.config.models import Profile
from app.jobs.answer_engine import (
    GeneratedAnswer,
    generate_application_answer,
)
from app.jobs.form_parser import FormField
from app.jobs.models import Job


def fill_high_confidence_open_ended_answers(
    browser: BrowserClient,
    fields: list[FormField],
    profile: Profile,
    job: Job,
) -> list[tuple[FormField, GeneratedAnswer]]:
    if browser.page is None:
        raise RuntimeError("Browser has not been started.")

    generated_answers: list[
        tuple[FormField, GeneratedAnswer]
    ] = []

    for field in fields:
        if field.field_type != "textarea":
            continue

        if not field.label.strip():
            continue

        if field.field_id is None:
            continue

        answer = generate_application_answer(
            question=field.label,
            profile=profile,
            job=job,
        )

        generated_answers.append(
            (field, answer)
        )

        if answer.confidence != "HIGH":
            continue

        if not answer.answer.strip():
            continue

        element = browser.page.locator(
            f'[id="{field.field_id}"]'
        )

        if element.count() == 0:
            continue

        element.fill(answer.answer)

    return generated_answers