from typing import Literal

from pydantic import BaseModel


class ExtractedJobData(BaseModel):
    required_experience_years: int | None

    seniority: Literal[
        "Entry Level",
        "Associate",
        "Mid Level",
        "Senior",
        "Staff",
        "Principal",
        "Director",
        "VP",
    ] | None

    employment_type: Literal[
        "Full Time",
        "Part Time",
        "Contract",
        "Internship",
        "Temporary",
    ] | None

    work_arrangement: Literal[
        "Remote",
        "Hybrid",
        "Onsite",
    ] | None

    sponsorship_available: bool | None
    security_clearance_required: bool | None


class Job(BaseModel):
    title: str
    company: str
    location: str
    description: str

    required_experience_years: int | None
    seniority: str | None
    employment_type: str | None
    work_arrangement: str | None

    sponsorship_available: bool | None
    security_clearance_required: bool | None

    source: str
    url: str


class FilterResult(BaseModel):
    passed: bool
    reasons: list[str]