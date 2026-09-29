from app.browser.client import BrowserClient
from app.config.loader import load_preferences, load_profile
from app.jobs.effective_field_mapper import get_effective_mapping
from app.jobs.filters import passes_hard_filters
from app.jobs.form_filler import fill_ready_fields
from app.jobs.form_parser import parse_form_fields
from app.jobs.form_verifier import verify_field
from app.jobs.greenhouse import extract_greenhouse_job
from app.jobs.open_ended_filler import (
    fill_high_confidence_open_ended_answers,
)
from app.jobs.readiness import build_readiness_report
from app.jobs.scorer import classify_score, score_job


def main():
    browser = BrowserClient()
    browser.start()

    try:
        # 1. Extract job
        job = extract_greenhouse_job(
            browser,
            "https://job-boards.greenhouse.io/courierhealth/jobs/5174299007",
        )

        # 2. Load candidate profile and preferences
        profile = load_profile()
        preferences = load_preferences()

        # 3. Run hard filters before touching application
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

        # 4. Score job
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
            auto_apply_minimum=(
                preferences.scoring.auto_apply_minimum
            ),
            review_minimum=(
                preferences.scoring.review_minimum
            ),
        )

        print("Decision:", decision)

        # 5. Stop before form interaction if SKIP
        if decision == "SKIP":
            print()
            print(
                "Skipping application because the score "
                "is below the review threshold."
            )
            print("Application form was not touched.")
            return

        # 6. Parse application form
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

        # 7. Build effective mappings
        print()
        print("=== EFFECTIVE FIELD MAPPINGS ===")

        effective_mappings = []

        for field in fields:
            mapping = get_effective_mapping(
                field=field,
                profile=profile,
                preferences=preferences,
            )

            effective_mappings.append(
                (field, mapping)
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

        # 9. Generate open-ended answers once
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

        # 10. Show generated answers
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

        # 11. Verify normal fields
        print()
        print("=== FIELD VERIFICATION ===")

        verifications = []
        review_items = []

        for field, mapping in effective_mappings:

            # Textareas are handled separately by
            # the open-ended answer engine.
            if field.field_type == "textarea":
                continue

            if mapping.status != "READY":
                review_items.append(
                    mapping.label
                )

                print(
                    f"{mapping.label!r} "
                    f"→ REVIEW"
                )
                continue

            if mapping.value is None:
                review_items.append(
                    mapping.label
                )

                print(
                    f"{mapping.label!r} "
                    f"→ REVIEW"
                )
                continue

            verification = verify_field(
                browser=browser,
                field=field,
                expected_value=mapping.value,
            )

            verifications.append(
                verification
            )

            print(
                f"{verification.label!r} "
                f"→ {verification.status} "
                f"| Expected: "
                f"{verification.expected_value!r} "
                f"| Actual: "
                f"{verification.actual_value!r}"
            )

        # 12. Verify open-ended answers separately
        print()
        print("=== OPEN-ENDED VERIFICATION ===")

        if not generated_answers:
            print(
                "No generated answers to verify."
            )

        for field, answer in generated_answers:
            if answer.confidence != "HIGH":
                review_items.append(
                    field.label
                )

                print(
                    f"{field.label!r} "
                    f"→ REVIEW"
                )
                continue

            if not answer.answer.strip():
                review_items.append(
                    field.label
                )

                print(
                    f"{field.label!r} "
                    f"→ REVIEW"
                )
                continue

            verification = verify_field(
                browser=browser,
                field=field,
                expected_value=answer.answer,
            )

            verifications.append(
                verification
            )

            print(
                f"{verification.label!r} "
                f"→ {verification.status}"
            )

        # 13. Build application readiness report
        readiness = build_readiness_report(
            verifications=verifications,
            review_items=review_items,
        )

        print()
        print("=== APPLICATION READINESS ===")
        print(
            "Verified fields:",
            readiness.verified_count,
        )
        print(
            "Review required:",
            readiness.review_count,
        )
        print(
            "Failed fields:",
            readiness.failed_count,
        )
        print(
            "Status:",
            readiness.status,
        )

        if readiness.blocking_items:
            print()
            print("Blocking items:")

            for item in readiness.blocking_items:
                print("-", item)

        # 14. Never submit automatically yet
        print()
        print("Application has NOT been submitted.")

    finally:
        browser.close()


if __name__ == "__main__":
    main()