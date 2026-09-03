from datetime import datetime

from app.config.models import Profile


def parse_profile_date(value: str) -> datetime:
    supported_formats = [
        "%Y-%m",
        "%m/%Y",
        "%Y-%m-%d",
    ]

    for date_format in supported_formats:
        try:
            return datetime.strptime(
                value,
                date_format,
            )
        except ValueError:
            continue

    raise ValueError(
        f"Unsupported profile date format: {value}"
    )


def calculate_total_experience_years(
    profile: Profile,
) -> float:
    total_months = 0

    for exp in profile.experience:
        start = parse_profile_date(
            exp.start_date
        )

        if exp.end_date:
            end = parse_profile_date(
                exp.end_date
            )
        else:
            end = datetime.now()

        months = (
            (end.year - start.year) * 12
            + (end.month - start.month)
        )

        total_months += max(
            months,
            0,
        )

    return round(
        total_months / 12,
        1,
    )