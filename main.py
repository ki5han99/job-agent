import argparse

from app.browser.client import BrowserClient
from app.config.loader import load_default_test_job_url, load_preferences, load_profile
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


def run_playwright(job_url: str):
    print("Job URL:", job_url)
    browser = BrowserClient()
    browser.start()

    try:
        # 1. Extract job
        job = extract_greenhouse_job(
            browser,
            job_url,
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
                    field
                )

                print(
                    f"{mapping.label!r} "
                    f"→ REVIEW"
                )
                continue

            if mapping.value is None:
                review_items.append(
                    field
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
                    field
                )

                print(
                    f"{field.label!r} "
                    f"→ REVIEW"
                )
                continue

            if not answer.answer.strip():
                review_items.append(
                    field
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
            fields=fields,
        )

        print()
        print("=== APPLICATION READINESS ===")
        print(
            "Verified fields:",
            readiness.verified_count,
        )
        print(
            "Required fields unresolved:",
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

        print("Optional fields for review (non-blocking):", readiness.optional_review_count)
        for item in readiness.optional_review_items:
            print("-", item)

        # 14. Never submit automatically yet
        print()
        print("Application has NOT been submitted.")

    finally:
        browser.close()


def main(job_url: str, browser_backend: str = "browserskill", session_id=None, tab_id=None, submit: bool = False):
    if browser_backend == "playwright":
        return run_playwright(job_url)
    from app.browser.browserskill_browser import BrowserSkillBrowser
    from app.jobs.browserskill_greenhouse import run_greenhouse
    print("Browser: BrowserSkill (primary)")
    print("Job URL:", job_url)
    return run_greenhouse(BrowserSkillBrowser(), job_url, session_id, tab_id, submit=submit)


def parse_options(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Evaluate and prepare a Greenhouse application without submitting.")
    parser.add_argument(
        "job_url", nargs="?",
        help="Greenhouse job URL (default: default_job in data/test_jobs.yaml)",
    )
    parser.add_argument("--browser", choices=["browserskill", "playwright"], default="browserskill")
    parser.add_argument("--session", help="Explicit BrowserSkill session to reattach")
    parser.add_argument("--tab-id", type=int, help="Agent tab belonging to --session")
    parser.add_argument("--submit", action="store_true",
                        help="Click Submit ONLY when the strict gate passes (AUTO_APPLY, READY, no generated answers)")
    parser.add_argument("--all-test-jobs", action="store_true", help="Run every job in data/test_jobs.yaml")
    args = parser.parse_args(argv)
    if args.submit and args.browser != "browserskill":
        parser.error("--submit is only supported with BrowserSkill")
    if bool(args.session) != (args.tab_id is not None):
        parser.error("--session and --tab-id must be provided together")
    if args.browser == "playwright" and args.session:
        parser.error("--session/--tab-id are only supported with BrowserSkill")
    if args.job_url is not None:
        return args
    try:
        args.job_url = load_default_test_job_url()
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return args


def parse_job_url(argv: list[str] | None = None) -> str:
    return parse_options(argv).job_url


if __name__ == "__main__":
    options = parse_options()
    if options.all_test_jobs:
        from app.config.loader import load_test_job_urls
        for url in load_test_job_urls():
            print("=" * 70)
            try:
                main(url, options.browser, submit=options.submit)
            except Exception as error:  # one failing job must not stop the batch
                print("JOB FAILED:", url, "→", error)
    else:
        main(options.job_url, options.browser, options.session, options.tab_id, options.submit)
