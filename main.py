from app.config.loader import load_preferences
from app.jobs.extractor import extract_job
from app.jobs.filters import passes_hard_filters


def main():
    preferences = load_preferences()

    description = """
        We are seeking a Senior Data Engineer to build and maintain
        large-scale data pipelines using Python, Spark, and AWS.

        Candidates should have at least 5 years of professional
        data engineering experience.

        This is a full-time hybrid position requiring employees
        to work from our New York office three days per week.

        Applicants must be authorized to work in the United States.
        We are unable to sponsor employment visas now or in the future.

        No security clearance is required for this position.
        """

    job = extract_job(
        title="Senior Data Engineer",
        company="Example Corp",
        location="New York, NY",
        description=description,
        source="Test",
        url="https://example.com/jobs/123",
    )

    print()
    print("=== QWEN EXTRACTION ===")
    print("Title:", job.title)
    print("Experience:", job.required_experience_years)
    print("Seniority:", job.seniority)
    print("Employment type:", job.employment_type)
    print("Work arrangement:", job.work_arrangement)
    print("Sponsorship:", job.sponsorship_available)
    print("Clearance required:", job.security_clearance_required)

    result = passes_hard_filters(job, preferences)

    print()
    print("=== HARD FILTER RESULT ===")
    print("Passed:", result.passed)
    print("Reasons:", result.reasons)


if __name__ == "__main__":
    main()