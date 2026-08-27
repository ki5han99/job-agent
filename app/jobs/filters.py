from app.config.models import Preferences
from app.jobs.models import FilterResult, Job

def passes_hard_filters(
    job: Job,
    preferences: Preferences,
) -> FilterResult:
    reasons: list[str] = []

    if (
        job.required_experience_years is not None
        and job.required_experience_years
        > preferences.experience.maximum_required_years
    ):
        reasons.append(
            f"Requires {job.required_experience_years} years of experience, "
            f"but maximum allowed is "
            f"{preferences.experience.maximum_required_years}."
        )

    if (
        job.seniority is not None
        and job.seniority in preferences.seniority.excluded
    ):
        reasons.append(
            f"Seniority '{job.seniority}' is excluded."
        )

    if (
        job.employment_type is not None
        and job.employment_type
        not in preferences.employment_types
    ):
        reasons.append(
            f"Employment type '{job.employment_type}' is not allowed."
        )

    if (
        job.work_arrangement is not None
        and not work_arrangement_allowed(
            job.work_arrangement,
            preferences,
        )
    ):
        reasons.append(
            f"Work arrangement '{job.work_arrangement}' is not allowed."
        )

    passed = len(reasons) == 0

    return FilterResult(
    passed=passed,
    reasons=reasons,
)


def work_arrangement_allowed(
    arrangement: str,
    preferences: Preferences,
) -> bool:
    normalized = arrangement.strip().lower()

    if normalized == "remote":
        return preferences.work_arrangements.remote

    if normalized == "hybrid":
        return preferences.work_arrangements.hybrid

    if normalized == "onsite":
        return preferences.work_arrangements.onsite

    return False