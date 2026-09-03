from app.browser.client import BrowserClient
from app.config.loader import load_preferences, load_profile
from app.jobs.effective_field_mapper import get_effective_mapping
from app.jobs.filters import passes_hard_filters
from app.jobs.form_filler import fill_ready_fields
from app.jobs.form_parser import parse_form_fields
from app.jobs.greenhouse import extract_greenhouse_job
from app.jobs.open_ended_filler import (
    fill_high_confidence_open_ended_answers,
)
from app.jobs.scorer import classify_score, score_job


def main():
    browser = BrowserClient()
    browser.start()

    try:
        # 1. Extract the job
        job = extract_greenhouse_job(
            browser,
            "https://job-boards.greenhouse.io/courierhealth/jobs/5174299007",
        )

        # 2. Load candidate profile and preferences
        profile = load_profile()
        preferences = load_preferences()

        # 3. Run hard filters before touching the application
        filter_result = passes_hard_filters(
            job,
            preferences,
        )

        print()
        print("=== JOB ===")
        print("Title:", job.title)
        print("Company:", job.company)
        print("Hard filter passed:", filter_result.passed)
        print("Reasons:", filter_result.reasons)

        if not filter_result.passed:
            print()
            print("Decision: SKIP")
            print("Application form was not touched.")
            return

        # 4. Score the job
        score = score_job(
            job,
            profile,
        )

        print()
        print("=== JOB SCORE ===")
        print("Skill match:", score.skill_match)
        print("Experience match:", score.experience_match)
        print("Role alignment:", score.role_alignment)
        print("Overall score:", score.overall_score)
        print("Explanation:", score.explanation)

        decision = classify_score(
            overall_score=score.overall_score,
            auto_apply_minimum=preferences.scoring.auto_apply_minimum,
            review_minimum=preferences.scoring.review_minimum,
        )

        print("Decision:", decision)

        # 5. Stop if the score says SKIP
        if decision == "SKIP":
            print()
            print(
                "Skipping application because the score "
                "is below the review threshold."
            )
            print("Application form was not touched.")
            return

        # 6. Parse the application form
        fields = parse_form_fields(browser)

        print()
        print("=== APPLICATION FIELDS ===")

        for field in fields:
            print(
                f"Label: {field.label!r} | "
                f"Type: {field.field_type} | "
                f"ID: {field.field_id!r} | "
                f"Role: {field.role!r} | "
                f"Required: {field.required}"
            )

        # 7. Show field mappings
        print()
        print("=== EFFECTIVE FIELD MAPPINGS ===")

        for field in fields:
            mapping = get_effective_mapping(
                field=field,
                profile=profile,
                preferences=preferences,
            )

            print(
                f"{mapping.label!r} "
                f"→ {mapping.value!r} "
                f"[{mapping.status} - {mapping.source}]"
            )

        # 8. Fill safe known fields
        fill_ready_fields(
            browser=browser,
            fields=fields,
            profile=profile,
            preferences=preferences,
        )

        print()
        print("READY fields have been filled.")

        # 9. Generate open-ended answers ONCE
        # and fill only HIGH-confidence answers
        generated_answers = (
            fill_high_confidence_open_ended_answers(
                browser=browser,
                fields=fields,
                profile=profile,
                job=job,
            )
        )

        print()
        print(
            "HIGH-confidence open-ended answers "
            "have been filled."
        )

        # 10. Print the same answers that were generated
        print()
        print("=== OPEN-ENDED QUESTIONS ===")

        if not generated_answers:
            print(
                "No open-ended application questions found."
            )

        for field, answer in generated_answers:
            print()
            print("Question:", field.label)
            print("Confidence:", answer.confidence)
            print("Answer:", answer.answer)

        # 11. Never submit automatically yet
        print()
        print("Application has NOT been submitted.")

    finally:
        browser.close()


if __name__ == "__main__":
    main()