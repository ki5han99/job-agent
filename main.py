from app.browser.client import BrowserClient
from app.config.loader import load_preferences, load_profile
from app.jobs.filters import passes_hard_filters
from app.jobs.greenhouse import extract_greenhouse_job
from app.jobs.scorer import score_job
from app.jobs.scorer import score_job, classify_score 
from app.jobs.form_parser import parse_form_fields  
from app.jobs.field_mapper import map_field_to_value
from app.jobs.form_filler import fill_ready_fields

def main():
    browser = BrowserClient()
    browser.start()

    try:
        job = extract_greenhouse_job(
            browser,
            "https://job-boards.greenhouse.io/mill/jobs/4722052005",
        )

        fields = parse_form_fields(browser)
        profile = load_profile()

        fill_ready_fields(
            browser=browser,
            fields=fields,
            profile=profile,
        )

        print()
        print("READY fields have been filled.")
        

        print()
        print("=== FIELD MAPPINGS ===")

        for field in fields:
            mapping = map_field_to_value(field, profile)

            print(
                f"{mapping.label!r} "
                f"→ {mapping.value!r} "
                f"[{mapping.status}]"
            )
        
        print()
        print("=== APPLICATION FIELDS ===")

        for field in fields:
            print(
                f"Label: {field.label!r} | "
                f"Type: {field.field_type} | "
                f"ID: {field.field_id!r} | "
                f"Required: {field.required}"
            )

        preferences = load_preferences()
        profile = load_profile()
        

        filter_result = passes_hard_filters(job, preferences)
        

        print("Title:", job.title)
        print("Company:", job.company)
        print("Passed:", filter_result.passed)
        print("Reasons:", filter_result.reasons)

        if filter_result.passed:
            score = score_job(job, profile)

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
        

    finally:
        browser.close()
    


if __name__ == "__main__":
    main()